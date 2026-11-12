"""Metadata-only origin commands through pinned native admission, synthetic only."""

import asyncio
import hashlib
import importlib
import json
import sqlite3
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_memory_candidates as candidates
import test_memory_process_restart as process
import test_observed_source_retention as sources
import test_session_memory_tools as model
from hermes_state import SessionDB
from test_local_task_cli import PLUGIN_ID

native = candidates.native
host = candidates.host


def module(host, name):
    prefix = host.manager._plugins[PLUGIN_ID].module.__name__ + ".personal_agent."
    return importlib.import_module(prefix + name)


def data(host, text):
    result = memory.command(host, text)
    assert result["status"] == "ok", result
    assert result["replayed"] is False
    return result["data"]


def human(host, text):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-memory " + text})
    )
    assert result["type"] == "exec"
    return result["output"]


def observed(host, role="user"):
    path, _ = sources.seed(host, ((role, "synthetic private original"),))
    args, preview = sources.selection(host)
    accepted = sources.retain(host, args, preview)
    return path, accepted["record"]["record_id"]


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_observed_origin_human_json_no_source_or_payload_reads(host, monkeypatch, role):
    path, rid = observed(host, role)
    # An unrelated pending draft must neither be hydrated nor expired by origin.
    candidates.pending(host)
    canonical = memory.database(host.home)
    before = canonical.read_bytes()
    config = (host.home / "config.yaml").read_bytes()
    path.unlink()
    storage = module(host, "memory_storage")
    acquire = storage.SQLiteMemoryFactory.acquire
    modes = []

    def forbidden(*args, **kwargs):
        pytest.fail("Origin must not open native source or use writable storage")

    def guarded(self, resources, binding, mode):
        assert mode == "readonly"
        modes.append(mode)
        backend = acquire(self, resources, binding, mode)
        assert backend._connection.execute("PRAGMA query_only").fetchone() == (1,)

        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ:
                assert column not in {"content", "topic", "quote", "session_ref"}
            assert action not in {
                sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_DELETE,
            }
            return sqlite3.SQLITE_OK

        backend._connection.set_authorizer(authorize)
        return backend

    monkeypatch.setattr(SessionDB, "__init__", forbidden)
    monkeypatch.setattr(module(host, "conversation_memory"), "open_memory_backend", forbidden)
    monkeypatch.setattr(storage.SQLiteMemoryFactory, "acquire", guarded)
    result = data(host, "origin " + rid)
    view = human(host, "origin " + rid)
    assert result["origin"]["kind"] == "observed_native_snapshot"
    assert result["origin"]["role"] == role
    assert result["current"]["revision"] == 1
    assert result["current_editing_route"] == "explicit_local_operator"
    assert 'Source role: "' + role + '"' in view
    assert "Original accepted origin:" in view
    assert "Historical acceptance (not current state):" in view
    assert "Source availability is not checked." in view
    assert "authorship, truth or authority" in view
    assert "Suppression does not mean" in view
    for secret in (
        "synthetic private original",
        "synthetic-topic",
        candidates.QUOTE,
        host.ref.session_id,
        str(host.home),
    ):
        assert secret not in json.dumps(result) + view
    assert modes == ["readonly", "readonly"]
    assert canonical.read_bytes() == before
    assert (host.home / "config.yaml").read_bytes() == config
    assert not path.exists()


def test_reviewed_candidate_origin_and_direct_unavailable(host):
    candidate = candidates.pending(host)
    cid = candidate["candidate_id"]
    accepted = data(host, f"candidate-accept {cid} --expected-revision 1 --keep")
    rid = accepted["record"]["record_id"]
    origin = data(host, "origin " + rid)["origin"]
    assert origin["kind"] == "reviewed_candidate" and origin["candidate_id"] == cid
    assert origin["acceptance"]["revision"] == 1
    assert "Candidate ID: " + cid in human(host, "origin " + rid)
    direct = data(host, 'remember "synthetic direct" --request-id direct')["record_id"]
    unavailable = data(host, "origin " + direct)["origin"]
    assert unavailable == {"kind": "unavailable", "reason": "no_durable_lineage"}
    assert 'Reason: "no_durable_lineage"' in human(host, "origin " + direct)


def test_retained_receipt_origin_native_command(host):
    # Retained receipts have no native creation command: trusted SDK staging is
    # synthetic setup only, followed by the actual registered operator command.
    storage = module(host, "memory_storage")
    backend_api = module(host, "memory_backend")
    payload = {
        "request_id": "retained-origin",
        "consumer_id": "retained",
        "expected_sequence": 0,
        "content": "synthetic receipt original",
        "topic": "private topic",
        "expires_at": None,
        "retention": "independent_snapshot",
        "source": {
            "identity": "a" * 64,
            "fingerprint": hashlib.sha256(b"synthetic receipt original").hexdigest(),
            "role": "assistant",
            "receipt_id": "b" * 64,
        },
    }
    with storage.open_memory_backend(host.home, host.ref.session_id) as backend:
        service = backend_api.MemoryService(backend)
        service.execute("source_stage", payload)
        rid = service.execute("source_accept", payload)["data"]["record"]["record_id"]
    origin = data(host, "origin " + rid)["origin"]
    assert origin["kind"] == "retained_native_snapshot"
    assert origin["role"] == "assistant" and origin["source_sequence"] == 1
    assert "retained_native_snapshot" in human(host, "origin " + rid)
    assert "b" * 64 not in human(host, "origin " + rid)


