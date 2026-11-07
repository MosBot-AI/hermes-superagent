"""Explicit local service workflow against real stores and a non-dispatching fake adapter."""

import json
import sqlite3
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from personal_agent import kanban_handoff as service
from personal_agent.kanban_handoff_store import HandoffStore
from personal_agent.tasks import TaskStore


@pytest.fixture
def flow(monkeypatch, tmp_path):
    config = dict(
        mode="local_tasks",
        local_conversation=True,
        kanban_handoff=True,
        kanban_handoff_board="scratch",
    )
    clock = [100]
    calls = []
    ledger_active = [0]
    binding = dict(
        root="/synthetic",
        board="scratch",
        path="/synthetic/cards.db",
        device=1,
        inode=2,
        schema="a" * 64,
        source="b" * 64,
    )
    outcome = [{"outcome": "parked", "card_id": "t_1234abcd", "status": "blocked"}]
    monkeypatch.setattr(service, "current_profile_home", lambda: tmp_path)
    monkeypatch.setattr(service, "_bound_key", lambda: "route")
    monkeypatch.setattr(service, "_runtime", lambda: None)
    monkeypatch.setattr(service.time, "time", lambda: clock[0])

    @contextmanager
    def tasks(home):
        assert home == tmp_path
        with sqlite3.connect(home / "tasks.db", timeout=0.05, isolation_level=None) as conn:
            store = TaskStore(conn)
            store.initialize()
            yield store

    @contextmanager
    def ledger(home):
        assert home == tmp_path
        with sqlite3.connect(home / "ledger.db", isolation_level=None) as conn:
            store = HandoffStore(conn)
            store.initialize()
            ledger_active[0] += 1
            try:
                yield store
            finally:
                ledger_active[0] -= 1

    def destination(board):
        calls.append("destination")
        return {**binding, "board": board}

    def create(binding, *, admit, remember_identity=None, **kwargs):
        admit()
        if remember_identity is not None:
            remember_identity({"card_id": "t_1234abcd", "created_at": 100, "created_event_id": 1})
            with ledger(tmp_path) as persisted:
                anchor_record = persisted.list(100, None, clock[0])["items"][-1]
                assert anchor_record["state"] == "claimed"
                assert anchor_record["identity_state"] == "available"
        calls.append(("create", kwargs))
        if isinstance(outcome[0], Exception):
            raise outcome[0]
        return outcome[0]

    def observe(binding, *, admit, **kwargs):
        admit()
        calls.append("observe")
        return outcome[0]

    progress = [
        {"outcome": "current", "card_id": "t_1234abcd", "status": "running", "observed_at": 110}
    ]

    def observe_progress(binding, *, admit, identity, **kwargs):
        assert ledger_active[0] == 0, "Ledger must close before native progress read"
        admit()
        calls.append("progress")
        assert identity == {"card_id": "t_1234abcd", "created_at": 100, "created_event_id": 1}
        if isinstance(progress[0], Exception):
            raise progress[0]
        return dict(progress[0])

    adapter = SimpleNamespace(
        destination=destination,
        payload_digest=lambda *args: "c" * 64,
        create_parked=create,
        observe=observe,
        observe_progress=observe_progress,
    )
    monkeypatch.setitem(sys.modules, "personal_agent.native_kanban", adapter)
    import personal_agent

    monkeypatch.setattr(personal_agent, "native_kanban", adapter, raising=False)
    monkeypatch.setattr(service, "open_task_store", tasks)
    monkeypatch.setattr(service, "open_handoff_store", ledger)
    instance = service.LocalKanbanHandoff(bound_home=tmp_path, read_config=config.get)
    source = SimpleNamespace(
        platform="local",
        chat_type="dm",
        is_bot=False,
        delivered_via_upstream_relay=False,
        profile_route_rejected=False,
        chat_id="chat",
        user_id="operator",
    )
    context = dict(platform="local", source=source, session_id="session", session_key="route")

    def invoke(command, **overrides):
        return json.loads(instance.command(command, **{**context, **overrides}))

    with tasks(tmp_path) as store:
        task = store.run(
            "capture",
            dict(
                title="Synthetic title",
                details="Synthetic details",
                project="PRIVATE PROJECT",
                request_id="capture",
            ),
        )["data"]
    return SimpleNamespace(**locals())


