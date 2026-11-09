"""Pinned manager lifecycle and real cron/delegation constructor call sites.

Constructor interception stops before AIAgent initialization/model traffic. These
are wiring contracts, not full-agent runs or durable-memory implementations.
"""

import json
from types import SimpleNamespace

import pytest
import test_native_plugin
from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider
from test_native_memory_provider import scoped

home = test_native_plugin.home


class LifecycleRecorder(MemoryProvider):
    def __init__(self, name, events, *, fail=()):
        self.name_value = name
        self.events = events
        self.fail = fail
        self.session = None

    @property
    def name(self):
        return self.name_value

    def is_available(self):
        return True

    def get_tool_schemas(self):
        return []

    def record(self, hook, *args, **kwargs):
        self.events.append((self.name, hook, self.session, args, kwargs))
        if hook in self.fail:
            raise RuntimeError("synthetic " + hook + " failure")

    def initialize(self, session_id, **kwargs):
        self.session = session_id
        self.record("initialize", **kwargs)

    def sync_turn(self, user_content, assistant_content, **kwargs):
        self.record("sync", user_content, assistant_content, **kwargs)

    def on_session_end(self, messages):
        self.record("end", messages)

    def on_session_switch(self, new_session_id, **kwargs):
        self.record("switch", new_session_id, **kwargs)
        self.session = new_session_id

    def shutdown(self):
        self.record("shutdown")


@pytest.mark.parametrize("fail", [(), ("end",), ("switch",), ("shutdown",)])
def test_public_manager_serializes_sync_end_switch_and_reverse_shutdown(home, fail):
    events = []
    with scoped(home):
        manager = MemoryManager()
        manager.add_provider(LifecycleRecorder("builtin", events))
        manager.add_provider(LifecycleRecorder("contract_recorder", events, fail=fail))
        manager.initialize_all(
            session_id="old", hermes_home=str(home), platform="cli", agent_context="primary"
        )
        messages = [{"role": "user", "content": "synthetic old conversation"}]
        manager.sync_all("synthetic input", "synthetic output", session_id="old", messages=messages)
        manager.commit_session_boundary_async(
            messages, new_session_id="new", parent_session_id="old", reason="contract_reset"
        )
        manager.shutdown_all()
        assert manager.shutdown_drain_state["status"] == "drained"
    external = [e for e in events if e[0] == "contract_recorder"]
    assert [e[1] for e in external] == ["initialize", "sync", "end", "switch", "shutdown"]
    assert external[0][4] == {
        "hermes_home": str(home),
        "platform": "cli",
        "agent_context": "primary",
    }
    assert external[1][2:4] == ("old", ("synthetic input", "synthetic output"))
    assert external[1][4]["session_id"] == "old"
    assert external[1][4]["messages"] == messages
    assert external[2][2:4] == ("old", (messages,))
    assert external[3][2:] == (
        "old",
        ("new",),
        {"parent_session_id": "old", "reset": True, "reason": "contract_reset"},
    )
    assert external[-1][2] == ("old" if "switch" in fail else "new")
    assert [(e[0], e[1]) for e in events[-2:]] == [
        ("contract_recorder", "shutdown"),
        ("builtin", "shutdown"),
    ]


def test_public_session_switch_forwards_branch_rewind_and_ignores_empty_id(home):
    events = []
    with scoped(home):
        manager = MemoryManager()
        manager.add_provider(LifecycleRecorder("contract_recorder", events))
        manager.initialize_all(session_id="parent", hermes_home=str(home), platform="cli")
        try:
            manager.on_session_switch("", reset=True)
            assert len(events) == 1
            manager.on_session_switch("child", parent_session_id="parent", rewound=True)
            assert events[-1][3:] == (
                ("child",),
                {"parent_session_id": "parent", "reset": False, "rewound": True},
            )
        finally:
            manager.shutdown_all()


