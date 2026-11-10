"""Explicit expiry is read-time eligibility, never a timed destructive edit."""

import json
import sqlite3
from uuid import uuid4

import pytest

from personal_agent import local_memory, memory_expiry
from personal_agent.memory_backend import MemoryError, MemoryService, validate_request

NOW = "2026-11-07T12:00:00Z"


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: NOW)
    conn = sqlite3.connect(":memory:")
    backend = local_memory.create_backend()
    backend.open(conn, namespace_id="expiry", session_ref="test")
    yield backend, conn
    backend.close()
    conn.close()


def save(b, key="r", **kw):
    return b.execute("remember", {"content": "temporary plan", "request_id": key, **kw})["data"][
        "record_id"
    ]


@pytest.mark.parametrize(
    "value",
    [
        "",
        0,
        False,
        "2026-02-29T00:00:00Z",
        "0000-01-01T00:00:00Z",
        "2026-11-07T24:00:00Z",
        "2026-11-07T12:00:60Z",
        "2026-11-07T12:00:00+00:00",
        "2026-11-07T12:00:00.0Z",
        "2026-1-07T12:00:00Z",
        "2026-11-07t12:00:00z",
        "２０２６-11-07T12:00:00Z",
    ],
)
def test_reject_noncanonical_expiry(value):
    with pytest.raises(MemoryError, match="invalid_request"):
        validate_request("remember", {"content": "x", "request_id": "r", "expires_at": value})


@pytest.mark.parametrize(
    "value", [None, "0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z", "2024-02-29T00:00:00Z"]
)
def test_accept_expiry_bounds(value):
    assert (
        validate_request("remember", {"content": "x", "request_id": "r", "expires_at": value})[
            "expires_at"
        ]
        == value
    )


def test_boundary_roll_back_clock_no_events_and_receipts(store, monkeypatch):
    b, c = store
    rid = save(b, expires_at="2026-11-07T12:00:01Z")
    before = list(c.iterdump())
    assert len(b.execute("recall", {"queries": ["plan"]})["items"]) == 1
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-11-07T12:00:01Z")
    for op, payload in [
        ("list", {}),
        ("search", {"query": "plan"}),
        ("recall", {"queries": ["plan"]}),
    ]:
        result = b.execute(op, payload)
        assert result["items"] == []
        assert result["evaluated_at"] == "2026-11-07T12:00:01Z"
    assert b.execute("get", {"record_id": rid})["expired"] is True
    assert b.execute("export", {})["items"][0]["expired"] is True
    assert save(b, expires_at="2026-11-07T12:00:01Z") == rid
    assert list(c.iterdump()) == before
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: NOW)
    assert b.execute("list", {})["items"][0]["expired"] is False


def test_correct_preserve_clear_and_forget(store):
    b, c = store
    rid = save(b)

    def edit(rev, **kw):
        return b.execute(
            "correct",
            {"record_id": rid, "request_id": f"edit{rev}", "expected_revision": rev, **kw},
        )

    edit(1, expires_at=NOW)
    edit(2, topic="updated")
    assert b.execute("get", {"record_id": rid})["expires_at"] == NOW
    edit(3, expires_at=None)
    assert b.execute("list", {})["items"][0]["expired"] is False
    edit(4, expires_at=NOW)
    b.execute("forget", {"record_id": rid, "expected_revision": 5, "request_id": "f"})
    row = b.execute("get", {"record_id": rid})
    assert row["expired"] is False and row["expires_at"] is None
    assert row["content"] is None
    assert b.execute("list", {"include_expired": True})["items"] == []
    with pytest.raises(MemoryError, match="record_forgotten"):
        edit(6, expires_at=None)


@pytest.mark.parametrize("operation,payload", [("list", {}), ("search", {"query": "plan"})])
def test_pagination_skips_expired_gaps(store, operation, payload):
    b, _ = store
    ids = [save(b, str(i), expires_at=NOW if i % 2 else None) for i in range(7)]
    page = b.execute(operation, {**payload, "limit": 2})
    assert [x["record_id"] for x in page["items"]] == [ids[6], ids[4]]
    second = b.execute(operation, {**payload, "limit": 2, "after": page["next_cursor"]})
    assert [x["record_id"] for x in second["items"]] == [ids[2], ids[0]]
    assert not second["has_more"]
    assert len(b.execute(operation, {**payload, "include_expired": True})["items"]) == 7


