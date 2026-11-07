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
    binding = dict(
        root="/synthetic",
        board="scratch",
        path="/synthetic/cards.db",
        device=1,
        inode=2,
        schema="a" * 64,
        source="b" * 64,
    )
    outcome = [{"outcome": "parked", "card_id": "card-1", "status": "blocked"}]
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
            yield store

    def destination(board):
        calls.append("destination")
        return {**binding, "board": board}

    def create(binding, *, admit, **kwargs):
        admit()
        calls.append(("create", kwargs))
        if isinstance(outcome[0], Exception):
            raise outcome[0]
        return outcome[0]

    def observe(binding, *, admit, **kwargs):
        admit()
        calls.append("observe")
        return outcome[0]

    adapter = SimpleNamespace(
        destination=destination,
        payload_digest=lambda *args: "c" * 64,
        create_parked=create,
        observe=observe,
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
