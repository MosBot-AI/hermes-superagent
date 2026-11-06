"""Pinned native discovery/catalog/consumer contracts, without executing cron.

Both registration transports are real (including the pipe plugin-host process).
A test-only child environment wrapper installs the socket guard.
Only job-creation/provider notification seams are intercepted in consumer tests;
no scheduler, model, gateway, listener or persisted job is started.
"""

import asyncio
import json
import os
import shutil
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = "hermes-personal-agent"
KEY = f"{PLUGIN}:planning-check-in"
GUARD = """import socket
from pathlib import Path

Path(__file__).with_suffix(".loaded").touch()

def denied(*args, **kwargs):
    raise AssertionError("Blueprint tests forbid socket bind/connect")

socket.socket.bind = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
"""


@pytest.fixture(params=["in_process", "host"])
def native(request, tmp_path, monkeypatch):
    from hermes_cli.plugin_host import PluginHost
    from hermes_cli.plugins import _reset_plugin_managers_for_tests, get_plugin_manager

    def denied(*args, **kwargs):
        raise AssertionError("Blueprint tests forbid socket bind/connect")

    for name in ("bind", "connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, denied)
    # sitecustomize also guards the real pipe-host child, not just pytest.
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(GUARD)
    # Hermes deliberately scrubs inherited PYTHONPATH. Add only the test guard
    # after its real environment builder; preserve the native launch and wire.
    original_env = PluginHost._env

    def guarded_env(self):
        env = original_env(self)
        env["PYTHONPATH"] = str(guard) + os.pathsep + env.get("PYTHONPATH", "")
        return env

    monkeypatch.setattr(PluginHost, "_env", guarded_env)
    home = tmp_path / "profile"
    plugin = home / "plugins" / PLUGIN
    plugin.mkdir(parents=True)
    for name in ("plugin.yaml", "__init__.py", "pyproject.toml", "compatibility.json", "LICENSE"):
        shutil.copy2(ROOT / name, plugin / name)
    shutil.copytree(ROOT / "personal_agent", plugin / "personal_agent")
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "os-home")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    _reset_plugin_managers_for_tests()
    manager = get_plugin_manager()

    def configure(value=True, enabled=True, omit=False):
        settings = {} if omit else {"planning_blueprint": value}
        data = {
            "plugins": {
                "enabled": [PLUGIN] if enabled else [],
                "isolation": request.param,
                "entries": {PLUGIN: {"settings": settings}},
            },
            "delegation": {"backend": "default"},
        }
        (home / "config.yaml").write_text(json.dumps(data))
        manager.discover_and_load(force=True)
        if request.param == "host" and enabled:
            assert (guard / "sitecustomize.loaded").exists()
        assert json.loads((home / "config.yaml").read_text()) == data
        assert not (home / "cron" / "jobs.json").exists()
        assert not (home / "plugin-data").exists()
        return manager

    try:
        yield configure, home, manager
    finally:
        _reset_plugin_managers_for_tests()


def test_discovery_catalog_reload_and_unload(native):
    from cron.blueprint_catalog import blueprint_form_schema, get_blueprint, list_blueprints

    configure, home, manager = native
    configure(omit=True)
    assert get_blueprint(KEY) is None
    configure()
    assert manager._plugins[PLUGIN].enabled, manager._plugins[PLUGIN].error
    blueprint = get_blueprint(KEY)
    assert blueprint is not None
    assert blueprint.plugin == PLUGIN
    assert len([bp for bp in list_blueprints() if bp.key == KEY]) == 1
    fields = {f["name"]: f for f in blueprint_form_schema(blueprint)["fields"]}
    assert fields["recurrence"]["strict"] is True
    assert fields["deliver"]["default"] == "local"
    assert fields["deliver"]["strict"] is False
    configure()
    assert len(manager.list_automation_blueprints()) == 1
    configure(False)
    assert get_blueprint(KEY) is None
    configure()
    manager.unload()
    assert manager.list_automation_blueprints() == []
    configure(enabled=False)
    assert get_blueprint(KEY) is None
    assert not (home / "cron" / "jobs.json").exists()


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", "false", [], {}])
def test_invalid_setting_leaves_no_registrations(native, invalid):
    from tools.registry import registry

    configure, _, manager = native
    configure()
    configure(invalid)
    assert not manager._plugins[PLUGIN].enabled
    assert "planning_blueprint must be a boolean" in manager._plugins[PLUGIN].error
    assert manager.list_automation_blueprints() == []
    assert registry.get_entry("personal_agent_status", scope=manager.scope_key) is None
    assert "personal-agent" not in manager._cli_commands
    assert not manager._plugins[PLUGIN].commands_registered


