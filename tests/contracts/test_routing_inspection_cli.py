"""Native saved-config diagnostics, with no credential/model/worker resolution."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_local_task_cli import configure, entry, invoke
from test_local_task_cli import native as native


def update(home, **delegation):
    raw = json.loads((home / "config.yaml").read_text())
    raw["delegation"].update(delegation)
    (home / "config.yaml").write_text(json.dumps(raw))


@pytest.mark.parametrize("mode", ["default", "read_only", "local_tasks"])
def test_native_registered_diagnostic_reads_only_saved_declarations(
    native, capsys, monkeypatch, mode
):
    from agent import delegation_registry
    from hermes_cli import runtime_provider

    home, manager = native
    configure(home, mode)
    update(
        home,
        provider="private-provider",
        model="private-model",
        reasoning_effort="high",
        fallback_providers=[],
        api_key="private-inline-key",
        base_url="https://private.endpoint/key",
    )
    command = entry(manager)
    before = (home / "config.yaml").read_bytes()
    forbidden = Mock(side_effect=AssertionError("Inspection must not resolve or execute"))
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", forbidden)
    monkeypatch.setattr(delegation_registry, "get_active_provider", forbidden)
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 0
    assert report["status"] == "ok"
    assert report["saved_route_shape"] == "endpoint_and_model_declared"
    assert report["saved_effort"]["requested_effort"] == "high"
    assert report["shadow_ready"] is False
    assert "private" not in json.dumps(report)
    forbidden.assert_not_called()
    assert (home / "config.yaml").read_bytes() == before
    assert not (home / "plugin-data").exists()


def test_saved_config_is_fresh_without_mutating_host_cache_or_expanding_env(
    native, capsys, monkeypatch
):
    from hermes_cli.config import load_config_readonly

    home, manager = native
    command = entry(manager)
    cached = load_config_readonly()
    original = json.dumps(cached, sort_keys=True)
    monkeypatch.setenv("ROUTING_PRIVATE_MODEL", "never-output-this-value")
    update(
        home, model="${ROUTING_PRIVATE_MODEL}", provider="private-provider", fallback_providers=[]
    )
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 0
    assert report["declarations"]["model"] == "unexpanded_reference"
    assert "never-output" not in json.dumps(report)
    assert json.dumps(cached, sort_keys=True) == original
    update(home, model="literal-private-model", profile="private-profile")
    assert (
        invoke(command, capsys, "routing", "inspect")[1]["saved_route_shape"]
        == "profile_dependent_uninspected"
    )


@pytest.mark.parametrize("body", ["provider: [private-secret", '"private-nonmapping-root"', "[]"])
def test_bad_raw_config_never_falls_back_to_a_claimed_good_baseline(native, capsys, body):
    home, manager = native
    command = entry(manager)
    (home / "config.yaml").write_text(body)
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 1 and report["status"] == "blocked"
    assert report["reason"] in {"saved_configuration_unreadable", "invalid_saved_configuration"}
    assert "private" not in json.dumps(report)


def test_retained_cli_is_blocked_after_unload_without_config_read(native, capsys, monkeypatch):
    from hermes_cli.config_backend import FileBackend

    _, manager = native
    command = entry(manager)
    manager.unload()
    read = Mock(side_effect=AssertionError("Unloaded inspection read config"))
    monkeypatch.setattr(FileBackend, "read_user_doc", read)
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 1 and report["reason"] == "inspector_closed"
    read.assert_not_called()


def test_profile_change_is_blocked_before_read(native, tmp_path, capsys, monkeypatch):
    from hermes_cli.config_backend import FileBackend

    _, manager = native
    command = entry(manager)
    other = tmp_path / "other-profile"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))
    read = Mock(side_effect=AssertionError("Wrong profile config opened"))
    monkeypatch.setattr(FileBackend, "read_user_doc", read)
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 1 and report["reason"] == "profile_context_changed"
    read.assert_not_called()


def test_non_file_backend_is_not_read_or_bypassed(native, capsys, monkeypatch):
    from hermes_cli import config_backend

    _, manager = native
    command = entry(manager)
    read = Mock(side_effect=AssertionError("Must not bypass selected config backend"))
    backend = SimpleNamespace(name="remote", read_user_doc=read)
    monkeypatch.setattr(config_backend, "get_config_backend", lambda: backend)
    monkeypatch.setattr(config_backend.FileBackend, "read_user_doc", read)
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 1 and report["reason"] == "unsupported_config_backend"
    read.assert_not_called()


def test_actual_unknown_config_backend_error_is_bounded(native, capsys, monkeypatch):
    _, manager = native
    command = entry(manager)
    monkeypatch.setenv("HERMES_CONFIG_BACKEND", "unavailable_private_backend")
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 1 and report["reason"] == "unsupported_config_backend"
    assert "private" not in json.dumps(report)


def environment(home, tmp_path):
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_PYTHON": sys.executable,
        "HERMES_BUNDLED_PLUGINS": os.environ["HERMES_BUNDLED_PLUGINS"],
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
    }


GUARD = """
import socket
def deny(*args, **kwargs):
    raise AssertionError("Routing inspection must not use network")
