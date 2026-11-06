"""Offline static template and fail-before-registration tests."""

import json
import socket
from copy import deepcopy

import pytest

from personal_agent.blueprints import planning_check_in
from personal_agent.plugin import register


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    monkeypatch.setattr("personal_agent.plugin.current_profile_home", lambda: tmp_path)

    def denied(*args, **kwargs):
        raise AssertionError("Network/listener use is forbidden in blueprint tests")

    monkeypatch.setattr(socket.socket, "bind", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


class Context:
    def __init__(self, config):
        self.config = config
        self.calls = []

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, **kwargs):
        self.calls.append(("tool", kwargs))

    def register_cli_command(self, **kwargs):
        self.calls.append(("cli", kwargs))

    def register_command(self, *args, **kwargs):
        self.calls.append(("command", kwargs))

    def register_automation_blueprint(self, **kwargs):
        self.calls.append(("blueprint", kwargs))


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_non_boolean_flag_fails_before_any_registration(value):
    ctx = Context({"planning_blueprint": value})
    with pytest.raises(ValueError, match="planning_blueprint must be a boolean"):
        register(ctx)
    assert ctx.calls == []


@pytest.mark.parametrize("config", [{}, {"planning_blueprint": False}])
def test_disabled_does_not_load_template(config, monkeypatch):
    def unexpected():
        raise AssertionError("Disabled template was loaded")

    monkeypatch.setattr("personal_agent.blueprints.planning_check_in", unexpected)
    ctx = Context(config)
    register(ctx)
    assert [name for name, _ in ctx.calls] == ["tool", "cli", "command"]


@pytest.mark.parametrize("mode", ["read_only", "local_tasks"])
def test_registration_only_adds_static_template(mode, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = Context({"mode": mode, "planning_blueprint": True})
    register(ctx)
    assert ctx.calls[-1] == ("blueprint", planning_check_in())
    assert list(tmp_path.iterdir()) == []


def test_template_is_fresh_serializable_and_has_no_execution_configuration():
    first = planning_check_in()
    original = deepcopy(first)
    first["slots"][0]["default"] = "00:00"
    assert planning_check_in() == original
    assert json.loads(json.dumps(original)) == original
    assert original["skills"] == []
    assert original["deliver_default"] == "local"
    assert not {"model", "provider", "tools", "script", "budget"} & original.keys()
    fields = {slot["name"]: slot for slot in original["slots"]}
    assert fields["language"]["options"] == ["English", "Simplified Chinese"]
    assert fields["deliver"]["strict"] is False
    assert "Do not use tools" in original["prompt_template"]


def test_status_describes_template_without_claiming_job_or_delivery_authority():
    from personal_agent.status import build_status

    status = build_status()
    info = status["automation_blueprints"]
    assert info["planning_template_implemented"] is True
    assert info["default_enabled"] is False
    assert info["creates_jobs_on_load"] is False
    assert info["manages_existing_jobs"] is False
    assert status["capabilities"]["reminders"] is False
    assert status["capabilities"]["external_delivery"] is False
    assert status["safety"]["release_gate"] == "blocked"
