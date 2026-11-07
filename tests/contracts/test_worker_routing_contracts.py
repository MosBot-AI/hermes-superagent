"""Pinned Hermes routing seams, with a synthetic test-only provider.

Discovery, schema, provider dispatch and route resolver are real. Only the
credential resolver is replaced by a recorder, before any credential reads.
No child agent, model, profile switch, HTTP/IPC transport or real account runs.
The production plugin does not register this provider or enable routing.
"""

import copy
import json
from types import SimpleNamespace

import pytest
from test_native_plugin import home, manager  # noqa: F401

PLUGIN_ID = "routing-contract-fixture"
BACKEND = "routing-contract-fixture"
SOURCE = """
from agent.delegation_provider import DelegationProvider, DelegationRouteError

class FixtureProvider(DelegationProvider):
    name = "routing-contract-fixture"
    available = True
    calls = []
    def is_available(self):
        return self.available
    def task_parameters(self, config):
        return {"work_class": {"type": "string", "enum": ["simple", "code", "review"]}}
    def description(self, config):
        return "Synthetic offline contract fixture."
    def route_task(self, task, config):
        self.calls.append(dict(task))
        if task.get("goal") == "refuse":
            raise DelegationRouteError("fixture refusal")
        if task.get("goal") == "raise":
            raise RuntimeError("fixture failure")
        return dict(self.settings(config)["route"])

provider = FixtureProvider()
def register(ctx):
    ctx.register_delegation_provider(provider)
"""


@pytest.fixture
def routing(home, manager, monkeypatch):  # noqa: F811
    from agent.delegation_registry import get_active_provider
    from tools import delegate_tool

    plugin = home / "plugins" / PLUGIN_ID
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text(
        "name: routing-contract-fixture\nversion: 0.1.0\ndescription: Offline test only\n"
    )
    (plugin / "__init__.py").write_text(SOURCE)
    config = {
        "plugins": {"enabled": [PLUGIN_ID]},
        "delegation": {
            "backend": BACKEND,
            "backends": {
                BACKEND: {
                    "route": {
                        "provider": "synthetic-provider",
                        "model": "synthetic-model",
                        "reasoning_effort": "high",
                        "fallback_providers": [],
                        "label": "fixture",
                    }
                }
            },
        },
    }
    (home / "config.yaml").write_text(json.dumps(config))
    before = (home / "config.yaml").read_bytes()
    manager.discover_and_load()
    assert manager._plugins[PLUGIN_ID].error is None
    provider = get_active_provider(config["delegation"])
    provider.calls = []
    resolved = []

    def resolve(route, parent):
        resolved.append(copy.deepcopy(route))
        return {"model": route.get("model"), "provider": route.get("provider")}

    monkeypatch.setattr(delegate_tool, "_resolve_delegation_credentials", resolve)
    yield SimpleNamespace(
        home=home,
        manager=manager,
        provider=provider,
        config=config["delegation"],
        resolved=resolved,
        parent=SimpleNamespace(),
    )
    assert (home / "config.yaml").read_bytes() == before


def run(routing, tasks, *, config=None, parent=None):
    from tools.delegate_tool_routes import resolve_task_routes

    return resolve_task_routes(tasks, config or routing.config, parent or routing.parent)


def test_native_registration_deterministic_schema_and_unload(routing):
    from agent.delegation_registry import get_active_provider
    from tools.delegate_tool_routes import schema_extension

    first = schema_extension(routing.config)
    assert first == schema_extension(routing.config)
    assert first[0]["work_class"]["enum"] == ["simple", "code", "review"]
    first[0]["work_class"]["enum"].append("injected")
    assert "injected" not in schema_extension(routing.config)[0]["work_class"]["enum"]
    assert get_active_provider(routing.config) is routing.provider
    routing.manager.unload()
    # Disable rediscovery explicitly to verify the unloaded registration cannot run.
    (routing.home / "config.yaml").write_text(json.dumps({"plugins": {"disabled": [PLUGIN_ID]}}))
    try:
        routes, error = run(routing, [{"goal": "synthetic"}])
        assert routes == [] and error
        assert not routing.resolved
    finally:
        (routing.home / "config.yaml").write_text(
            json.dumps(
                {
                    "plugins": {"enabled": [PLUGIN_ID]},
                    "delegation": routing.config,
                }
            )
        )


def test_payload_is_not_trusted_context_and_extra_route_keys_are_dropped(routing):
    route = routing.config["backends"][BACKEND]["route"]
    route.update(budget_token="untrusted", policy_revision=99, deadline=1, owner_id="forged")
    tasks = [
        {
            "goal": "Synthetic goal",
            "context": "Untrusted text",
            "work_class": "code",
            "images": ["synthetic-image"],
            "role": "researcher",
            "output_schema": {"type": "object"},
            "provider": "forged-provider",
            "model": "forged-model",
            "index": 999,
        }
    ]
    routes, error = run(routing, tasks)
    assert error is None and routes[0].error is None
    assert routing.provider.calls == [
        {
            "goal": "Synthetic goal",
            "context": "Untrusted text",
            "index": 0,
            "work_class": "code",
        }
    ]
    assert set(routing.resolved[0]) == {
        "provider",
        "model",
        "reasoning_effort",
        "fallback_providers",
        "label",
    }
    assert routes[0].report() == {"backend": BACKEND, "label": "fixture"}
    assert "model" not in routes[0].report()  # not a wire/usage observation


