"""Offline durable one-attempt ledger, with real SQLite concurrency and rollback."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent import kanban_handoff_store as module
from personal_agent.kanban_handoff_store import HandoffError, HandoffStore


def intent():
    return {
        "source": {
            "task_id": str(uuid4()),
            "revision": 1,
            "title": "PRIVATE TITLE",
            "details": "PRIVATE DETAILS",
        },
        "destination": {
            "root": "/synthetic/root",
            "board": "scratch",
            "path": "/synthetic/root/board.db",
            "device": 1,
            "inode": 2,
            "schema": "a" * 64,
            "source": "b" * 64,
        },
        "native_title": "PRIVATE NATIVE TITLE",
        "native_body": "PRIVATE NATIVE BODY",
        "key": "stable.key",
        "payload_digest": "c" * 64,
        "profile_fingerprint": "d" * 64,
    }


@pytest.fixture
def store():
    with sqlite3.connect(":memory:", isolation_level=None) as connection:
        result = HandoffStore(connection)
        result.initialize()
        yield result


def assert_purged(store, record):
    assert record["payload"] is None
    assert "PRIVATE" not in json.dumps(record)
    row = store.connection.execute(
        "SELECT metadata,payload,observation FROM handoffs WHERE id=?", (record["id"],)
    ).fetchone()
    assert row[1] is None and "PRIVATE" not in str(row)


def test_prepare_replay_claim_and_sticky_observation(store):
    original = intent()
    first = store.prepare("request", original, 100)
    assert first["state"] == "prepared" and first["expires_at"] == 1000
    original["source"]["details"] = "changed outside"
    assert first["payload"]["source"]["details"] == "PRIVATE DETAILS"
    assert store.prepare("request", first["payload"], 101) == first
    claimed, winner = store.claim(first["id"], first["intent_digest"], 102)
    assert winner and claimed["state"] == "claimed" and claimed["payload"] == first["payload"]
    assert_purged(store, store.get(first["id"], 103))
    again, winner = store.claim(first["id"], first["intent_digest"], 104)
    assert not winner
    assert_purged(store, again)
    unknown = store.record_observation(first["id"], {"outcome": "missing"}, 105)
    assert unknown["state"] == "unknown"
    confirmed = store.record_observation(
        first["id"], {"outcome": "parked", "card_id": "card-1", "status": "blocked"}, 106
    )
    assert confirmed["state"] == "confirmed"
    changed = store.record_observation(first["id"], {"outcome": "archived"}, 107)
    assert changed["state"] == "confirmed" and changed["observation"]["outcome"] == "archived"
    assert_purged(store, changed)
    assert_purged(store, store.prepare("request", first["payload"], 108))


@pytest.mark.parametrize("terminal", ["cancel", "expire", "claim"])
def test_terminal_rows_never_rearm_and_only_unattempted_can_use_new_key(store, terminal):
    payload = intent()
    record = store.prepare("key", payload, 0)
    if terminal == "cancel":
        result = store.cancel(record["id"], record["intent_digest"], 1)
    elif terminal == "expire":
        result, won = store.claim(record["id"], record["intent_digest"], 900)
        assert not won and result["state"] == "expired"
    else:
        store.claim(record["id"], record["intent_digest"], 1)
        result = store.get(record["id"], 2)
    assert_purged(store, result)
    assert_purged(store, store.prepare("key", payload, 1000))
    if terminal == "claim":
        with pytest.raises(HandoffError, match="source_already_prepared"):
            store.prepare("new-key", {**payload, "key": "new.native.key"}, 1001)
    else:
        new = store.prepare("new-key", {**payload, "key": "new.native.key"}, 1001)
        assert new["id"] != record["id"] and new["state"] == "prepared"
        assert store.claim(record["id"], record["intent_digest"], 1002)[1] is False
        assert store.prepare("key", payload, 1003)["state"] == result["state"]
        assert store.claim(new["id"], new["intent_digest"], 1004)[1] is True


def test_digest_conflicts_and_failed_operations_rollback_cleanup(store):
    payload = intent()
    record = store.prepare("key", payload, 0)
    with pytest.raises(HandoffError, match="idempotency_conflict"):
        store.prepare("key", {**payload, "native_body": "different"}, 901)
    assert store.connection.execute("SELECT state FROM handoffs").fetchone()[0] == "prepared"
    for method in (store.claim, store.cancel):
        with pytest.raises(HandoffError, match="intent_conflict"):
            method(record["id"], "0" * 64, 901)
    assert store.get(record["id"], 901)["state"] == "expired"


def test_cancel_replay_and_no_cancel_after_claim(store):
    record = store.prepare("a", intent(), 0)
    cancelled = store.cancel(record["id"], record["intent_digest"], 1)
    assert store.cancel(record["id"], record["intent_digest"], 2) == cancelled
    assert_purged(store, cancelled)
    second = store.prepare("b", intent(), 3)
    store.claim(second["id"], second["intent_digest"], 4)
    with pytest.raises(HandoffError, match="terminal_state"):
        store.cancel(second["id"], second["intent_digest"], 5)


def test_capacity_preserves_terminal_rows_and_replay(store, monkeypatch):
    monkeypatch.setattr(module, "MAX_RECORDS", 2)
    first = store.prepare("one", intent(), 0)
    store.cancel(first["id"], first["intent_digest"], 1)
    second = store.prepare("two", intent(), 2)
    with pytest.raises(HandoffError, match="handoff_limit"):
        store.prepare("three", intent(), 1000)
    assert store.prepare("two", second["payload"], 1000)["state"] == "expired"
    assert store.connection.execute("SELECT count(*) FROM handoffs").fetchone()[0] == 2


def test_list_oldest_cursor_and_successful_lazy_expiry(store):
    records = [store.prepare(f"key-{i}", intent(), i) for i in range(3)]
    page = store.list(2, None, 900)
    assert [item["id"] for item in page["items"]] == [r["id"] for r in records[:2]]
    assert page["items"][0]["state"] == "expired"
    assert page["items"][1]["state"] == "prepared"
    assert page["has_more"] and page["next_cursor"] == records[1]["id"]
    last = store.list(2, page["next_cursor"], 902)
    assert last["items"][0]["state"] == "expired" and not last["has_more"]
    with pytest.raises(HandoffError, match="invalid_cursor"):
        store.list(1, str(uuid4()), 903)


def test_reopen_and_concurrent_claim_one_winner(tmp_path):
    path = tmp_path / "ledger.db"
    with sqlite3.connect(path, isolation_level=None) as connection:
        ledger = HandoffStore(connection)
        ledger.initialize()
        record = ledger.prepare("key", intent(), 0)
    barrier = Barrier(2)

    def claim():
        with sqlite3.connect(path, isolation_level=None) as connection:
            ledger = HandoffStore(connection)
            ledger.initialize()
            barrier.wait(timeout=5)
            return ledger.claim(record["id"], record["intent_digest"], 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert sum(winner for _, winner in results) == 1
    assert sum(result["payload"] is not None for result, _ in results) == 1
    with sqlite3.connect(path, isolation_level=None) as connection:
        ledger = HandoffStore(connection)
        ledger.initialize()
        assert_purged(ledger, ledger.get(record["id"], 2))
        assert ledger.claim(record["id"], record["intent_digest"], 3)[1] is False


def test_claim_write_failure_rolls_back_without_returning_payload(store):
    record = store.prepare("key", intent(), 0)
    store.connection.execute(
        "CREATE TEMP TRIGGER fail BEFORE UPDATE ON handoffs "
        "BEGIN SELECT RAISE(ABORT,'private error'); END"
    )
    with pytest.raises(HandoffError, match="storage_error") as error:
        store.claim(record["id"], record["intent_digest"], 1)
    assert "private error" not in str(error.value)
    assert store.get(record["id"], 1)["state"] == "prepared"
    store.connection.execute("DROP TRIGGER fail")
    assert store.claim(record["id"], record["intent_digest"], 2)[1]


@pytest.mark.parametrize(
    "change",
    [
        {"extra": "private"},
        {"native_body": "x" * 16001},
        {"payload_digest": []},
        {"profile_fingerprint": "bad"},
        {"destination": {"path": "wrong"}},
        {"key": "bad key"},
        {"native_title": "\x00bad"},
        {"source": {"task_id": str(uuid4()), "revision": True, "title": "a", "details": ""}},
    ],
)
def test_invalid_intents_do_not_write(store, change):
    with pytest.raises(HandoffError, match="invalid_request"):
        store.prepare("key", {**intent(), **change}, 0)
    assert not store.list(10, None, 0)["items"]


@pytest.mark.parametrize(
    "observation",
    [
        {"outcome": "parked"},
        {"outcome": "parked", "card_id": "a", "status": "running"},
        {"outcome": "missing", "body": "private"},
        {"outcome": []},
        {"outcome": "missing", "match_count": True},
        {"outcome": "parked", "card_id": "a", "status": "blocked", "match_count": 2},
    ],
)
def test_observation_strict_metadata(store, observation):
    record = store.prepare("key", intent(), 0)
    store.claim(record["id"], record["intent_digest"], 1)
    with pytest.raises(HandoffError, match="invalid_request"):
        store.record_observation(record["id"], observation, 2)
    assert store.get(record["id"], 3)["state"] == "claimed"


@pytest.mark.parametrize(
    "setup,code",
    [
        ("CREATE TABLE foreign_data(x)", "foreign_database"),
        (f"PRAGMA application_id={module.APPLICATION_ID}", "unsupported_schema"),
    ],
)
def test_foreign_or_inexact_schema_refused(setup, code):
    with sqlite3.connect(":memory:", isolation_level=None) as connection:
        connection.execute(setup)
        with pytest.raises(HandoffError, match=code):
            HandoffStore(connection).initialize()


def test_changed_schema_not_adopted(store):
    store.connection.execute("CREATE TABLE extra(x)")
    with pytest.raises(HandoffError, match="unsupported_schema"):
        store.initialize()
    with pytest.raises(HandoffError, match="not_initialized"):
        store.list(1, None, 0)


def test_nested_transaction_is_not_rolled_back(store):
    store.connection.execute("BEGIN")
    with pytest.raises(HandoffError, match="connection_in_transaction"):
        store.prepare("key", intent(), 0)
    assert store.connection.in_transaction
    store.connection.rollback()


def test_canonical_digest_ignores_mapping_order(store):
    payload = intent()
    record = store.prepare("key", payload, 0)
    reordered = dict(reversed(list(copy.deepcopy(payload).items())))
    assert store.prepare("key", reordered, 1) == record


def test_commit_failure_returns_no_claim_and_rolls_back():
    class FailingConnection(sqlite3.Connection):
        fail_commit = False

        def execute(self, sql, parameters=(), /):
            if self.fail_commit and sql == "COMMIT":
                raise sqlite3.OperationalError("synthetic private commit failure")
            return super().execute(sql, parameters)

    with sqlite3.connect(":memory:", isolation_level=None, factory=FailingConnection) as connection:
        store = HandoffStore(connection)
        store.initialize()
        record = store.prepare("key", intent(), 0)
        connection.fail_commit = True
        with pytest.raises(HandoffError, match="storage_error"):
            store.claim(record["id"], record["intent_digest"], 1)
        connection.fail_commit = False
        assert store.get(record["id"], 1)["state"] == "prepared"
        assert store.claim(record["id"], record["intent_digest"], 2)[1]


def test_uncommitted_claim_connection_loss_and_durable_claim_no_rearm(tmp_path):
    path = tmp_path / "crash.db"
    connection = sqlite3.connect(path, isolation_level=None)
    store = HandoffStore(connection)
    store.initialize()
    record = store.prepare("key", intent(), 0)
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("UPDATE handoffs SET state='claimed',payload=NULL")
    connection.close()  # SQLite rolls back an interrupted pre-commit transaction.
    with sqlite3.connect(path, isolation_level=None) as recovered:
        store = HandoffStore(recovered)
        store.initialize()
        assert store.get(record["id"], 1)["state"] == "prepared"
        assert store.claim(record["id"], record["intent_digest"], 2)[1]
    # Losing the process after claim commit must not authorize another attempt.
    with sqlite3.connect(path, isolation_level=None) as recovered:
        store = HandoffStore(recovered)
        store.initialize()
        record, winner = store.claim(record["id"], record["intent_digest"], 3)
        assert not winner
        assert_purged(store, record)


@pytest.mark.parametrize("change", ["payload", "source", "authority"])
def test_corrupt_prepared_data_cannot_change_claim_payload(store, change):
    record = store.prepare("key", intent(), 0)
    if change == "payload":
        payload = record["payload"]
        payload["native_body"] = "altered"
        store.connection.execute("UPDATE handoffs SET payload=?", (json.dumps(payload),))
    else:
        metadata = json.loads(
            store.connection.execute("SELECT metadata FROM handoffs").fetchone()[0]
        )
        if change == "source":
            metadata["source"]["revision"] = 2
        else:
            metadata["authorization"] = "forged"
        store.connection.execute("UPDATE handoffs SET metadata=?", (json.dumps(metadata),))
    with pytest.raises(HandoffError, match="storage_corrupt"):
        store.claim(record["id"], record["intent_digest"], 1)
    assert store.connection.execute("SELECT state FROM handoffs").fetchone()[0] == "prepared"


def test_process_exit_mid_claim_rolls_back_before_any_external_attempt(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "abrupt.db"
    with sqlite3.connect(path, isolation_level=None) as connection:
        ledger = HandoffStore(connection)
        ledger.initialize()
        record = ledger.prepare("key", intent(), 0)
    child = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sqlite3,os,sys; c=sqlite3.connect(sys.argv[1],isolation_level=None); "
            "c.execute('BEGIN IMMEDIATE'); "
            "c.execute(\"UPDATE handoffs SET state='claimed',payload=NULL\"); os._exit(17)",
            str(path),
        ],
        check=False,
        timeout=10,
    )
    assert child.returncode == 17
    with sqlite3.connect(path, isolation_level=None) as connection:
        ledger = HandoffStore(connection)
        ledger.initialize()
        assert ledger.get(record["id"], 1)["state"] == "prepared"
        assert ledger.claim(record["id"], record["intent_digest"], 2)[1]


def test_prepare_insert_failure_leaves_no_receipt_or_reserved_scope(store):
    payload = intent()
    store.connection.execute(
        "CREATE TEMP TRIGGER fail BEFORE INSERT ON handoffs "
        "BEGIN SELECT RAISE(ABORT,'synthetic'); END"
    )
    with pytest.raises(HandoffError, match="storage_error"):
        store.prepare("key", payload, 0)
    assert store.connection.execute("SELECT count(*) FROM handoffs").fetchone()[0] == 0
    store.connection.execute("DROP TRIGGER fail")
    assert store.prepare("key", payload, 1)["state"] == "prepared"


def test_prepared_listing_never_discloses_payload_but_single_preview_does(store):
    record = store.prepare("preview", intent(), 0)
    listed = store.list(100, None, 1)["items"][0]
    assert listed["state"] == "prepared" and listed["payload"] is None
    assert "PRIVATE" not in json.dumps(listed)
    assert store.get(record["id"], 2)["payload"] == record["payload"]


def anchor(**overrides):
    return {"card_id": "t_1234abcd", "created_at": 123, "created_event_id": 1, **overrides}


def test_anchor_is_immutable_and_observation_never_establishes_it(store):
    record = store.prepare("key", intent(), 0)
    with pytest.raises(HandoffError, match="terminal_state"):
        store.remember_native_identity(record["id"], anchor(), 1)
    store.claim(record["id"], record["intent_digest"], 2)
    available = store.remember_native_identity(record["id"], anchor(), 3)
    assert available["identity_state"] == "available" and available["native_identity"] == anchor()
    assert available["state"] == "claimed" and available["payload"] is None
    assert store.remember_native_identity(record["id"], anchor(), 4) == available
    for field, value in [("card_id", "t_aaaaaaaa"), ("created_at", 124), ("created_event_id", 2)]:
        with pytest.raises(HandoffError, match="native_identity_conflict"):
            store.remember_native_identity(record["id"], anchor(**{field: value}), 5)
    with pytest.raises(HandoffError, match="native_identity_conflict"):
        store.record_observation(
            record["id"], {"outcome": "parked", "card_id": "t_aaaaaaaa", "status": "blocked"}, 6
        )
    assert store.get(record["id"], 7)["state"] == "claimed"
    confirmed = store.record_observation(
        record["id"], {"outcome": "parked", "card_id": anchor()["card_id"], "status": "blocked"}, 8
    )
    assert store.remember_native_identity(record["id"], anchor(), 9) == confirmed
    other = store.prepare("other", intent(), 10)
    store.claim(other["id"], other["intent_digest"], 11)
    observed = store.record_observation(
        other["id"], {"outcome": "parked", "card_id": anchor()["card_id"], "status": "blocked"}, 12
    )
    assert observed["native_identity"] is None and observed["identity_state"] == "unbound"
    with pytest.raises(HandoffError, match="terminal_state"):
        store.remember_native_identity(other["id"], anchor(), 13)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"card_id": "t_1234abcd"},
        anchor(extra="authority"),
        anchor(card_id="t_1234ABCD"),
        anchor(card_id="t_1234abcde"),
        anchor(created_at=True),
        anchor(created_at=-1),
        anchor(created_at=1.0),
        anchor(created_event_id=False),
        anchor(created_event_id=0),
        anchor(created_event_id="1"),
    ],
)
def test_anchor_input_is_strict_and_cannot_inject_authority(store, value):
    record = store.prepare("key", intent(), 0)
    store.claim(record["id"], record["intent_digest"], 1)
    with pytest.raises(HandoffError, match="invalid_request"):
        store.remember_native_identity(record["id"], value, 2)
    assert store.get(record["id"], 3)["identity_state"] == "unbound"


def legacy_connection(factory=sqlite3.Connection):
    connection = sqlite3.connect(":memory:", isolation_level=None, factory=factory)
    connection.execute(module._SCHEMA_V1["handoffs"])
    connection.execute(f"PRAGMA application_id={module.APPLICATION_ID}")
    connection.execute("PRAGMA user_version=1")
    return connection


def seed_legacy(connection):
    with sqlite3.connect(":memory:", isolation_level=None) as fresh:
        source = HandoffStore(fresh)
        source.initialize()
        records = {}
        for state in ("prepared", "claimed", "unknown", "confirmed", "cancelled", "expired"):
            record = source.prepare(state, intent(), 0)
            if state in ("claimed", "unknown", "confirmed"):
                source.claim(record["id"], record["intent_digest"], 1)
                if state != "claimed":
                    observation = (
                        {"outcome": "missing"}
                        if state == "unknown"
                        else {"outcome": "parked", "card_id": "t_1234abcd", "status": "blocked"}
                    )
                    source.record_observation(record["id"], observation, 2)
            elif state == "cancelled":
                source.cancel(record["id"], record["intent_digest"], 1)
            elif state == "expired":
                # Do not expire the separate prepared migration case.
                fresh.execute(
                    "UPDATE handoffs SET state='expired',payload=NULL,scope_digest=NULL WHERE id=?",
                    (record["id"],),
                )
            records[state] = record
        rows = fresh.execute("SELECT * FROM handoffs ORDER BY sequence").fetchall()
        connection.executemany(
            "INSERT INTO handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [row[:12] for row in rows]
        )
        return records


def test_exact_v1_migration_preserves_all_prior_bytes_and_never_adopts_legacy():
    with legacy_connection() as connection:
        records = seed_legacy(connection)
        before = connection.execute("SELECT * FROM handoffs ORDER BY sequence").fetchall()
        store = HandoffStore(connection)
        store.initialize()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        after = connection.execute("SELECT * FROM handoffs ORDER BY sequence").fetchall()
        assert [row[:12] for row in after] == before
        store.initialize()  # Exact migrated schema is also an accepted fresh-load schema.
        for state, record in records.items():
            result = store.get(record["id"], 3)
            attempted = state in ("claimed", "unknown", "confirmed")
            assert result["identity_state"] == ("legacy_unbound" if attempted else "unbound")
            assert result["native_identity"] is None
            if attempted:
                with pytest.raises(HandoffError, match="native_identity_unavailable"):
                    store.remember_native_identity(record["id"], anchor(), 4)
                store.record_observation(
                    record["id"],
                    {"outcome": "parked", "card_id": anchor()["card_id"], "status": "blocked"},
                    5,
                )
                assert store.get(record["id"], 6)["identity_state"] == "legacy_unbound"
        prepared = records["prepared"]
        assert store.claim(prepared["id"], prepared["intent_digest"], 7)[1]
        assert (
            store.remember_native_identity(prepared["id"], anchor(), 8)["identity_state"]
            == "available"
        )


def test_partial_migration_failure_rolls_back_schema_and_rows():
    class Failure(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            if sql.startswith("UPDATE handoffs SET identity_state="):
                raise sqlite3.OperationalError("synthetic migration interruption")
            return super().execute(sql, parameters)

    with legacy_connection(Failure) as connection:
        seed_legacy(connection)
        before = connection.execute("SELECT * FROM handoffs").fetchall()
        with pytest.raises(HandoffError, match="storage_error"):
            HandoffStore(connection).initialize()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT * FROM handoffs").fetchall() == before
        assert (
            connection.execute("SELECT sql FROM sqlite_master WHERE name='handoffs'").fetchone()[0]
            == module._SCHEMA_V1["handoffs"]
        )


def test_nonexact_v1_schema_refused_without_migration():
    with legacy_connection() as connection:
        connection.execute("CREATE INDEX extra ON handoffs(state)")
        with pytest.raises(HandoffError, match="unsupported_schema"):
            HandoffStore(connection).initialize()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_anchor_failure_rolls_back_and_committed_anchor_survives_native_failure(tmp_path):
    path = tmp_path / "identity.db"
    with sqlite3.connect(path, isolation_level=None) as connection:
        store = HandoffStore(connection)
        store.initialize()
        record = store.prepare("key", intent(), 0)
        store.claim(record["id"], record["intent_digest"], 1)
        connection.execute(
            "CREATE TEMP TRIGGER fail BEFORE UPDATE ON handoffs "
            "BEGIN SELECT RAISE(ABORT,'synthetic anchor failure'); END"
        )
        with pytest.raises(HandoffError, match="storage_error"):
            store.remember_native_identity(record["id"], anchor(), 2)
        assert store.get(record["id"], 3)["native_identity"] is None
        connection.execute("DROP TRIGGER fail")
        store.remember_native_identity(record["id"], anchor(), 4)
    # This reopen represents a crash after anchor commit but before native commit.
    with sqlite3.connect(path, isolation_level=None) as connection:
        store = HandoffStore(connection)
        store.initialize()
        result = store.record_observation(record["id"], {"outcome": "missing"}, 5)
        assert result["state"] == "unknown" and result["native_identity"] == anchor()
        assert result["identity_state"] == "available"
        assert not store.claim(record["id"], record["intent_digest"], 6)[1]


@pytest.mark.parametrize(
    "status",
    ["triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"],
)
@pytest.mark.parametrize("state", ["claimed", "unknown"])
def test_identity_confirmation_proves_creation_after_advancement_not_execution(
    store, status, state
):
    record = store.prepare("key", intent(), 0)
    store.claim(record["id"], record["intent_digest"], 1)
    store.remember_native_identity(record["id"], anchor(), 2)
    if state == "unknown":
        store.record_observation(record["id"], {"outcome": "unavailable"}, 3)
    observation = {
        "outcome": "identity_confirmed",
        "card_id": anchor()["card_id"],
        "status": status,
    }
    result = store.record_observation(record["id"], observation, 4)
    assert result["state"] == "confirmed" and result["observation"] == observation
    assert result["native_identity"] == anchor() and result["payload"] is None
    assert not store.claim(record["id"], record["intent_digest"], 5)[1]
    changed = store.record_observation(record["id"], {"outcome": "changed"}, 6)
    assert changed["state"] == "confirmed" and changed["native_identity"] == anchor()


@pytest.mark.parametrize("kind", ["unbound", "legacy_unbound", "different_card"])
def test_identity_confirmation_cannot_invent_or_replace_anchor(store, kind):
    record = store.prepare("key", intent(), 0)
    store.claim(record["id"], record["intent_digest"], 1)
    if kind == "different_card":
        store.remember_native_identity(record["id"], anchor(), 2)
    elif kind == "legacy_unbound":
        store.connection.execute("UPDATE handoffs SET identity_state='legacy_unbound'")
    before = store.get(record["id"], 3)
    observation = {"outcome": "identity_confirmed", "card_id": "t_aaaaaaaa", "status": "done"}
    code = "native_identity_conflict" if kind == "different_card" else "native_identity_unavailable"
    with pytest.raises(HandoffError, match=code):
        store.record_observation(record["id"], observation, 4)
    assert store.get(record["id"], 5) == before


@pytest.mark.parametrize(
    "extra",
    [
        {"card_id": "other"},
        {"status": None},
        {"status": "complete"},
        {"match_count": 2},
        {"authority": "operator"},
    ],
)
def test_identity_confirmation_strict_metadata(store, extra):
    record = store.prepare("key", intent(), 0)
    store.claim(record["id"], record["intent_digest"], 1)
    store.remember_native_identity(record["id"], anchor(), 2)
    with pytest.raises(HandoffError, match="invalid_request"):
        store.record_observation(
            record["id"],
            {
                "outcome": "identity_confirmed",
                "card_id": anchor()["card_id"],
                "status": "running",
                **extra,
            },
            3,
        )
    assert store.get(record["id"], 4)["state"] == "claimed"
