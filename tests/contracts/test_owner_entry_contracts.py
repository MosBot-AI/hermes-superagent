"""Pinned native host seams; diagnostics never authenticate an owner.

Uses real source, wire codec, invoker, command resolver and dispatch sink. Does
not claim full gateway/agent integration or use live adapters or credentials.
"""

import asyncio
import dataclasses
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_local_task_cli import PLUGIN_ID, PLUGIN_ROOT, configure, invoke
from test_local_task_cli import native as native


def source(**changes):
    from gateway.config import Platform
    from gateway.session import SessionSource

    fields = dict(
        platform=Platform.TELEGRAM,
        user_id="137246801",
        chat_id="137246801",
        profile="synthetic-private-profile",
        user_name="Synthetic Private Name",
    )
    fields.update(changes)
    return SessionSource(**fields)


def diagnostic(src=None, **context):
    from personal_agent.identity import build_access_diagnostic

    return build_access_diagnostic(
        source=src, platform=context.pop("platform", "telegram"), **context
    )


def assert_denied(result, reason=None):
    assert result["status"] == "blocked"
    assert result["decision"] == "deny"
    assert result["protected_reads_enabled"] is False
    assert result["primary_binding_enabled"] is False
    assert result["scope"] == "diagnostic_only_no_authentication_or_grant"
    if reason:
        assert result["reason"] == reason
    for value in (
        "137246801",
        "Synthetic Private Name",
        "synthetic-private-profile",
        "synthetic-private-session",
        "synthetic-private-key",
        "secret-in-args",
    ):
        assert value not in json.dumps(result)


def test_exact_host_pin():
    import hermes_cli.plugins

    root = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    actual = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert actual == json.loads((PLUGIN_ROOT / "compatibility.json").read_text())["hermes_commit"]


def test_distinct_receiving_adapters_with_identical_public_projection_both_deny():
    first, second = source(), source()
    first._transport_adapter_ref, second._transport_adapter_ref = object(), object()
    assert first._transport_adapter_ref is not second._transport_adapter_ref
    assert dataclasses.asdict(first) == dataclasses.asdict(second)
    assert first.to_dict() == second.to_dict()
    assert diagnostic(first) == diagnostic(second)
    for src in (first, second):
        assert diagnostic(src)["actor_observation"]["candidate_recognized"] is True
        assert_denied(diagnostic(src), "receiving_transport_unverified")


def test_host_wire_preserves_public_fields_but_loses_dynamic_adapter():
    from hermes_cli.plugin_host_wire import Record, decode, encode

    src = source()
    src._transport_adapter_ref = object()
    restored = decode(json.loads(json.dumps(encode(src))))
    assert isinstance(restored, Record)
    for field in ("user_id", "chat_id", "profile"):
        assert getattr(restored, field) == getattr(src, field)
    assert restored.platform == src.platform.value
    assert not hasattr(restored, "_transport_adapter_ref")
    assert diagnostic(restored) == diagnostic(src)
    assert_denied(diagnostic(restored), "receiving_transport_unverified")
    relayed = decode(encode(source(delivered_via_upstream_relay=True)))
    assert relayed.delivered_via_upstream_relay is True
    assert_denied(diagnostic(relayed), "relay_source_unsupported")


@pytest.mark.parametrize(
    "changes",
    [
        {"is_bot": True},
        {"chat_type": "group"},
        {"chat_type": "channel"},
        {"thread_id": "synthetic-thread"},
        {"parent_chat_id": "synthetic-parent"},
        {"scope_id": "synthetic-scope"},
        {"delivered_via_upstream_relay": True},
        {"profile_route_rejected": True},
        {"user_id": None},
        {"user_id": 137246801},
        {"chat_id": "123"},
        {"user_id": "bad", "chat_id": "bad"},
    ],
)
def test_real_source_variants_fail_closed(changes):
    result = diagnostic(source(**changes))
    assert_denied(result)
    assert result["actor_observation"]["candidate_recognized"] is False


def test_missing_local_malformed_and_forged_arguments_fail_closed():
    from gateway.config import Platform

    assert_denied(diagnostic(), "source_unavailable")
    assert_denied(
        diagnostic(source(platform=Platform.LOCAL), platform="local"), "unsupported_platform"
    )
    assert_denied(diagnostic(SimpleNamespace()), "source_platform_mismatch")
    assert_denied(diagnostic(source(), raw_args="owner=true secret-in-args"), "invalid_arguments")