def test_correction_expiry_forget_restart_and_repack_preserve_historical_origin(host, monkeypatch):
    _, rid = observed(host)
    accepted = data(host, "origin " + rid)["origin"]["acceptance"]
    model.activate(host, "enable-write")
    with model.turn(host):
        changed = model.call(
            host,
            {
                "action": "correct",
                "record_id": rid,
                "content": "synthetic replacement",
                "expected_revision": 1,
                "request_id": "model-edit",
                "expires_at": "2000-01-01T00:00:00Z",
            },
            write=True,
        )
    assert changed["status"] == "ok", changed
    current = data(host, "origin " + rid)
    assert current["current"]["revision"] == 2 and current["current"]["expired"] is True
    assert current["current_editing_route"] == "activated_session_model"
    assert current["origin"]["acceptance"] == accepted
    assert current["origin"]["suppressed"] is True
    assert current["current"]["status"] == "active"
    data(host, f"forget {rid} --expected-revision 2 --request-id forgotten")
    forgotten = data(host, "origin " + rid)
    assert forgotten["current"]["status"] == "forgotten"
    assert forgotten["current_editing_route"] is None
    assert forgotten["origin"]["suppressed"] is True
    assert forgotten["origin"]["acceptance"] == accepted
    for name, finish in (("normal", "maintenance-commit"), ("interrupted", "maintenance-recover")):
        data(host, f"maintenance-prepare {name} --expected-watermark 3")
        memory.assert_error(memory.command(host, "origin " + rid), "memory_maintenance_pending")
        if name == "interrupted":
            maintenance = module(host, "memory_maintenance")
            rename = maintenance.os.rename

            def interrupted(source, destination, rename=rename):
                rename(source, destination)
                if destination == memory.database(host.home):
                    raise OSError("synthetic interruption after canonical cutover")

            with monkeypatch.context() as patch:
                patch.setattr(maintenance.os, "rename", interrupted)
                memory.assert_error(
                    memory.command(host, "maintenance-commit " + name),
                    "maintenance_outcome_unknown",
                )
            memory.assert_error(memory.command(host, "origin " + rid), "memory_maintenance_pending")
        result = process.restart(
            host.home, [{"command": f"{finish} {name}"}, {"command": "origin " + rid}]
        )
        assert result[0]["status"] == "ok", result
        assert result[1]["status"] == "ok", result
        assert result[1]["data"]["origin"] == forgotten["origin"]
        assert result[1]["data"]["current"] == forgotten["current"]


def test_missing_old_store_and_invalid_args_never_create_or_migrate(host):
    rid = "00000000-0000-4000-8000-000000000001"
    memory.assert_error(memory.command(host, "origin " + rid), "memory_store_missing")
    assert not (host.home / "plugin-data").exists()
    for text in ("origin", "origin bad", "origin " + rid + " --limit 2"):
        memory.assert_error(memory.command(host, text), "invalid_request")
    saved = data(host, 'remember "synthetic" --request-id old')["record_id"]
    path = memory.database(host.home)
    with sqlite3.connect(path) as connection:
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        connection.execute(f"PRAGMA user_version={current - 1}")
    before = path.read_bytes()
    memory.assert_error(memory.command(host, "origin " + saved), "readonly_schema_unavailable")
    assert path.read_bytes() == before


def test_disabled_foreign_remote_and_model_origin_denied(host):
    rid = "00000000-0000-4000-8000-000000000001"
    memory.configure(host.home, local_memory=False)
    memory.assert_error(memory.command(host, "origin " + rid), "local_memory_disabled")
    remote = json.loads(
        memory.handler(host)(
            "--json origin " + rid, platform="telegram", session_id="remote", session_key="remote"
        )
    )
    memory.assert_error(remote, "unsupported_origin")
    memory.configure(host.home, local_memory=True, memory_model_tools=True, memory_candidates=True)
    model.activate(host, "enable-write")
    with model.turn(host):
        for action in ("origin", "record_origin"):
            for write in (True, False):
                assert (
                    model.call(host, {"action": action, "record_id": rid}, write=write)["status"]
                    == "error"
                )
    host.connection.actor = replace(host.connection.actor, subject="foreign")
    from hermes_state_runtime import RuntimeStoreError

    with pytest.raises(RuntimeStoreError):
        memory.command(host, "origin " + rid)
    assert not memory.database(host.home).exists()
