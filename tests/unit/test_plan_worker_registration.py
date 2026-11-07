"""Default-off worker admission leaves unrelated features usable on old hosts."""

import json
from types import SimpleNamespace

import pytest
from test_kanban_registration import Context

from personal_agent.plugin import plan_worker_host_status, register
from personal_agent.status import build_status


class Service:
    @property
    def text_worker_contract(self):
        return "hermes.text-worker.v1"

    def launch_text(self, *args, **kwargs):
        raise AssertionError("No request during registration or status")

    authorize_text_route = result = launch_text


class Host(Context):
    def __init__(self, config, service=None, consent=True):
        super().__init__(config)
        self.subagent_lifecycle = service
        self.consent = consent

    def has_capability(self, name):
        assert name == "llm.text_worker"
        return self.consent

    def register_hook(self, *args, **kwargs):
        pass


def settings(**values):
    return dict(
        mode="local_tasks",
        local_conversation=True,
        local_model_tools=True,
        plan_worker=True,
        **values,
    )


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr("personal_agent.plugin.current_profile_home", lambda: tmp_path)
    monkeypatch.setattr("personal_agent.task_plan_worker.current_profile_home", lambda: tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "service,consent,reason",
    [
        (None, True, "unsupported_host"),
        (SimpleNamespace(text_worker_contract="hermes.text-worker.v1"), True, "unsupported_host"),
        (Service(), False, "consent_required"),
        (Service(), 1, "consent_required"),
    ],
)
def test_unavailable_worker_does_not_break_ordinary_tasks(home, service, consent, reason):
    ctx = Host(settings(), service, consent)
    register(ctx)
    assert "personal-plan-worker" not in ctx.commands
    assert "personal_task_plan_preview" not in ctx.tools
    assert "personal-tasks" in ctx.commands and "personal_tasks_read" in ctx.tools
    observed = json.loads(ctx.tools["personal_agent_status"]({}))["plan_worker"]
    assert observed["host"] == reason and not observed["enabled"]
    assert list(home.iterdir()) == []


def test_default_off_does_not_probe_host(home):
    class NoHost(Host):
        def has_capability(self, name):
            raise AssertionError("Default off must not probe capabilities")

    ctx = NoHost({})
    register(ctx)
    assert "personal-plan-worker" not in ctx.commands
    assert (
        json.loads(ctx.tools["personal_agent_status"]({}))["plan_worker"]["host"] == "not_checked"
    )
    assert not build_status()["plan_worker"]["enabled"]


def test_registered_status_rechecks_current_consent_without_route_resolution(home):
    ctx = Host(settings(), Service())
    register(ctx)
    assert "personal-plan-worker" in ctx.commands
    assert "personal_task_plan_preview" in ctx.tools

    def status():
        return json.loads(ctx.tools["personal_agent_status"]({}))["plan_worker"]

    assert status()["enabled"] and not status()["route_verified"]
    ctx.consent = False
    assert status()["registered"] and not status()["enabled"]
    ctx.config["plan_worker"] = False
    assert status()["host"] == "not_checked" and not status()["enabled"]
    assert list(home.iterdir()) == []


def test_late_consent_requires_reload_and_does_not_create_tool(home):
    ctx = Host(settings(), Service(), False)
    register(ctx)
    ctx.consent = True
    state = json.loads(ctx.tools["personal_agent_status"]({}))["plan_worker"]
    assert state["host"] == "available" and state["reload_required"] and not state["enabled"]
    assert "personal_task_plan_preview" not in ctx.tools


@pytest.mark.parametrize(
    "config", [{"plan_worker": True}, {"plan_worker": 1}, {"plan_worker": "true"}]
)
def test_invalid_config_fails_before_registration(home, config):
    ctx = Host(config, Service())
    with pytest.raises(ValueError):
        register(ctx)
    assert not ctx.tools and not ctx.commands


def test_host_probe_exception_is_fixed_diagnostic():
    class Bad(Host):
        def has_capability(self, name):
            raise ValueError("private detail")

    assert plan_worker_host_status(Bad({}, Service())) == "host_check_failed"