def test_native_invoker_forwards_context_and_registered_callback_denies(native):
    from hermes_cli.plugin_command_dispatch import invoke_plugin_command

    home, manager = native
    manager.discover_and_load()
    handler = manager._plugin_commands["personal-access"]["handler"]
    src, received = source(), []
    context = dict(
        source=src,
        platform="telegram",
        session_id="synthetic-private-session",
        session_key="synthetic-private-key",
    )

    def observe(raw_args, *, source, platform, session_id, session_key):
        received.append((raw_args, source, platform, session_id, session_key))
        return handler(
            raw_args,
            source=source,
            platform=platform,
            session_id=session_id,
            session_key=session_key,
        )

    assert_denied(
        json.loads(invoke_plugin_command(observe, "status", **context)),
        "receiving_transport_unverified",
    )
    assert received == [
        ("status", src, "telegram", "synthetic-private-session", "synthetic-private-key")
    ]
    assert_denied(
        json.loads(invoke_plugin_command(handler, "secret-in-args", **context)), "invalid_arguments"
    )
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize("mode", ["default", "read_only", "local_tasks"])
def test_cli_and_slash_do_not_read_storage_or_change_config(native, capsys, monkeypatch, mode):
    import sqlite3

    from hermes_cli.plugin_command_dispatch import invoke_plugin_command

    home, manager = native
    configure(home, mode)
    before = (home / "config.yaml").read_bytes()
    manager.discover_and_load()
    blocked = Mock(side_effect=AssertionError("diagnostic attempted SQLite access"))
    monkeypatch.setattr(sqlite3, "connect", blocked)
    _, result = invoke(manager._cli_commands["personal-agent"], capsys, "access")
    assert_denied(result, "source_unavailable")
    handler = manager._plugin_commands["personal-access"]["handler"]
    assert_denied(
        json.loads(invoke_plugin_command(handler, "", source=source(), platform="telegram"))
    )
    blocked.assert_not_called()
    assert (home / "config.yaml").read_bytes() == before
    assert not (home / "plugin-data").exists()


def test_registration_reload_disable_and_unload_clear_slash(native):
    home, manager = native
    manager.discover_and_load()
    assert set(manager._plugin_commands) == {"personal-access"}
    manager.discover_and_load(force=True)
    assert set(manager._plugin_commands) == {"personal-access"}
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["disabled"] = [PLUGIN_ID]
    (home / "config.yaml").write_text(json.dumps(config))
    manager.discover_and_load(force=True)
    assert not manager._plugin_commands
    assert "personal-agent" not in manager._cli_commands
    configure(home)
    manager.discover_and_load(force=True)
    assert set(manager._plugin_commands) == {"personal-access"}
    manager.unload()
    assert not manager._plugin_commands
    assert "personal-agent" not in manager._cli_commands


def test_injected_event_native_resolution_and_dispatch_do_not_invoke_slash(native, monkeypatch):
    import hermes_cli.plugins
    from gateway.platforms.event import MessageEvent
    from gateway.run_inbound import GatewayInboundMixin

    _, manager = native
    manager.discover_and_load()
    event = MessageEvent(
        text="/personal-access secret-in-args",
        source=source(),
        internal=True,
        allow_gateway_control=False,
    )
    assert event.is_command() is False
    assert event.get_command() is None
    lookup = Mock(side_effect=AssertionError("injected text reached plugin lookup"))
    monkeypatch.setattr(hermes_cli.plugins, "get_plugin_command_handler", lookup)
    runner = object.__new__(GatewayInboundMixin)
    runner._draining = False
    # Real gateway resolver and quick/plugin sink, not the full inbound pipeline.
    resolved = asyncio.run(runner._hm_resolve_command(event, event.source, "synthetic-private-key"))
    assert resolved == (False, None, None, None)
    assert asyncio.run(
        runner._hm_dispatch_quick_and_plugin_commands(event, event.source, resolved[2])
    ) == (False, None, None)
    lookup.assert_not_called()


@pytest.mark.parametrize("admitted", [True, False, "true", 1])
def test_hosted_http_admission_never_supplies_owner_proof(admitted):
    from hermes_cli.plugin_host_http_auth import with_hosted_admission

    observed = []

    async def app(scope, receive, send):
        observed.append(scope)

    original = {"type": "http", "state": {"untouched": True}}
    asyncio.run(with_hosted_admission(app, admitted)(original, None, None))
    assert observed[0]["state"]["hosted_http_authenticated"] is (admitted is True)
    assert "hosted_http_authenticated" not in original["state"]
    src = source()
    src.hosted_http_authenticated = observed[0]["state"]["hosted_http_authenticated"]
    assert_denied(diagnostic(src), "receiving_transport_unverified")
