"""Registration/status declarations only; never import or open native Kanban."""

import json
import sys
from types import ModuleType

import pytest

from personal_agent.plugin import register
from personal_agent.status import build_status


class Context:
    def __init__(self, config):
        self.config = config
        self.commands = {}
        self.tools = {}
        self.unload = []

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def on_unload(self, callback):
        self.unload.append(callback)

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = handler

    def register_tool(self, name, handler, **kwargs):
        self.tools[name] = handler

    def register_cli_command(self, **kwargs):
        pass


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    instances = []
    module = ModuleType("personal_agent.kanban_handoff")

    class Handoff:
        def __init__(self, *, bound_home, read_config):
            self.home, self.config, self.closed = bound_home, read_config, False
            instances.append(self)

        def command(self, *args, **kwargs):
            return "fixture"

        def close(self):
            self.closed = True

    module.LocalKanbanHandoff = Handoff
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr("personal_agent.plugin.current_profile_home", lambda: tmp_path)
    return tmp_path, instances


@pytest.mark.parametrize("enabled", [False, True])
def test_command_registered_even_when_creation_disabled_and_unloads(fixture, enabled):
    home, instances = fixture
    ctx = Context(
        {
            "mode": "local_tasks",
            "local_conversation": True,
            "kanban_handoff": enabled,
            "kanban_handoff_board": "default",
        }
    )
    register(ctx)
    assert ctx.commands["personal-handoff"].__self__ is instances[0]
    assert instances[0].home == home
    section = json.loads(ctx.tools["personal_agent_status"]({}))["kanban_handoff"]
    assert section["enabled"] is enabled
    assert section["native_runtime_verified"] is False
    assert section["native_schema_verified"] is False
    assert section["dispatch_enabled"] is False
    assert list(home.iterdir()) == []
    for callback in ctx.unload:
        callback()
    assert instances[0].closed


def test_default_no_command_or_adapter_construction(fixture):
    _, instances = fixture
    ctx = Context({})
    register(ctx)
    assert "personal-handoff" not in ctx.commands and not instances
    assert build_status()["kanban_handoff"]["enabled"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"kanban_handoff": 1},
        {"kanban_handoff": "true"},
        {"kanban_handoff_board": None},
        {"kanban_handoff_board": ""},
        {"kanban_handoff_board": "Default"},
        {"kanban_handoff_board": "../default"},
        {"kanban_handoff_board": "board name"},
        {"kanban_handoff_board": "a" * 65},
        {"local_conversation": False},
        {"mode": "read_only"},
    ],
)
def test_invalid_configuration_fails_before_registration(fixture, changes):
    _, instances = fixture
    config = {
        "mode": "local_tasks",
        "local_conversation": True,
        "kanban_handoff": True,
        "kanban_handoff_board": "default",
    }
    ctx = Context(config | changes)
    with pytest.raises(ValueError):
        register(ctx)
    assert not ctx.commands and not ctx.tools and not instances


def test_status_rechecks_flags_without_echoing_board_or_probing(fixture):
    home, _ = fixture
    ctx = Context({"mode": "local_tasks", "local_conversation": True})
    register(ctx)
    ctx.config.update(kanban_handoff=True, kanban_handoff_board="explicit-board")
    raw = ctx.tools["personal_agent_status"]({})
    assert json.loads(raw)["kanban_handoff"]["enabled"] is True
    assert "explicit-board" not in raw and list(home.iterdir()) == []
    ctx.config["kanban_handoff_board"] = ""
    assert (
        json.loads(ctx.tools["personal_agent_status"]({}))["error"]["code"]
        == "invalid_configuration"
    )
