"""Whole-batch expiry review, terminal writes and retry/failure/privacy fences."""

import json
import sqlite3
import threading

import pytest

from personal_agent import memory_expiry, memory_retention
from personal_agent.conversation_memory import parse_command
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService, validate_request
from personal_agent.memory_edits import PrivateEdits
from personal_agent.memory_presentation import render_memory_result
from personal_agent.memory_projection import PrivateProjection

NOW = "2026-11-09T12:00:00Z"
PAST = "2026-11-08T12:00:00Z"
FUTURE = "2026-11-10T12:00:00Z"


def opened(directory, *, files=True, factory=sqlite3.Connection, source="explicit_local_operator"):
    conn = sqlite3.connect(directory / "records.sqlite3", isolation_level=None, factory=factory)
    backend = create_backend()
    backend.open(
        conn,
        namespace_id="test",
        session_ref="operator",
        source_kind=source,
        edits=PrivateEdits(directory) if files else None,
        projection=PrivateProjection(directory) if files else None,
    )
    return backend, conn


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: NOW)
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700)
    backend, conn = opened(directory)
    yield backend, conn, directory
    backend.close()
    conn.close()


def save(backend, key="seed", **fields):
    return backend.execute(
        "remember",
        {"content": "private expired payload", "expires_at": PAST, "request_id": key, **fields},
    )["data"]["record_id"]


def review(backend, **fields):
    return backend.execute("expired_preview", {"before": NOW, **fields})


def request(backend, key="cleanup", **fields):
    preview = review(backend, **fields)
    return {
        "before": preview["before"],
        "limit": preview["limit"],
        "expected_snapshot": preview["snapshot"],
        "request_id": key,
    }


def error(code, call):
    with pytest.raises(MemoryError) as caught:
        call()
    assert caught.value.code == code


def canonical(conn):
    return {
        table: conn.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("records", "events", "receipts", "memory_edits", "memory_projection")
    }


def test_preview_complete_selected_records_counts_and_order_without_writes(store):
    b, c, _ = store
    later = save(b, "later", expires_at=NOW)
    first = save(b, "first", content="中文\n# untrusted <script>", topic="出行")
    second = save(b, "second")
    save(b, "future", expires_at=FUTURE)
    save(b, "keep", expires_at=None)
    forgotten = save(b, "forgotten")
    b.execute("forget", {"record_id": forgotten, "expected_revision": 1, "request_id": "f"})
    before = canonical(c)
    data = review(b, limit=2)
    assert [item["record_id"] for item in data["items"]] == [first, second]
    assert data["items"][0] == b.execute("get", {"record_id": first})
    assert data["eligible_count"] == 3
    assert data["selected_count"] == 2
    assert data["remaining_count"] == 1
    assert data["evaluated_at"] == NOW and data["before"] == NOW
    assert len(json.dumps(data, sort_keys=True, ensure_ascii=True)) <= 64000
    assert canonical(c) == before
    assert review(b)["items"][-1]["record_id"] == later


def test_apply_uses_ordinary_terminal_forget_metadata_and_index_path(store):
    b, c, d = store
    ids = [save(b, str(i), content=f"needle{i} private") for i in range(3)]
    reader = sqlite3.connect(d / "records.sqlite3")
    assert (
        reader.execute(
            "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'needle0'"
        ).fetchone()[0]
        == 1
    )
    action = request(b, limit=2)
    result = MemoryService(b).execute("forget_expired", action)
    data = result["data"]
    assert not result["replayed"]
    assert data["forgotten_count"] == 2 and data["remaining_count"] == 1
    assert data["previous_watermark"] == 3 and data["watermark"] == 5
    for rid in ids[:2]:
        record = b.execute("get", {"record_id": rid})
        assert record["revision"] == 2 and record["status"] == "forgotten"
        assert all(
            record[key] is None
            for key in ("content", "topic", "source", "session_ref", "expires_at")
        )
    assert b.execute("get", {"record_id": ids[2]})["status"] == "active"
    assert c.execute("SELECT count(*) FROM records").fetchone()[0] == 3
    assert (
        c.execute("SELECT operation FROM events ORDER BY sequence").fetchall()
        == [("remember",)] * 3 + [("forget",)] * 2
    )
    assert (
        reader.execute(
            "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'needle0'"
        ).fetchone()[0]
        == 0
    )
    reader.close()
    with sqlite3.connect(d / "records.sqlite3") as fresh:
        fresh.execute("INSERT INTO memory_fts(memory_fts) VALUES ('integrity-check')")
    for (receipt,) in c.execute("SELECT receipt FROM receipts"):
        assert "private" not in receipt and "needle" not in receipt
    assert c.execute("PRAGMA user_version").fetchone()[0] == 12


