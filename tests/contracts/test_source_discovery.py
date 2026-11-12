"""Pinned native LOCAL discovery after synthetic source loss and restart."""

import asyncio
import json
import sys
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_observed_source_retention as retention
from hermes_state import SessionDB

native = memory.native
host = memory.host


def test_discover_terminal_after_native_loss_and_plugin_reload(host, monkeypatch):
    path, _ = retention.seed(host, (("user", "synthetic private discovery source"),))
    args, preview = retention.selection(host)
    accepted = retention.retain(host, args, preview)
    rid = accepted["record"]["record_id"]
    retention.data(host, f"forget {rid} --expected-revision 1")
    path.unlink()
    host.manager.discover_and_load(force=True)
    canonical = memory.database(host.home)
    before = retention.snapshot(canonical)
    monkeypatch.setattr(SessionDB, "__init__", lambda *a, **k: pytest.fail("native source opened"))
    result = retention.data(host, "source-discover --state all")
    assert result["total"] == 1
    item = result["items"][0]
    assert item["query"] == preview["query"]
    assert item["state"] == "accepted"
    assert item["record"] == accepted["record"]
    assert item["current"]["status"] == "forgotten"
    assert item["suppressed"] is True
    encoded = json.dumps(result)
    for forbidden in (
        "synthetic private discovery source",
        "synthetic-topic",
        host.ref.session_id,
        "observation_id",
        "fingerprint",
    ):
        assert forbidden not in encoded
    assert retention.data(host, "source-discover")["items"] == []
    assert retention.snapshot(canonical) == before
    assert not path.exists()


def test_pending_discovery_recovers_exact_identity_for_deliberate_discard(host, monkeypatch):
    path, _ = retention.seed(host)
    args, preview = retention.selection(host)
    modules = [
        m
        for name, m in list(sys.modules.items())
        if name.endswith(".local_memory") and hasattr(m, "LocalMemoryBackend")
    ]
    assert modules
    with monkeypatch.context() as patch:
        for module in modules:
            backend = module.LocalMemoryBackend
            original = backend.execute

            def interrupt(self, operation, payload, original=original):
                if operation == "source_accept":
                    raise RuntimeError("synthetic post-stage interruption")
                return original(self, operation, payload)

            patch.setattr(backend, "execute", interrupt)
        result = memory.command(
            host,
            "source-retain " + args + " --expected-digest " + preview["query"]["expected_digest"],
        )
        assert result["status"] == "error"
    path.unlink()
    host.manager.discover_and_load(force=True)
    pending = retention.data(host, "source-discover")["items"]
    assert len(pending) == 1 and pending[0]["state"] == "pending"
    assert pending[0]["record"] is None and pending[0]["current"] is None
    query = pending[0]["query"]
    assert query == preview["query"]
    args = "--expected-digest=" + query["expected_digest"] + " -- " + query["request_id"]
    assert retention.data(host, "source-status " + args)["decision"]["state"] == "pending"
    assert retention.data(host, "source-discard " + args)["state"] == "discarded"
    assert retention.data(host, "source-discover")["items"] == []
    assert retention.data(host, "source-discover --state discarded")["items"][0]["suppressed"]
    assert not path.exists()


def test_discovery_missing_store_no_creation(host):
    memory.assert_error(memory.command(host, "source-discover"), "memory_store_missing")
    assert not (host.home / "plugin-data").exists()


def test_discovery_disabled_and_foreign_profile_are_denied(host):
    from hermes_state_runtime import RuntimeStoreError

    callback = memory.handler(host)
    memory.configure(host.home, local_memory=False)
    memory.assert_error(
        memory.retained_command(host, callback, "source-discover"), "local_memory_disabled"
    )
    memory.configure(host.home)
    host.connection.actor = replace(host.connection.actor, profile_id=str(host.home / "foreign"))
    with pytest.raises(RuntimeStoreError) as caught:
        memory.command(host, "source-discover")
    assert caught.value.reason == "profile_mismatch"
    assert not (host.home / "plugin-data").exists()


@pytest.mark.parametrize("platform", ["telegram", "discord", "api_server"])
def test_remote_and_model_producer_cannot_discover(host, platform):
    from gateway.config import Platform
    from gateway.platforms.base import MessageEvent

    source = replace(host.source, platform=Platform(platform))
    event = MessageEvent(text="/personal-memory --json source-discover", source=source)
    entry = host.runner.session_store.lookup_by_session_key(host.live.route)
    result = asyncio.run(
        host.runner._hm_run_plugin_handler(memory.handler(host), event, source, entry)
    )
    memory.assert_error(json.loads(result), "unsupported_origin")
    event = MessageEvent(
        text="/personal-memory source-discover", source=host.source, allow_gateway_control=False
    )
    assert not event.is_command() and event.get_command() is None
    assert not (host.home / "plugin-data").exists()
