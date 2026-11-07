"""Real native command -> admitted hook -> API-bound user context, with no model/network."""

import json
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host


def collect(host, *, sid=None, task_id="native-task"):
    from agent.turn_context import _collect_pre_llm_call_context

    return _collect_pre_llm_call_context(
        SimpleNamespace(session_id=sid or host.ref.session_id, model="synthetic", platform="cli"),
        effective_task_id=task_id,
        turn_id="native-turn",
        original_user_message="What should I do next?",
        messages=[{"role": "user", "content": "What should I do next?"}],
        conversation_history=None,
    )


def focus(host):
    task = command(host, 'add "Focused native task" --project Demo --request-id seed')["data"]
    activate(host, "enable-read")
    result = activate(host, "focus " + task["id"])
    assert result["status"] == "ok", result
    return task


def test_focus_reaches_native_api_message_and_refreshes_on_next_turn(host):
    from agent.turn_context import compose_user_api_content

    task = focus(host)
    before = database(host.home).read_bytes()
    with turn(host):
        snapshot = collect(host)
    assert "Focused native task" in snapshot and task["id"] in snapshot
    assert '"revision": 1' in snapshot
    assert (
        compose_user_api_content("Help with this", "", snapshot) == "Help with this\n\n" + snapshot
    )
    assert database(host.home).read_bytes() == before
    command(
        host, f'update {task["id"]} --expected-revision 1 --title "Changed focus" --request-id edit'
    )
    with turn(host):
        latest = collect(host)
    assert "Changed focus" in latest and "Focused native task" not in latest
    assert '"revision": 2' in latest
    assert activate(host, "status")["data"]["focus_task_id"] == task["id"]
    activate(host, "clear-focus")
    with turn(host):
        assert collect(host) == ""
        assert call(host)["status"] == "ok"
    # Previously composed API content is not rewritten by clearing focus.
    assert "Focused native task" in snapshot


@pytest.mark.parametrize(
    "change",
    [
        {"platform": "telegram"},
        {"platform": "subagent"},
        {"parent": "parent-session"},
        {"key": ""},
        {"key": "another-route"},
        {"sid": "another-session"},
        {"profile": "/synthetic/foreign"},
    ],
)
def test_focus_hook_does_not_cross_native_turn_boundaries(host, change):
    focus(host)
    before = database(host.home).read_bytes()
    with turn(host, **change):
        assert collect(host, sid=change.get("sid")) == ""
    assert database(host.home).read_bytes() == before


def test_focus_without_live_turn_wrong_task_and_copied_env_denied(host, monkeypatch):
    focus(host)
    monkeypatch.setenv("HERMES_SESSION_KEY", host.live.route)
    monkeypatch.setenv("HERMES_SESSION_ID", host.ref.session_id)
    assert collect(host) == ""
    with turn(host):
        assert collect(host, task_id="wrong-turn") == ""


def test_focus_excludes_delegated_and_cron_context(host):
    from agent.delegation_context import delegated_child_context
    from gateway.session_context import clear_session_vars, set_session_vars

    focus(host)
    with turn(host), delegated_child_context():
        assert collect(host) == ""
    tokens = set_session_vars(cron_session="1")
    try:
        with turn(host):
            assert collect(host) == ""
    finally:
        clear_session_vars(tokens)


def test_focus_unload_and_reload_clear_activation_and_retained_hook(host):
    focus(host)
    callback = host.manager._plugin_commands["personal-tools"]["handler"].__self__.turn_context
    host.manager.discover_and_load(force=True)
    activate(host, "enable-read")
    with turn(host):
        assert collect(host) == ""
        assert callback(session_id=host.ref.session_id, task_id="native-task") is None
    assert activate(host, "status")["data"]["focus_task_id"] is None


def test_focus_hook_registration_remains_idle_without_selection(host):
    assert host.manager._plugins["hermes-personal-agent"].hooks_registered == ["pre_llm_call"]
    activate(host, "enable-read")
    with turn(host):
        assert collect(host) == ""
    assert not database(host.home).exists()
    assert activate(host, "focus invalid")["error"]["code"] == "invalid_request"
    assert not database(host.home).exists()


def test_focus_disablement_rechecks_current_config_before_storage(host):
    focus(host)
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"]["hermes-personal-agent"]["settings"]["local_model_tools"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    with turn(host):
        assert collect(host) == ""


@pytest.mark.parametrize("multimodal", [False, True])
def test_native_sidecar_and_wire_replay_preserve_prior_focus(host, multimodal):
    from agent.turn_context import (
        _append_multimodal_context,
        _stamp_api_content_sidecar,
        build_api_messages,
    )

    task = focus(host)
    agent = SimpleNamespace(
        session_id=host.ref.session_id,
        _current_turn_timestamp=time.time(),
        ephemeral_system_prompt="",
        _copy_reasoning_content_for_api=lambda *args: None,
        _should_sanitize_tool_calls=lambda: False,
    )
    content = [{"type": "text", "text": "Help with this"}] if multimodal else "Help with this"
    messages = [{"role": "user", "content": content}]
    with turn(host):
        snapshot = collect(host)
    if multimodal:
        _append_multimodal_context(agent, messages[0], "", snapshot, preflight_compressed=False)
    else:
        _stamp_api_content_sidecar(agent, messages, 0, "", snapshot, preflight_compressed=False)

    def wire(index, fresh_context):
        return build_api_messages(
            agent,
            messages,
            current_turn_user_idx=index,
            ext_prefetch_cache="",
            plugin_user_context=fresh_context,
            moa_config=None,
            active_system_prompt="Stable system",
        )

    frozen = deepcopy(messages)
    first, system = wire(0, snapshot)
    assert system == "Stable system"
    assert "Focused native task" in json.dumps(first)
    # Repeated requests reuse exactly the sidecar/durable part, even if a caller
    # accidentally supplies changed context within the same turn.
    repeated, _ = wire(0, "CHANGED WITHIN TURN")
    assert repeated == first and messages == frozen
    assert all("api_content" not in item for item in repeated)
    command(
        host,
        f'update {task["id"]} --expected-revision 1 --title "New turn title" --request-id edit',
    )
    with turn(host):
        latest = collect(host)
    messages.extend(
        [{"role": "assistant", "content": "Plan"}, {"role": "user", "content": "Next?"}]
    )
    _stamp_api_content_sidecar(agent, messages, 2, "", latest, preflight_compressed=False)
    second, _ = wire(2, latest)
    assert second[0:2] == first
    assert "New turn title" in second[-1]["content"]
    activate(host, "clear-focus")
    with turn(host):
        cleared = collect(host)
    assert cleared == ""
    messages.extend(
        [{"role": "assistant", "content": "Updated plan"}, {"role": "user", "content": "Unrelated"}]
    )
    after_clear, _ = wire(4, cleared)
    assert after_clear[:-2] == second
    assert after_clear[-1] == {"role": "user", "content": "Unrelated"}