socket.create_connection = deny
socket.socket.connect = deny
socket.socket.connect_ex = deny
"""


def test_real_top_level_cli_inspection(native, tmp_path):
    from hermes_cli import main

    home, _ = native
    update(
        home,
        provider="private-provider",
        model="private-model",
        fallback_providers=[],
        reasoning_effort="high",
        service_tier="fast",
    )
    before = (home / "config.yaml").read_bytes()
    bootstrap = (
        GUARD
        + """
import sys
sys.argv = ["hermes", "personal-agent", "routing", "inspect"]
from hermes_cli.main import main
main()
"""
    )
    result = subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=Path(main.__file__).resolve().parents[1],
        env=environment(home, tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["saved_route_shape"] == "provider_and_model_declared"
    assert "default_backend_ignores_delegation_service_tier" in report["notes"]
    assert "private-provider" not in result.stdout and "private-model" not in result.stdout
    assert (home / "config.yaml").read_bytes() == before


@pytest.mark.parametrize("safe", [False, True])
def test_managed_worker_snapshot_rejects_raw_profile_read(native, tmp_path, safe):
    from hermes_cli import main

    home, _ = native
    root = Path(__file__).resolve().parents[2]
    bootstrap = (
        GUARD
        + f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
from agent.managed_worker import bind_worker_policy
bind_worker_policy({{"safe_mode": {safe!r}, "ignore_user_config": False,
    "policy": {{"config_json": json.dumps({{"delegation": {{"model": "private-frozen"}}}})}}}})
from hermes_cli.config_backend import FileBackend
def forbidden(*args, **kwargs):
    raise AssertionError("Frozen worker must not read profile config")
FileBackend.read_user_doc = forbidden
from personal_agent.routing_cli import RoutingInspector
print(json.dumps(RoutingInspector(Path({str(home)!r})).inspect()))
"""
    )
    result = subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=Path(main.__file__).resolve().parents[1],
        env=environment(home, tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "blocked" and report["reason"] == "unsupported_runtime"
    assert "private-frozen" not in result.stdout


def test_diagnostic_tier_warning_matches_pinned_default_backend():
    from plugins.delegation.default import DefaultDelegationProvider

    route = DefaultDelegationProvider().route_task(
        {"goal": "synthetic"},
        {"provider": "synthetic-provider", "model": "synthetic-model", "service_tier": "fast"},
    )
    assert "service_tier" not in route
    assert route["model"] == "synthetic-model"


def test_profile_change_during_read_discards_inspection(native, capsys, monkeypatch, tmp_path):
    from hermes_cli.config_backend import FileBackend

    _, manager = native
    command = entry(manager)
    other = tmp_path / "other-profile"
    other.mkdir()

    def changed(*args):
        monkeypatch.setenv("HERMES_HOME", str(other))
        return {"delegation": {"model": "private-interleaved-model"}}

    monkeypatch.setattr(FileBackend, "read_user_doc", changed)
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 1 and report["reason"] == "profile_context_changed"
    assert "private" not in json.dumps(report)


def test_unload_during_read_discards_inspection(native, capsys, monkeypatch):
    from hermes_cli.config_backend import FileBackend

    _, manager = native
    command = entry(manager)

    def unloaded(*args):
        manager.unload()
        return {"delegation": {"model": "private-interleaved-model"}}

    monkeypatch.setattr(FileBackend, "read_user_doc", unloaded)
    code, report = invoke(command, capsys, "routing", "inspect")
    assert code == 1 and report["reason"] == "inspector_closed"
    assert "private" not in json.dumps(report)