def test_retry_before_selection_after_restart_clock_rollback_and_unknown_files(store, monkeypatch):
    b, c, d = store
    ids = [save(b, str(i)) for i in range(3)]
    b.execute("projection_refresh", {})
    action = request(b, limit=1)
    receipt = b.execute("forget_expired", action)["data"]
    assert not (d / "records.md").exists()
    (d / "records.md").write_text("unknown replacement, do not touch")
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2020-01-01T00:00:00Z")
    restarted, connection = opened(d)
    try:
        before = canonical(c)
        assert restarted.execute("forget_expired", action) == {"data": receipt, "replayed": True}
        assert canonical(c) == before
        assert (d / "records.md").read_text() == "unknown replacement, do not touch"
        assert b.execute("get", {"record_id": ids[1]})["status"] == "active"
        error(
            "idempotency_conflict",
            lambda: restarted.execute("forget_expired", {**action, "limit": 2}),
        )
    finally:
        restarted.close()
        connection.close()


def test_new_key_cannot_consume_remaining_batch_with_old_snapshot(store):
    b, _, _ = store
    save(b, "first")
    save(b, "second")
    action = request(b, limit=1)
    b.execute("forget_expired", action)
    error(
        "retention_snapshot_conflict",
        lambda: b.execute("forget_expired", {**action, "request_id": "new"}),
    )
    assert review(b)["remaining_count"] == 0 and review(b)["selected_count"] == 1
    b.execute("forget_expired", request(b, "next"))
    empty = request(b, "empty")
    error("retention_empty_batch", lambda: b.execute("forget_expired", empty))


@pytest.mark.parametrize("change", ["content", "expiry", "clear", "forget", "new", "unselected"])
def test_stale_snapshot_fails_closed_for_canonical_changes(store, change):
    b, c, _ = store
    rid = save(b)
    other = save(b, "other", expires_at=NOW)
    action = request(b, limit=1)
    if change == "new":
        save(b, "new", expires_at=None)
    elif change == "forget":
        b.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "change"})
    else:
        fields = (
            {"content": "updated"}
            if change in {"content", "unselected"}
            else {"expires_at": FUTURE if change == "expiry" else None}
        )
        b.execute(
            "correct",
            {
                "record_id": other if change == "unselected" else rid,
                "expected_revision": 1,
                "request_id": "change",
                **fields,
            },
        )
    before = canonical(c)
    error("retention_snapshot_conflict", lambda: b.execute("forget_expired", action))
    assert canonical(c) == before


def test_fixed_cutoff_does_not_expand_with_time_and_snapshot_does_not_bind_evaluation(
    store, monkeypatch
):
    b, _, _ = store
    old = save(b)
    newer = save(b, "later", expires_at=FUTURE)
    action = request(b)
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-11-11T12:00:00Z")
    assert review(b)["snapshot"] == action["expected_snapshot"]
    assert b.execute("forget_expired", action)["data"]["forgotten_count"] == 1
    assert b.execute("get", {"record_id": old})["status"] == "forgotten"
    assert b.execute("get", {"record_id": newer})["status"] == "active"


@pytest.mark.parametrize(
    "before",
    [
        None,
        False,
        "",
        "2026-11-09",
        "2026-11-09T12:00:00+00:00",
        "2026-11-09T12:00:00.0Z",
        "2026-02-29T00:00:00Z",
    ],
)
def test_invalid_cutoff(before):
    error("invalid_request", lambda: validate_request("expired_preview", {"before": before}))


@pytest.mark.parametrize("limit", [0, 21, True, "1", None, 1.5])
def test_invalid_batch_limit(limit):
    error(
        "invalid_request",
        lambda: validate_request("expired_preview", {"before": NOW, "limit": limit}),
    )


def test_future_cutoff_and_clock_rollback_refuse_new_deletion(store, monkeypatch):
    b, c, _ = store
    save(b)
    error("retention_future_cutoff", lambda: review(b, before=FUTURE))
    action = request(b)
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: PAST)
    before = canonical(c)
    error("retention_future_cutoff", lambda: b.execute("forget_expired", action))
    assert canonical(c) == before