def prepare(flow):
    reply = flow.invoke(f"prepare {flow.task['id']} --expected-revision 1 --request-id key")
    assert reply["status"] == "ok", reply
    return reply["data"]


def commit(flow, record):
    return flow.invoke(f"commit {record['id']} --expected-digest {record['intent_digest']}")


def test_preview_then_one_attempt_and_reconcile_never_resubmits(flow):
    record = prepare(flow)
    assert "PRIVATE PROJECT" not in json.dumps(record)
    assert record["payload"]["source"]["details"] == "Synthetic details"
    assert record["payload"]["native_title"] == "Synthetic title"
    assert "UNTRUSTED" in record["payload"]["native_body"]
    result = commit(flow, record)
    assert result["data"]["state"] == "confirmed" and result["data"]["payload"] is None
    assert commit(flow, record)["data"]["state"] == "confirmed"
    flow.outcome[0] = {"outcome": "missing"}
    assert flow.invoke(f"reconcile {record['id']}")["data"]["state"] == "confirmed"
    assert commit(flow, record)["data"]["state"] == "confirmed"
    assert sum(isinstance(call, tuple) for call in flow.calls) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ("source", "source_changed"),
        ("digest", "intent_conflict"),
        ("board", "destination_changed"),
        ("binding", "destination_changed"),
        ("disable", "handoff_disabled"),
        ("unload", "handoff_unloaded"),
    ],
)
def test_changes_refuse_before_attempt(flow, change, code):
    record = prepare(flow)
    if change == "source":
        with flow.tasks(flow.tmp_path) as tasks:
            tasks.run(
                "update",
                dict(
                    task_id=flow.task["id"], expected_revision=1, request_id="edit", title="changed"
                ),
            )
    elif change == "digest":
        record["intent_digest"] = "0" * 64
    elif change == "board":
        flow.config["kanban_handoff_board"] = "other"
    elif change == "binding":
        flow.binding["inode"] = 3
    elif change == "disable":
        flow.config["kanban_handoff"] = False
    else:
        flow.instance.close()
    assert commit(flow, record)["error"]["code"] == code
    assert not any(isinstance(call, tuple) for call in flow.calls)


def test_expiry_cancel_and_disabled_metadata_access(flow):
    record = prepare(flow)
    flow.config["kanban_handoff"] = False
    assert flow.invoke(f"show {record['id']}")["status"] == "ok"
    assert (
        flow.invoke(f"cancel {record['id']} --expected-digest {record['intent_digest']}")["data"][
            "state"
        ]
        == "cancelled"
    )
    flow.config["kanban_handoff"] = True
    assert commit(flow, record)["data"]["state"] == "cancelled"
    assert not any(isinstance(call, tuple) for call in flow.calls)


def test_claim_expiry_is_committed_without_create(flow):
    record = prepare(flow)
    flow.clock[0] = 1000
    assert commit(flow, record)["data"]["state"] == "expired"
    assert flow.invoke(f"show {record['id']}")["data"]["payload"] is None
    assert not any(isinstance(call, tuple) for call in flow.calls)


def test_ambiguous_creation_is_durable_and_never_retried(flow):
    record = prepare(flow)
    flow.outcome[0] = RuntimeError("PRIVATE EXCEPTION")
    result = commit(flow, record)
    assert "PRIVATE EXCEPTION" not in json.dumps(result)
    assert result["data"]["state"] == "unknown"
    flow.outcome[0] = {"outcome": "missing"}
    assert flow.invoke(f"reconcile {record['id']}")["data"]["state"] == "unknown"
    assert commit(flow, record)["data"]["state"] == "unknown"
    assert sum(isinstance(call, tuple) for call in flow.calls) == 1


def test_receipt_failure_after_attempt_leaves_claimed_no_resubmit(flow, monkeypatch):
    record = prepare(flow)
    original = HandoffStore.record_observation

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE RECEIPT FAILURE")

    monkeypatch.setattr(HandoffStore, "record_observation", fail)
    assert commit(flow, record)["error"]["code"] == "handoff_unavailable"
    monkeypatch.setattr(HandoffStore, "record_observation", original)
    assert commit(flow, record)["data"]["state"] == "claimed"
    assert flow.invoke(f"reconcile {record['id']}")["data"]["state"] == "confirmed"
    assert sum(isinstance(call, tuple) for call in flow.calls) == 1