def test_actual_cron_constructor_keeps_memory_but_disables_background_review(home):
    from cron.scheduler import _construct_cron_agent, _CronAgentSetup

    calls = []

    def capture(**kwargs):
        calls.append(kwargs)
        return "synthetic constructor boundary"

    with scoped(home):
        result = _construct_cron_agent(
            capture,
            {},
            {},
            _CronAgentSetup(model="synthetic", runtime={}),
            workdir=None,
            session_id="cron-contract",
            session_db=None,
        )
    assert result == "synthetic constructor boundary"
    assert len(calls) == 1
    assert calls[0]["skip_memory"] is False
    assert calls[0]["skip_background_review"] is True
    assert calls[0]["platform"] == "cron"
    assert calls[0]["session_id"] == "cron-contract"


@pytest.mark.parametrize("required", [False, True])
def test_actual_delegation_constructor_memory_policy_tracks_required_checkpoint(
    home, monkeypatch, required
):
    import run_agent
    from tools import delegate_tool

    (home / "config.yaml").write_text(
        json.dumps(
            {
                "compression": {"checkpoint_required": required},
                "delegation": {"backend": "default"},
            }
        )
    )
    calls = []

    class ConstructorBoundary(Exception):
        pass

    def capture(**kwargs):
        calls.append(kwargs)
        raise ConstructorBoundary

    monkeypatch.setattr(run_agent, "AIAgent", capture)
    # Credential/runtime resolution is a synthetic boundary: no provider login,
    # network, or model client is needed to observe the real constructor call.
    monkeypatch.setattr(
        delegate_tool,
        "_resolve_child_runtime",
        lambda *a, **k: {"model": "synthetic", "provider": "synthetic", "base_url": None},
    )
    parent = SimpleNamespace(
        session_id="parent-contract",
        model="synthetic",
        base_url=None,
        enabled_toolsets=[],
        disabled_toolsets=[],
        session_db=None,
    )
    with scoped(home), pytest.raises(ConstructorBoundary):
        delegate_tool._build_child_agent(0, "synthetic goal", None, [], None, 1, 1, parent)
    assert len(calls) == 1
    assert calls[0]["skip_memory"] is (not required)
    assert calls[0]["memory_agent_context"] == "subagent"
    assert calls[0]["platform"] == "subagent"
    assert calls[0]["parent_session_id"] == "parent-contract"


@pytest.mark.parametrize("interrupted", [True, False])
def test_actual_turn_sync_boundary_skips_interrupted_provider_writes_and_prefetch(
    home, interrupted
):
    from run_agent import AIAgent

    class TurnRecorder(LifecycleRecorder):
        def queue_prefetch(self, query, *, session_id=""):
            self.record("prefetch", query, session_id=session_id)

    events = []
    messages = [
        {"role": "user", "content": "synthetic project status"},
        {"role": "assistant", "content": "synthetic partial or complete answer"},
    ]
    author = {"id": "synthetic-author", "name": "Synthetic", "is_bot": True}
    with scoped(home):
        manager = MemoryManager()
        manager.add_provider(TurnRecorder("contract_recorder", events))
        manager.initialize_all(session_id="turn-contract", hermes_home=str(home), platform="cli")
        # Invoke the actual consumer method on its minimal state boundary, with
        # a real manager/executor/provider. No constructor or model run is claimed.
        state = SimpleNamespace(
            _memory_manager=manager, session_id="turn-contract", _turn_author=author
        )
        try:
            AIAgent._sync_external_memory_for_turn(
                state,
                original_user_message=messages[0]["content"],
                final_response=messages[1]["content"],
                interrupted=interrupted,
                messages=messages,
            )
        finally:
            manager.shutdown_all()
        assert manager.shutdown_drain_state["status"] == "drained"
    work = [event for event in events if event[1] in {"sync", "prefetch"}]
    if interrupted:
        assert work == []
    else:
        assert [event[1] for event in work] == ["sync", "prefetch"]
        assert work[0][2:] == (
            "turn-contract",
            (messages[0]["content"], messages[1]["content"]),
            {"session_id": "turn-contract", "messages": messages, "turn_author": author},
        )
        assert work[1][2:] == (
            "turn-contract",
            (messages[0]["content"],),
            {"session_id": "turn-contract"},
        )