def test_preview_budget_counts_full_ascii_data_without_partial_approval(store):
    b, c, _ = store
    for i in range(3):
        save(b, str(i), content="😀" * 2048, topic="📝" * 128)
    before = canonical(c)
    error("retention_preview_too_large", lambda: review(b))
    one = review(b, limit=1)
    assert len(one["items"][0]["content"]) == 2048
    assert one["remaining_count"] == 2
    assert len(json.dumps(one, ensure_ascii=True, sort_keys=True)) <= 64000
    assert canonical(c) == before


def test_global_expiry_validation_cannot_hide_corrupt_unselected_record(store):
    b, c, _ = store
    save(b)
    rid = save(b, "bad", expires_at=FUTURE)
    c.execute("UPDATE records SET expires_at='broken' WHERE record_id=?", (rid,))
    error("storage_corrupt", lambda: review(b, limit=1))


def test_public_keys_cannot_collide_with_child_and_internal_collision_refused(store):
    b, c, _ = store
    rid = save(b)
    action = request(b)
    key = memory_retention._child_key(action["request_id"], rid)
    for operation, payload in (
        ("forget_expired", {**action, "request_id": key}),
        ("forget", {"record_id": rid, "expected_revision": 1, "request_id": key}),
        ("remember", {"content": "public", "request_id": key}),
    ):
        error("invalid_request", lambda op=operation, p=payload: b.execute(op, p))
    c.execute("INSERT INTO receipts VALUES (?,?,?)", (key, "collision", "{}"))
    before = canonical(c)
    error("idempotency_conflict", lambda: b.execute("forget_expired", action))
    assert canonical(c) == before


def test_batch_keys_share_public_canonical_receipt_namespace(store):
    b, c, _ = store
    save(b, "used")
    before = canonical(c)
    error("idempotency_conflict", lambda: b.execute("forget_expired", request(b, "used")))
    assert canonical(c) == before
    action = request(b)
    b.execute("forget_expired", action)
    error("idempotency_conflict", lambda: save(b, "cleanup"))


def test_operator_only_preview_and_apply_with_unchanged_model_contract(store):
    from personal_agent.memory_tool_contract import normalize_memory_tool_request

    b, _, d = store
    save(b)
    action = request(b)
    model, c = opened(d, source="activated_session_model")
    reader, r = create_backend(), sqlite3.connect(d / "records.sqlite3")
    reader.open_readonly(r, namespace_id="test", session_ref="reader")
    try:
        for backend in (model, reader):
            for operation, payload in (
                ("expired_preview", {"before": NOW}),
                ("forget_expired", action),
            ):
                error(
                    "retention_scope_required",
                    lambda b=backend, op=operation, p=payload: b.execute(op, p),
                )
        for tool in ("personal_memory_read", "personal_memory_write"):
            for operation in ("expired_preview", "forget_expired"):
                error(
                    "invalid_request",
                    lambda t=tool, op=operation: normalize_memory_tool_request(t, {"action": op}),
                )
    finally:
        model.close()
        c.close()
        reader.close()
        r.close()


def test_capability_negotiation_refuses_old_adapter_before_dispatch(store):
    b, _, _ = store
    describe = b.describe
    b.describe = lambda: {
        **describe(),
        "capabilities": [x for x in describe()["capabilities"] if x != "reviewed_expired_cleanup"],
    }
    service = MemoryService(b)
    error("capability_unavailable", lambda: service.execute("expired_preview", {"before": NOW}))


def test_registered_draft_and_projection_cleanup_and_terminal_replay(store):
    b, c, d = store
    rid = save(b)
    did = b.execute(
        "edit_create", {"record_id": rid, "expected_revision": 1, "request_id": "draft"}
    )["data"]["draft_id"]
    (d / "edit.md").write_text("manual replacement must be removed")
    b.execute("projection_refresh", {})
    action = request(b)
    b.execute("forget_expired", action)
    assert not (d / "edit.md").exists() and not (d / "records.md").exists()
    assert (
        c.execute("SELECT state FROM memory_edits WHERE draft_id=?", (did,)).fetchone()[0]
        == "invalidated"
    )
    assert b.execute("projection_status", {})["dirty"]
    (d / "edit.md").write_text("unknown after terminal")
    b.execute("forget_expired", action)
    assert (d / "edit.md").read_text() == "unknown after terminal"