def test_one_clock_read_and_budget(store, monkeypatch):
    b, _ = store
    save(b, "expired", expires_at=NOW)
    save(b, "live")
    calls = []

    def now():
        calls.append(1)
        return NOW

    monkeypatch.setattr(memory_expiry, "utc_now", now)
    result = b.execute("recall", {"queries": ["plan"], "max_chars": 1024})
    assert len(calls) == 1
    assert result["matched_records"] == 1
    assert result["items_json_chars"] == len(
        json.dumps(result["items"], ensure_ascii=True, sort_keys=True)
    )


def test_clock_is_sampled_after_sqlite_snapshot_acquisition(store, monkeypatch):
    b, c = store
    boundary = "2026-11-07T12:00:01Z"
    save(b, expires_at=boundary)
    clock = {"now": NOW}
    samples = []

    def now():
        samples.append(clock["now"])
        return clock["now"]

    def acquire_snapshot(statement):
        if statement == "SELECT id FROM namespace":
            # Simulate elapsed time while obtaining the first read snapshot.
            clock["now"] = boundary

    monkeypatch.setattr(memory_expiry, "utc_now", now)
    c.set_trace_callback(acquire_snapshot)
    result = b.execute("list", {})
    c.set_trace_callback(None)
    assert samples == [boundary]
    assert result["evaluated_at"] == boundary and result["items"] == []


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("list", {}),
        ("search", {"query": "unmatched"}),
        ("recall", {"queries": ["unmatched"]}),
        ("export", {}),
    ],
)
def test_malformed_stored_expiry_fails_closed(store, operation, payload):
    b, c = store
    save(b)
    c.execute("UPDATE records SET expires_at='ambiguous'")
    c.commit()
    with pytest.raises(MemoryError, match="storage_corrupt"):
        b.execute(operation, payload)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_all_migrations_identical_and_atomic(version):
    schema = getattr(local_memory, f"_SCHEMA_V{version}")
    c = sqlite3.connect(":memory:")
    for sql in schema.values():
        c.execute(sql)
    c.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    c.execute(f"PRAGMA user_version={version}")
    c.execute("INSERT INTO namespace VALUES ('expiry')")
    rid = str(uuid4())
    c.execute(
        "INSERT INTO records VALUES (9,?,1,'active','old','', "
        "'explicit_local_operator','s','t','t')",
        (rid,),
    )
    c.commit()
    before = list(c.iterdump())
    c.set_authorizer(
        lambda action, *args: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_ALTER_TABLE and args[1] == "records" and version != 1
            else sqlite3.SQLITE_OK
        )
    )
    if version != 1:
        with pytest.raises(MemoryError):
            local_memory.create_backend().open(c, namespace_id="expiry", session_ref="s")
        assert list(c.iterdump()) == before
    c.set_authorizer(None)
    b = local_memory.create_backend()
    b.open(c, namespace_id="expiry", session_ref="s")
    assert (
        dict(c.execute("SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"))
        == local_memory._SCHEMA
    )
    assert b.execute("get", {"record_id": rid})["expires_at"] is None
    assert c.execute("PRAGMA user_version").fetchone() == (11,)
    b.close()
    c.close()


def test_optional_capability_gates_explicit_fields(store):
    b, _ = store

    class Incapable:
        def describe(self):
            desc = b.describe()
            desc["capabilities"].remove("record_expiry")
            return desc

        def execute(self, *args):
            return b.execute(*args)

        def close(self):
            pass

    service = MemoryService(Incapable())
    assert service.execute("list", {})["data"]["items"] == []
    for op, payload in [
        ("list", {"include_expired": False}),
        ("remember", {"content": "x", "request_id": "r", "expires_at": None}),
    ]:
        with pytest.raises(MemoryError, match="capability_unavailable"):
            service.execute(op, payload)