def test_native_fill_validation_and_defaults(native):
    from cron.blueprint_catalog import BlueprintFillError, fill_blueprint, get_blueprint
    from cron.jobs import parse_schedule

    configure, _, _ = native
    configure()
    blueprint = get_blueprint(KEY)
    default = fill_blueprint(blueprint, {})
    assert default["schedule"] == "0 9 * * 1-5"
    assert default["deliver"] == "local"
    assert "in English" in default["prompt"]
    assert set(default) == {"prompt", "schedule", "name", "deliver"}
    for recurrence, dow in (("everyday", "*"), ("weekdays", "1-5"), ("weekends", "0,6")):
        spec = fill_blueprint(
            blueprint,
            {"time": "23:59", "recurrence": recurrence, "language": "Simplified Chinese"},
        )
        assert spec["schedule"] == f"59 23 * * {dow}"
        assert "in Simplified Chinese" in spec["prompt"]
        parse_schedule(spec["schedule"])
    for invalid in (
        {"time": "24:00"},
        {"time": "09:60"},
        {"time": "tomorrow"},
        {"recurrence": "1-5"},
        {"focus": "read inbox"},
        {"language": "tool injection"},
        {"schedule": "* * * * *"},
        {"model": "override"},
    ):
        with pytest.raises(BlueprintFillError):
            fill_blueprint(blueprint, invalid)
    assert fill_blueprint(blueprint, {"deliver": "telegram"})["deliver"] == "telegram"


def test_real_slash_consumer_captures_create_kwargs_only(native, monkeypatch):
    from cron import scheduler
    from cron.blueprint_catalog import blueprint_slash_command, get_blueprint
    from hermes_cli.blueprint_cmd import handle_blueprint_command

    configure, home, _ = native
    configure()
    calls = []

    def capture(**kwargs):
        calls.append(kwargs)
        return {"schedule_display": kwargs["schedule"]}

    monkeypatch.setattr(scheduler, "create_job_with_scheduler_registration", capture)
    assert KEY in handle_blueprint_command("").text
    assert handle_blueprint_command(KEY).agent_seed
    assert not calls
    command = blueprint_slash_command(get_blueprint(KEY))
    result = handle_blueprint_command(command.removeprefix("/blueprint "))
    assert "Scheduled" in result.text
    assert calls[0]["deliver"] == "local"
    assert calls[0]["schedule"] == "0 9 * * 1-5"
    handle_blueprint_command(KEY + " time=25:00")
    assert len(calls) == 1
    assert not (home / "cron" / "jobs.json").exists()


def test_real_dashboard_catalog_and_submit_without_server(native, monkeypatch):
    from cron.scheduler_delivery import cron_delivery_targets
    from hermes_cli.web_models import AutomationBlueprintInstantiate
    from hermes_cli.web_routers import cron

    configure, home, _ = native
    configure()
    # No connected accounts exist in this synthetic profile. Native target lookup is read-only.
    assert isinstance(cron_delivery_targets(), list)
    entries = cron._blueprint_catalog_sync(None)
    entry = next(e for e in entries if e["key"] == KEY)
    deliver = next(f for f in entry["fields"] if f["name"] == "deliver")
    assert deliver["default"] == "local"
    assert "local" in deliver["options"]
    calls = []

    def capture(profile, action, **kwargs):
        calls.append((profile, action, kwargs))
        return {"id": "synthetic-not-persisted"}

    monkeypatch.setattr(cron, "_call_cron_for_profile", capture)
    monkeypatch.setattr(cron, "_notify_cron_provider_for_profile", lambda profile: None)
    result = asyncio.run(
        cron.instantiate_blueprint(
            AutomationBlueprintInstantiate(
                blueprint=KEY, values={"language": "Simplified Chinese"}
            ),
        )
    )
    assert result == {"id": "synthetic-not-persisted"}
    assert calls[0][0:2] == ("default", "create_job")
    assert calls[0][2]["deliver"] == "local"
    assert "in Simplified Chinese" in calls[0][2]["prompt"]
    assert not (home / "cron" / "jobs.json").exists()