def test_unselected_draft_preserved_and_bare_backend_cannot_bypass_files(store):
    b, c, d = store
    save(b)
    other = save(b, "other", expires_at=FUTURE)
    b.execute("edit_create", {"record_id": other, "expected_revision": 1, "request_id": "draft"})
    draft = (d / "edit.md").read_bytes()
    b.execute("projection_refresh", {})
    bare, bc = opened(d, files=False)
    try:
        action = request(b)
        before = canonical(c)
        error("projection_storage_required", lambda: bare.execute("forget_expired", action))
        assert canonical(c) == before
        b.execute("forget_expired", action)
        assert (d / "edit.md").read_bytes() == draft
    finally:
        bare.close()
        bc.close()


def test_mid_batch_failure_rolls_back_database_but_not_removed_files(store, monkeypatch):
    b, c, d = store
    ids = [save(b, str(i)) for i in range(2)]
    b.execute("edit_create", {"record_id": ids[0], "expected_revision": 1, "request_id": "draft"})
    b.execute("projection_refresh", {})
    action = request(b)
    before = canonical(c)
    mutate = b._mutate
    calls = []

    def fault(*args):
        calls.append(args[2]["record_id"])
        result = mutate(*args)
        if len(calls) == 2:
            raise sqlite3.OperationalError("synthetic second mutation failure")
        return result

    monkeypatch.setattr(b, "_mutate", fault)
    error("storage_error", lambda: b.execute("forget_expired", action))
    assert calls == ids and canonical(c) == before and not c.in_transaction
    assert not (d / "edit.md").exists() and not (d / "records.md").exists()
    monkeypatch.setattr(b, "_mutate", mutate)
    assert b.execute("forget_expired", action)["data"]["forgotten_count"] == 2


