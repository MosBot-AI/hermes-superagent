"""Real pinned Hermes discovery and dispatch. Run with scripts/check.py --hermes.

No parser, manager, registry or config-loader mocks. Private manager fields are
test observations only; the shipped plugin never imports host internals.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ID = "hermes-personal-agent"
TOOL_NAME = "personal_agent_status"


@pytest.fixture
def home(tmp_path, monkeypatch):
    host = tmp_path / "hermes-home"
    plugin = host / "plugins" / PLUGIN_ID
    plugin.mkdir(parents=True)
    for name in ("plugin.yaml", "__init__.py", "pyproject.toml", "compatibility.json", "LICENSE"):
        shutil.copy2(PLUGIN_ROOT / name, plugin / name)
    shutil.copytree(
        PLUGIN_ROOT / "personal_agent",
        plugin / "personal_agent",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    empty_bundled = tmp_path / "empty-bundled"
    empty_bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(host))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(empty_bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "os-home")
    return host


def write_config(home, *, enabled=True, disabled=False, mode="read_only"):
    # JSON is valid YAML; use the actual host config loader, not a stub.
    config = {
        "plugins": {
            "enabled": [PLUGIN_ID] if enabled else [],
            "disabled": [PLUGIN_ID] if disabled else [],
            "entries": {PLUGIN_ID: {"settings": {"mode": mode}}},
        },
        "delegation": {"backend": "default"},
    }
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")


@pytest.fixture
def manager(home):
    from hermes_cli.plugins import PluginManager

    result = PluginManager()
    try:
        yield result
    finally:
        result.unload()


def test_imports_come_from_exact_pinned_hermes_checkout():
    import hermes_cli.plugins

    upstream = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    expected = json.loads((PLUGIN_ROOT / "compatibility.json").read_text())["hermes_commit"]
    actual = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    assert actual == expected, "Contract results require the exact recorded Hermes commit"


def test_real_discovery_tool_dispatch_and_cli(home, manager, capsys):
    from tools.registry import registry

    write_config(home)
    original_config = (home / "config.yaml").read_bytes()
    manager.discover_and_load()
    loaded = manager._plugins[PLUGIN_ID]
    assert loaded.enabled and loaded.error is None
    assert loaded.tools_registered == [TOOL_NAME]
    assert not loaded.hooks_registered
    assert loaded.module is not None
    assert Path(loaded.module.__file__).is_relative_to(home / "plugins" / PLUGIN_ID)
    entry = registry.get_entry(TOOL_NAME, scope=manager.scope_key)
    assert entry is not None
    assert entry.schema["parameters"]["additionalProperties"] is False

    raw = registry.dispatch(TOOL_NAME, {}, scope=manager.scope_key, session_id="synthetic")
    result = json.loads(raw)
    assert result["status"] == "ok"
    assert result["safety"]["release_gate"] == "blocked"
    assert result["safety"]["host_write_paths_enforced"] is False

    command = manager._cli_commands["personal-agent"]
    parser = argparse.ArgumentParser()
    command["setup_fn"](parser)
    command["handler_fn"](parser.parse_args(["status"]))
    assert json.loads(capsys.readouterr().out) == result
    assert (home / "config.yaml").read_bytes() == original_config
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize("kwargs", [{"enabled": False}, {"disabled": True}])
def test_host_enable_and_disable_gate_is_respected(home, manager, kwargs):
    from tools.registry import registry

    write_config(home, **kwargs)
    manager.discover_and_load()
    loaded = manager._plugins.get(PLUGIN_ID)
    assert loaded is None or not loaded.enabled
    assert registry.get_entry(TOOL_NAME, scope=manager.scope_key) is None
    assert "personal-agent" not in manager._cli_commands


@pytest.mark.parametrize("mode", ["live", "shadow", True, None, 1, {}])
def test_invalid_mode_registers_no_tools_or_commands(home, manager, mode):
    from tools.registry import registry

    write_config(home, mode=mode)
    manager.discover_and_load()
    loaded = manager._plugins[PLUGIN_ID]
    assert not loaded.enabled
    assert "supports only read_only or local_tasks mode" in loaded.error
    assert registry.get_entry(TOOL_NAME, scope=manager.scope_key) is None
    assert "personal-agent" not in manager._cli_commands


def test_dispatch_rejects_forged_approval_and_context(home, manager):
    from tools.registry import registry

    write_config(home)
    manager.discover_and_load()
    response = registry.dispatch(
        TOOL_NAME,
        {"approved": True, "recipient": "synthetic-secret"},
        scope=manager.scope_key,
        session_id="synthetic-session",
    )
    assert json.loads(response)["status"] == "blocked"
    assert "synthetic-secret" not in response


def test_code_defaults_work_without_manifest_default_injection(home, manager):
    from tools.registry import registry

    (home / "config.yaml").write_text(
        json.dumps({"plugins": {"enabled": [PLUGIN_ID]}}), encoding="utf-8"
    )
    manager.discover_and_load()
    assert manager._plugins[PLUGIN_ID].error is None
    result = registry.dispatch(TOOL_NAME, {}, scope=manager.scope_key)
    assert json.loads(result)["mode"] == "read_only"


def test_host_doctor_agrees_with_actual_registration(home):
    from hermes_cli.plugin_dev import doctor_plugin

    report = doctor_plugin(home / "plugins" / PLUGIN_ID)
    assert report.ok, report.format_text()
    assert report.registered_tools == (TOOL_NAME,)
    assert not report.registered_hooks


def test_actual_package_metadata_has_no_install_requirements(home):
    from pm.plugin_declarations import read_python_declaration

    staged = home / "plugins" / PLUGIN_ID
    declaration = read_python_declaration(staged)
    assert declaration.pyproject == staged / "pyproject.toml"
    assert declaration.requirements == ()
    assert declaration.install_requirements == ()
    assert declaration.installs_packages is False


@pytest.mark.parametrize("change", [{"mode": "live"}, {"disabled": True}])
def test_reload_with_invalid_or_disabled_config_clears_tool_and_cli(home, manager, change):
    from tools.registry import registry

    write_config(home)
    manager.discover_and_load()
    assert registry.get_entry(TOOL_NAME, scope=manager.scope_key) is not None
    assert "personal-agent" in manager._cli_commands
    write_config(home, **change)
    manager.discover_and_load(force=True)
    assert registry.get_entry(TOOL_NAME, scope=manager.scope_key) is None
    assert "personal-agent" not in manager._cli_commands


def test_force_reload_and_unload_do_not_leave_tools(home, manager):
    from tools.registry import registry

    write_config(home)
    manager.discover_and_load()
    manager.discover_and_load(force=True)
    assert manager._plugins[PLUGIN_ID].tools_registered == [TOOL_NAME]
    assert json.loads(registry.dispatch(TOOL_NAME, {}, scope=manager.scope_key))["status"] == "ok"
    manager.unload()
    assert registry.get_entry(TOOL_NAME, scope=manager.scope_key) is None
    assert "personal-agent" not in manager._cli_commands


def test_public_storage_helper_tracks_profile_scope_and_rejects_traversal(home, tmp_path):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from plugins.plugin_storage import plugin_data_dir

    first = plugin_data_dir(PLUGIN_ID)
    other = tmp_path / "second-profile"
    token = set_hermes_home_override(other)
    try:
        second = plugin_data_dir(PLUGIN_ID)
        assert second == other / "plugin-data" / PLUGIN_ID
        assert first != second
    finally:
        reset_hermes_home_override(token)
    assert plugin_data_dir(PLUGIN_ID) == first
    with pytest.raises(ValueError):
        plugin_data_dir("../outside")