@pytest.mark.parametrize(
    "extra",
    [
        {"work_class": "unbounded"},
        {"owner_id": "forged"},
        {"budget": 999},
        {"authorized": True},
        {"effort_hint": "ultra"},
    ],
)
def test_invalid_and_undeclared_model_parameters_refuse_before_provider(routing, extra):
    routes, error = run(routing, [{"goal": "synthetic", **extra}])
    assert error is None and routes[0].error
    assert routing.provider.calls == [] and routing.resolved == []
    refused = routes[0].refused_entry(0)
    assert refused["api_calls"] == 0
    assert refused["route"]["refused"]


@pytest.mark.parametrize("goal", ["refuse", "raise"])
def test_route_refusal_or_exception_does_not_cancel_valid_sibling(routing, goal):
    routes, error = run(routing, [{"goal": goal}, {"goal": "valid", "work_class": "review"}])
    assert error is None and routes[0].error and routes[1].error is None
    assert len(routing.resolved) == 1


def test_explicit_empty_fallback_blocks_inheritance_and_omission_does_not(routing):
    routing.config["fallback_providers"] = [{"provider": "must-not-run"}]
    routes, error = run(routing, [{"goal": "synthetic"}])
    assert error is None and routes[0].routing_cfg["fallback_providers"] == []
    del routing.config["backends"][BACKEND]["route"]["fallback_providers"]
    routes, error = run(routing, [{"goal": "synthetic"}])
    assert error is None
    assert routes[0].routing_cfg["fallback_providers"] == [{"provider": "must-not-run"}]
    # This records config only. No fallback or model request was executed.


def test_unavailable_and_unknown_backend_fail_closed(routing):
    routing.provider.available = False
    routes, error = run(routing, [{"goal": "synthetic"}])
    assert routes == [] and "unavailable" in error
    routes, error = run(routing, [{"goal": "synthetic"}], config={"backend": "absent-fixture"})
    assert routes == [] and "not installed" in error
    assert not routing.resolved


def test_unknown_effort_refuses_before_credential_resolution(routing):
    routing.config["backends"][BACKEND]["route"]["reasoning_effort"] = "invented-level"
    routes, error = run(routing, [{"goal": "synthetic"}])
    assert error is None and "unknown reasoning_effort" in routes[0].error
    assert not routing.resolved


def test_session_backend_pin_wins_over_changed_saved_config(routing):
    parent = SimpleNamespace(_delegation_backend=BACKEND)
    config = {**routing.config, "backend": "absent-fixture"}
    routes, error = run(routing, [{"goal": "synthetic"}], config=config, parent=parent)
    assert error is None and routes[0].backend == BACKEND and routes[0].error is None


def test_internal_route_bypasses_provider(routing):
    from tools.delegate_tool_routes import route_for_config

    result = route_for_config({"model": "internal-fixture-model"}, routing.parent)
    assert result.creds["model"] == "internal-fixture-model"
    assert routing.provider.calls == []


def test_public_lifecycle_empty_allowlist_does_not_mean_no_tools(monkeypatch):
    from agent.subagent_lifecycle import SubagentLifecycleError, SubagentLifecycleService
    from tools import delegate_tool

    parent = SimpleNamespace(session_id="synthetic-parent", enabled_toolsets=["terminal"])
    service = SubagentLifecycleService(lambda: parent)
    observed = []

    def stop_before_construction(**kwargs):
        observed.append(kwargs)
        raise RuntimeError("synthetic construction boundary")

    monkeypatch.setattr(delegate_tool, "_load_config", lambda: {})
    monkeypatch.setattr(
        delegate_tool, "_resolve_delegation_credentials", lambda *args: {"model": "synthetic"}
    )
    monkeypatch.setattr(delegate_tool, "_credential_overrides", lambda *args: {})
    monkeypatch.setattr(
        delegate_tool, "_build_child_preserving_parent_tools", stop_before_construction
    )
    with pytest.raises(RuntimeError, match="synthetic construction boundary"):
        service.launch({"goal": "Synthetic", "allowed_toolsets": []})
    assert observed[0]["toolsets"] is None
    with pytest.raises(SubagentLifecycleError, match="timeout is not supported"):
        service.launch({"goal": "Synthetic", "timeout_seconds": 1})
    assert len(observed) == 1


def test_native_child_narrowing_can_still_inherit_mcp_and_orchestrator_tools(monkeypatch):
    from tools import delegate_tool_toolsets

    parent = SimpleNamespace(enabled_toolsets=["terminal", "mcp-synthetic"], disabled_toolsets=[])
    monkeypatch.setattr(delegate_tool_toolsets, "_get_inherit_mcp_toolsets", lambda: True)
    tools, _ = delegate_tool_toolsets._resolve_child_toolsets(parent, ["terminal"], "leaf")
    assert "mcp-synthetic" in tools
    monkeypatch.setattr(delegate_tool_toolsets, "_get_inherit_mcp_toolsets", lambda: False)
    tools, _ = delegate_tool_toolsets._resolve_child_toolsets(parent, ["terminal"], "orchestrator")
    assert "delegation" in tools and "mcp-synthetic" not in tools