@pytest.mark.parametrize(
    "context",
    [{"platform": "cli"}, {"platform": "telegram"}, {"session_key": "wrong"}, {"source": None}],
)
def test_origin_refusal_before_storage_or_native_probe(flow, context):
    assert flow.invoke("list", **context)["error"]["code"] == "unsupported_origin"
    assert not (flow.tmp_path / "ledger.db").exists() and not flow.calls


def test_default_off_help_metadata_and_malformed_do_not_probe_native(flow):
    flow.config.pop("kanban_handoff")
    assert flow.invoke("help")["status"] == "ok"
    assert flow.invoke("list")["status"] == "ok"
    assert (
        flow.invoke("prepare x --expected-revision 1 --request-id key")["error"]["code"]
        == "handoff_disabled"
    )
    assert flow.invoke("commit x")["error"]["code"] == "invalid_request"
    assert not flow.calls


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "x" * 2049,
        "prepare \x00",
        "commit a --expected-dig x",
        "prepare a --expected-revision 1",
        "show a extra",
        "'bad",
    ],
)
def test_parser_rejects_invalid_or_abbreviated_commands(raw):
    with pytest.raises(service.HandoffError, match="invalid_request"):
        service.parse_command(raw)


def test_source_snapshot_blocks_concurrent_writer_commit_through_native_attempt(flow):
    record = prepare(flow)
    original = flow.adapter.create_parked

    def create(*args, **kwargs):
        with sqlite3.connect(
            flow.tmp_path / "tasks.db", timeout=0.01, isolation_level=None
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE tasks SET title='racing change'")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                conn.execute("COMMIT")
            conn.rollback()
        return original(*args, **kwargs)

    flow.adapter.create_parked = create
    assert commit(flow, record)["data"]["state"] == "confirmed"


def test_source_private_file_check_cannot_drop_snapshot_lock(flow):
    import subprocess

    from personal_agent.task_cli import _private_database_file

    path = flow.tmp_path / "tasks.db"
    path.chmod(0o600)
    with flow.tasks(flow.tmp_path) as tasks:
        with tasks.snapshot_task(flow.task["id"]):
            # A concurrent ordinary opener's preflight runs in this process.
            _private_database_file(path)
            child = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import sqlite3,sys; c=sqlite3.connect(sys.argv[1],timeout=.01); "
                    "c.execute(\"UPDATE tasks SET title='changed during handoff'\"); c.commit()",
                    str(path),
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
            assert child.returncode != 0, "Source opener dropped the live snapshot lock"
            assert b"locked" in child.stderr


def test_config_revocation_after_claim_prevents_adapter_write_and_never_rearms(flow):
    record = prepare(flow)
    original = flow.adapter.create_parked

    def revoked(*args, **kwargs):
        flow.config["kanban_handoff"] = False
        return original(*args, **kwargs)

    flow.adapter.create_parked = revoked
    result = commit(flow, record)
    assert result["data"]["state"] == "unknown"
    assert not any(isinstance(call, tuple) for call in flow.calls)
    flow.config["kanban_handoff"] = True
    flow.adapter.create_parked = original
    assert commit(flow, record)["data"]["state"] == "unknown"
    assert not any(isinstance(call, tuple) for call in flow.calls)


def test_no_adapter_import_for_disabled_or_metadata_only_commands(flow, monkeypatch):
    import builtins

    original = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if "native_kanban" in name or "native_kanban" in (fromlist or ()):
            pytest.fail("adapter imported without explicit enabled native operation")
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    flow.config["kanban_handoff"] = False
    assert flow.invoke("help")["status"] == "ok"
    assert flow.invoke("list")["status"] == "ok"
    assert (
        flow.invoke("prepare x --expected-revision 1 --request-id key")["error"]["code"]
        == "handoff_disabled"
    )


def test_restarted_service_cannot_recreate_claimed_handoff(flow):
    record = prepare(flow)
    assert commit(flow, record)["data"]["state"] == "confirmed"
    fresh = service.LocalKanbanHandoff(bound_home=flow.tmp_path, read_config=flow.config.get)
    reply = json.loads(
        fresh.command(
            f"commit {record['id']} --expected-digest {record['intent_digest']}", **flow.context
        )
    )
    assert reply["data"]["state"] == "confirmed" and reply["data"]["payload"] is None
    assert sum(isinstance(call, tuple) for call in flow.calls) == 1


@pytest.mark.parametrize("character", ["中", "😀"])
def test_full_length_unicode_task_preview_and_commit(flow, character):
    with flow.tasks(flow.tmp_path) as tasks:
        tasks.run(
            "update",
            dict(
                task_id=flow.task["id"],
                expected_revision=1,
                request_id="unicode",
                title=character * 240,
                details=character * 5000,
            ),
        )
    result = flow.invoke(
        f"prepare {flow.task['id']} --expected-revision 2 --request-id unicode-handoff"
    )
    assert result["status"] == "ok", result
    record = result["data"]
    assert record["payload"]["source"]["details"] == character * 5000
    assert record["payload"]["native_body"].endswith(character * 5000)
    assert flow.invoke("list")["data"]["items"][0]["payload"] is None
    assert flow.invoke(f"show {record['id']}")["data"]["payload"] == record["payload"]
    assert commit(flow, record)["data"]["state"] == "confirmed"


def sync(flow, record, *, revision=1, key="sync-1", task_id=None):
    return flow.invoke(
        f"sync {record['id']} --task {task_id or flow.task['id']} "
        f"--expected-revision {revision} --request-id {key}"
    )


def confirmed(flow):
    record = prepare(flow)
    result = commit(flow, record)
    assert result["data"]["state"] == "confirmed", result
    assert result["data"]["identity_state"] == "available"
    return record


def test_sync_records_advisory_only_with_identity_saved_before_creation_confirmation(flow):
    record = confirmed(flow)
    result = sync(flow, record)
    assert result["status"] == "ok", result
    task = result["data"]
    assert result["replayed"] is False
    assert task["revision"] == 2 and task["state"] == "captured" and task["work_status"] == "ready"
    assert task["native_progress"] == {
        **flow.progress[0],
        "handoff_id": record["id"],
        "exported_revision": 1,
    }
    flow.progress[0]["status"] = "done"
    refreshed = sync(flow, record, revision=2, key="sync-2")
    assert refreshed["data"]["native_progress"]["status"] == "done"
    assert refreshed["data"]["state"] == "captured"
    assert refreshed["data"]["work_status"] == "ready"
    assert sum(isinstance(call, tuple) for call in flow.calls) == 1


@pytest.mark.parametrize("mode", ["disabled", "missing", "terminal", "invalid-config"])
def test_sync_exact_replay_precedes_ledger_native_and_creation_config(flow, monkeypatch, mode):
    record = confirmed(flow)
    first = sync(flow, record)
    assert first["status"] == "ok", first
    if mode == "disabled":
        flow.config["kanban_handoff"] = False
    elif mode == "invalid-config":
        flow.config["kanban_handoff"] = "invalid"
        flow.config["kanban_handoff_board"] = []
    elif mode == "missing":
        (flow.tmp_path / "ledger.db").unlink()
    else:
        with flow.tasks(flow.tmp_path) as tasks:
            tasks.run(
                "complete",
                dict(
                    task_id=flow.task["id"],
                    expected_revision=2,
                    request_id="done",
                    note="local decision",
                ),
            )

    def forbidden(*args, **kwargs):
        pytest.fail("Exact replay must not access ledger/native")

    monkeypatch.setattr(service, "open_handoff_store", forbidden)
    flow.adapter.observe_progress = forbidden
    replay = sync(flow, record)
    assert replay["replayed"] is True and replay["data"] == first["data"]


@pytest.mark.parametrize(
    "mode,code",
    [
        ("prepared", "handoff_not_confirmed"),
        ("legacy", "native_identity_unavailable"),
        ("source", "source_mismatch"),
    ],
)
def test_sync_refuses_unconfirmed_legacy_or_different_source(flow, mode, code):
    record = prepare(flow)
    other = None
    if mode != "prepared":
        assert commit(flow, record)["data"]["state"] == "confirmed"
    if mode == "legacy":
        with flow.ledger(flow.tmp_path) as ledger:
            ledger.connection.execute(
                "UPDATE handoffs SET native_identity=NULL,identity_state='legacy_unbound'"
            )
    if mode == "source":
        with flow.tasks(flow.tmp_path) as tasks:
            other = tasks.run("capture", dict(title="Other", request_id="other"))["data"]["id"]
    assert sync(flow, record, task_id=other)["error"]["code"] == code
    assert "progress" not in flow.calls


def test_sync_key_collision_and_stale_revision_refused_before_native_callback(flow):
    record = confirmed(flow)
    assert sync(flow, record, key="capture")["error"]["code"] == "idempotency_conflict"
    assert sync(flow, record, revision=2)["error"]["code"] == "revision_conflict"
    assert "progress" not in flow.calls


def test_ambiguous_native_response_preserves_anchor_then_reconcile_allows_sync(flow):
    record = prepare(flow)
    flow.outcome[0] = RuntimeError("Synthetic response lost after native commit")
    result = commit(flow, record)
    assert result["data"]["state"] == "unknown"
    assert result["data"]["identity_state"] == "available"
    assert sync(flow, record)["error"]["code"] == "handoff_not_confirmed"
    flow.outcome[0] = {"outcome": "parked", "card_id": "t_1234abcd", "status": "blocked"}
    assert flow.invoke(f"reconcile {record['id']}")["data"]["state"] == "confirmed"
    assert sync(flow, record)["status"] == "ok"
    assert sum(isinstance(call, tuple) for call in flow.calls) == 1


def test_native_read_failure_preserves_prior_snapshot_and_local_revision(flow):
    record = confirmed(flow)
    before = sync(flow, record)["data"]
    flow.progress[0] = RuntimeError("PRIVATE native error")
    failed = sync(flow, record, revision=2, key="refresh")
    assert failed["status"] == "error" and "PRIVATE" not in json.dumps(failed)
    with flow.tasks(flow.tmp_path) as tasks:
        assert tasks.run("get", {"task_id": flow.task["id"]})["data"] == before


@pytest.mark.parametrize(
    "outcome", ["missing", "duplicate", "identity_changed", "key_changed", "identity_unavailable"]
)
def test_negative_projection_is_advisory_and_never_copies_status(flow, outcome):
    record = confirmed(flow)
    flow.progress[0] = {
        "outcome": outcome,
        "status": None,
        "card_id": "t_1234abcd",
        "observed_at": 110,
    }
    result = sync(flow, record)
    assert result["status"] == "ok", result
    assert result["data"]["native_progress"]["status"] is None
    assert result["data"]["native_progress"]["outcome"] == outcome
    assert result["data"]["work_status"] == "ready" and result["data"]["state"] == "captured"


@pytest.mark.parametrize(
    "raw",
    [
        "sync handoff --expected-revision 1 --request-id key",
        "sync handoff --task task --request-id key",
        "sync handoff --task task --expected-revision 1",
    ],
)
def test_sync_parser_requires_task_revision_and_key(raw):
    with pytest.raises(service.HandoffError, match="invalid_request"):
        service.parse_command(raw)


@pytest.mark.parametrize(
    "outcome", ["identity_changed", "key_changed", "identity_unavailable", "missing", "duplicate"]
)
def test_anchored_reconcile_normalizes_progress_failure_without_losing_sync_detail(flow, outcome):
    record = confirmed(flow)
    identity = flow.invoke(f"show {record['id']}")["data"]["native_identity"]
    failure = {"outcome": outcome, "card_id": "t_1234abcd", "status": None, "observed_at": 110}
    flow.outcome[0] = dict(failure)
    result = flow.invoke(f"reconcile {record['id']}")
    assert result["status"] == "ok", result
    persisted = flow.invoke(f"show {record['id']}")["data"]
    assert persisted["state"] == "confirmed"
    assert persisted["native_identity"] == identity
    expected = (
        "changed"
        if outcome in ("identity_changed", "key_changed", "identity_unavailable")
        else outcome
    )
    assert persisted["observation"]["outcome"] == expected
    assert "status" not in persisted["observation"]
    flow.progress[0] = failure
    synced = sync(flow, record)
    assert synced["status"] == "ok", synced
    assert synced["data"]["native_progress"]["outcome"] == outcome
    assert synced["data"]["native_progress"]["status"] is None
    assert sum(isinstance(call, tuple) for call in flow.calls) == 1