def test_reader_requires_writer_migration(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    for sql in local_memory._SCHEMA_V4.values():
        c.execute(sql)
    c.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    c.execute("PRAGMA user_version=4")
    c.execute("INSERT INTO namespace VALUES ('expiry')")
    c.commit()
    before = list(c.iterdump())
    reader = local_memory.create_backend()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        reader.open_readonly(ro, namespace_id="expiry", session_ref="r")
    assert list(c.iterdump()) == before
    writer = local_memory.create_backend()
    writer.open(c, namespace_id="expiry", session_ref="w")
    reader.open_readonly(ro, namespace_id="expiry", session_ref="r")
    assert reader.execute("list", {})["items"] == []
    reader.close()
    writer.close()
    ro.close()
    c.close()


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_include_expired_strict_bool(value):
    with pytest.raises(MemoryError, match="invalid_request"):
        validate_request("list", {"include_expired": value})


def test_invalid_get_expiry_redacted(store):
    b, c = store
    rid = save(b)
    c.execute("UPDATE records SET expires_at='2026-02-30T00:00:00Z'")
    c.commit()
    with pytest.raises(MemoryError, match="storage_corrupt") as err:
        b.execute("get", {"record_id": rid})
    assert "temporary" not in str(err.value)


def test_v4_receipts_progress_and_checkpoints_survive_expiry_migration(monkeypatch):
    import hashlib

    from personal_agent.memory_checkpoints import create_checkpoint
    from personal_agent.memory_progress import advance_consumer

    monkeypatch.setattr(memory_expiry, "utc_now", lambda: NOW)
    c = sqlite3.connect(":memory:")
    for sql in local_memory._SCHEMA_V4.values():
        c.execute(sql)
    c.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    c.execute("PRAGMA user_version=4")
    c.execute("INSERT INTO namespace VALUES ('expiry')")
    rid = str(uuid4())
    c.execute(
        "INSERT INTO records VALUES (7,?,1,'active','legacy plan','',"
        "'explicit_local_operator','legacy-session','created','updated')",
        (rid,),
    )
    c.execute("INSERT INTO events VALUES (3,?,1,'remember')", (rid,))
    # The actual old normalization: absent topic became empty; expiry did not exist.
    old_request = {"content": "legacy plan", "request_id": "old", "topic": ""}
    digest = hashlib.sha256(
        json.dumps(
            ["remember", old_request], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    old_receipt = {
        "record_id": rid,
        "revision": 1,
        "status": "active",
        "operation": "remember",
        "request_id": "old",
        "event_sequence": 3,
    }
    c.execute(
        "INSERT INTO receipts VALUES ('old',?,?)", (digest, json.dumps(old_receipt, indent=2))
    )
    consumer_request = {
        "consumer_id": "reader",
        "through_sequence": 3,
        "expected_revision": 0,
        "request_id": "old-cursor",
    }
    cursor_receipt = advance_consumer(c, consumer_request)["data"]
    checkpoint_request = {"expected_watermark": 3, "request_id": "old-checkpoint"}
    checkpoint_receipt = create_checkpoint(c, checkpoint_request)["data"]
    # Distinct whitespace makes any incidental deserialize/reserialize detectable.
    for table in ("consumer_receipts", "record_checkpoints"):
        text = c.execute(f"SELECT receipt FROM {table}").fetchone()[0]
        c.execute(f"UPDATE {table} SET receipt=?", (json.dumps(json.loads(text), indent=3),))
    c.commit()
    names = (
        "namespace",
        "records",
        "events",
        "receipts",
        "consumer_cursors",
        "consumer_receipts",
        "record_checkpoints",
        "sqlite_sequence",
    )
    before = {name: c.execute(f"SELECT * FROM {name}").fetchall() for name in names}
    b = local_memory.create_backend()
    b.open(c, namespace_id="expiry", session_ref="new")
    for name, rows in before.items():
        actual = c.execute(f"SELECT * FROM {name}").fetchall()
        assert actual == ([(*row, None) for row in rows] if name == "records" else rows)
    assert b.execute("remember", {"content": "legacy plan", "request_id": "old"}) == {
        "data": old_receipt,
        "replayed": True,
    }
    assert b.execute("consumer_advance", consumer_request) == {
        "data": cursor_receipt,
        "replayed": True,
    }
    assert b.execute("checkpoint_create", checkpoint_request) == {
        "data": checkpoint_receipt,
        "replayed": True,
    }
    old_checkpoint = {"checkpoint_id": checkpoint_receipt["checkpoint_id"]}
    assert b.execute("checkpoint_status", old_checkpoint)["is_current"] is True
    b.execute(
        "correct",
        {
            "record_id": rid,
            "expected_revision": 1,
            "request_id": "set-expiry",
            "expires_at": "2026-11-07T12:00:01Z",
        },
    )
    assert b.execute("get", {"record_id": rid})["revision"] == 2
    assert b.execute("checkpoint_status", old_checkpoint)["is_current"] is False
    assert b.execute("changes", {})["current_watermark"] == 4
    assert b.execute("consumer_get", {"consumer_id": "reader"})["through_sequence"] == 3
    current_checkpoint = b.execute(
        "checkpoint_create",
        {
            "expected_watermark": 4,
            "request_id": "expiry-checkpoint",
        },
    )["data"]
    status_request = {"checkpoint_id": current_checkpoint["checkpoint_id"]}
    frozen = list(c.iterdump())
    assert len(b.execute("recall", {"queries": ["plan"]})["items"]) == 1
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-11-07T12:00:01Z")
    assert b.execute("recall", {"queries": ["plan"]})["items"] == []
    assert b.execute("checkpoint_status", status_request)["is_current"] is True
    assert b.execute("changes", {})["current_watermark"] == 4
    assert b.execute("consumer_get", {"consumer_id": "reader"})["through_sequence"] == 3
    assert list(c.iterdump()) == frozen
    b.close()
    c.close()


def test_v1_expiry_step_failure_rolls_back_prior_rebuild_and_tables():
    c = sqlite3.connect(":memory:")
    for sql in local_memory._SCHEMA_V1.values():
        c.execute(sql)
    c.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    c.execute("PRAGMA user_version=1")
    c.execute("INSERT INTO namespace VALUES ('expiry')")
    rid = str(uuid4())
    c.execute(
        "INSERT INTO records VALUES (9,?,1,'active','old','',"
        "'explicit_local_operator','old-session','created','updated')",
        (rid,),
    )
    c.execute("INSERT INTO events VALUES (4,?,1,'remember')", (rid,))
    c.execute("UPDATE sqlite_sequence SET seq=20 WHERE name='records'")
    c.commit()
    before = list(c.iterdump())
    before_schema = list(c.execute("SELECT name,sql FROM sqlite_master ORDER BY name"))
    alters, created = [], []

    def deny_expiry_only(action, arg1, arg2, *_):
        if action == sqlite3.SQLITE_CREATE_TABLE:
            created.append(arg1)
        if action == sqlite3.SQLITE_ALTER_TABLE and arg2 == "records":
            alters.append(arg2)
            # First ALTER renames V1 for its rebuild; second adds the V5 column.
            if len(alters) == 2:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    c.set_authorizer(deny_expiry_only)
    b = local_memory.create_backend()
    with pytest.raises(MemoryError, match="storage_error"):
        b.open(c, namespace_id="expiry", session_ref="new")
    c.set_authorizer(None)
    assert len(alters) == 2
    assert {"records", "consumer_cursors", "consumer_receipts", "record_checkpoints"} <= set(
        created
    )
    assert not c.in_transaction
    assert c.execute("PRAGMA user_version").fetchone() == (1,)
    assert list(c.iterdump()) == before
    assert list(c.execute("SELECT name,sql FROM sqlite_master ORDER BY name")) == before_schema
    b.open(c, namespace_id="expiry", session_ref="new")
    assert c.execute("PRAGMA user_version").fetchone() == (11,)
    assert b.execute("get", {"record_id": rid})["expires_at"] is None
    assert c.execute("SELECT seq FROM sqlite_sequence WHERE name='records'").fetchone() == (20,)
    b.close()
    c.close()