@pytest.mark.parametrize("after", [False, True])
def test_commit_failure_and_lost_response_retry(store, after):
    b, c, d = store
    save(b, "first")
    save(b, "second")
    action = request(b)

    class Fault(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            if self.armed and sql == "COMMIT":
                self.armed = False
                if after:
                    super().execute(sql, *args)
                raise sqlite3.OperationalError("synthetic commit failure")
            return super().execute(sql, *args)

    failing, fc = opened(d, factory=Fault)
    try:
        before = canonical(c)
        fc.armed = True
        error("storage_error", lambda: failing.execute("forget_expired", action))
        assert not fc.in_transaction
        if not after:
            assert canonical(c) == before
        result = failing.execute("forget_expired", action)
        assert result["replayed"] is after
        assert c.execute("SELECT count(*) FROM events WHERE operation='forget'").fetchone()[0] == 2
    finally:
        failing.close()
        fc.close()


def test_competing_batches_one_commit_and_one_stale_snapshot(store):
    b, c, d = store
    for i in range(3):
        save(b, str(i))
    action = request(b, limit=2)
    barrier = threading.Barrier(2)
    results = []

    def worker(key):
        other, connection = opened(d)
        try:
            barrier.wait(timeout=5)
            try:
                results.append(other.execute("forget_expired", {**action, "request_id": key}))
            except MemoryError as exc:
                results.append(exc.code)
        finally:
            other.close()
            connection.close()

    threads = [threading.Thread(target=worker, args=(key,)) for key in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(results) == 2
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "retention_snapshot_conflict" in results
    assert c.execute("SELECT count(*) FROM events WHERE operation='forget'").fetchone()[0] == 2


def test_native_parser_requires_explicit_stable_id_and_full_ascii_success_view(store):
    b, _, _ = store
    save(b, content="中文\nprivate")
    assert parse_command(f"expired-preview --before {NOW}") == (
        "expired_preview",
        {"before": NOW, "limit": 10},
    )
    action = request(b)
    raw = f"forget-expired --before {NOW} --expected-snapshot {action['expected_snapshot']}"
    error("invalid_request", lambda: parse_command(raw))
    assert parse_command(raw + " --request-id stable")[1]["request_id"] == "stable"
    data = review(b)
    envelope = {"status": "ok", "data": data, "replayed": False, "error": None}
    rendered = render_memory_result(envelope, operation="expired_preview", payload={})
    assert rendered.isascii() and json.loads(rendered) == envelope
    failed = {
        "status": "error",
        "error": {"code": "retention_preview_too_large", "retryable": False},
    }
    assert "Reduce --limit" in render_memory_result(failed, operation="expired_preview", payload={})


def test_time_sample_after_writer_acquisition_and_snapshot_establishment(store, monkeypatch):
    b, _, d = store
    save(b, expires_at=NOW)
    action = request(b)
    trace = []

    class ClockAtLock(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed:
                trace.append(sql)
                if sql == "BEGIN IMMEDIATE":
                    # The wall clock moves back while acquiring the writer.
                    monkeypatch.setattr(memory_expiry, "utc_now", lambda: PAST)
            return result

    other, conn = opened(d, factory=ClockAtLock)
    try:
        conn.armed = True
        error("retention_future_cutoff", lambda: other.execute("forget_expired", action))
        assert trace[0] == "BEGIN IMMEDIATE"
        assert (
            conn.execute("SELECT count(*) FROM events WHERE operation='forget'").fetchone()[0] == 0
        )
    finally:
        other.close()
        conn.close()


def test_expired_preview_samples_time_after_read_snapshot(store, monkeypatch):
    b, _, d = store
    save(b)

    class ClockAtSnapshot(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and sql == "SELECT id FROM namespace":
                monkeypatch.setattr(memory_expiry, "utc_now", lambda: PAST)
            return result

    other, conn = opened(d, factory=ClockAtSnapshot)
    try:
        conn.armed = True
        error("retention_future_cutoff", lambda: review(other))
        assert not conn.in_transaction
    finally:
        other.close()
        conn.close()


def test_maximum_record_and_mutation_caps_are_not_reset(store):
    b, c, _ = store
    rid = save(b)
    # Synthetic saturation avoids 10,000 filesystem transactions. Metadata is
    # internally consistent: one record has 9,001 revisions; 999 others have one.
    from uuid import uuid4

    c.execute("BEGIN IMMEDIATE")
    c.executemany(
        "INSERT INTO events(record_id,revision,operation) VALUES (?,?,'correct')",
        [(rid, revision) for revision in range(2, 9002)],
    )
    c.execute("UPDATE records SET revision=9001 WHERE record_id=?", (rid,))
    for _ in range(999):
        other = str(uuid4())
        c.execute(
            "INSERT INTO records(record_id,revision,status,content,topic,source,session_ref,"
            "created_at,updated_at,expires_at) VALUES (?,1,'active','kept','',"
            "'explicit_local_operator',"
            "'s',?,?,NULL)",
            (other, NOW, NOW),
        )
        c.execute(
            "INSERT INTO events(record_id,revision,operation) VALUES (?,1,'remember')", (other,)
        )
    c.execute(
        "INSERT INTO memory_fts(rowid,content,topic) "
        "SELECT sequence,content,topic FROM records WHERE record_id != ?",
        (rid,),
    )
    c.execute("COMMIT")
    assert c.execute("SELECT count(*) FROM events").fetchone()[0] == 10000
    error("mutation_limit", lambda: save(b, "blocked"))
    assert b.execute("forget_expired", request(b))["data"]["forgotten_count"] == 1
    assert c.execute("SELECT count(*) FROM records").fetchone()[0] == 1000
    error("mutation_limit", lambda: save(b, "still-blocked"))
    assert (
        c.execute("SELECT count(*) FROM events WHERE operation != 'forget'").fetchone()[0] == 10000
    )


@pytest.mark.parametrize("files", ["projection", "edit"])
def test_managed_file_cleanup_failure_rolls_back_entire_batch(store, monkeypatch, files):
    b, c, d = store
    ids = [save(b, str(i)) for i in range(2)]
    if files == "projection":
        b.execute("projection_refresh", {})
        target, method = b._projection, "invalidate"
    else:
        b.execute(
            "edit_create", {"record_id": ids[1], "expected_revision": 1, "request_id": "draft"}
        )
        target, method = b._edits, "remove"
    action = request(b)
    before = canonical(c)

    def fail(*args):
        raise MemoryError("unsafe_storage_file")

    monkeypatch.setattr(target, method, fail)
    error("unsafe_storage_file", lambda: b.execute("forget_expired", action))
    assert canonical(c) == before and not c.in_transaction
    assert (d / ("records.md" if files == "projection" else "edit.md")).exists()
