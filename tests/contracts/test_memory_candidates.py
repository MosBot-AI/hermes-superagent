"""Native candidate proposals and explicit operator review; no model/network/listener."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import test_local_conversation_tasks as local
import test_local_memory_commands as memory
from test_local_task_cli import PLUGIN_ID
from test_session_memory_tools import activate, turn

native = local.native
TEXT = "I prefer oat milk in coffee. Please remember this preference."
QUOTE = "I prefer oat milk in coffee."


@pytest.fixture
def host(native, monkeypatch):
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"].update(
        local_memory=True, memory_model_tools=True, memory_candidates=True
    )
    config["memory"] = {"provider": "synthetic-existing-provider"}
    (home / "config.yaml").write_text(json.dumps(config))

    def load(manager):
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        assert loaded.enabled and loaded.error is None
        assert set(loaded.tools_registered) == {
            "personal_agent_status",
            "personal_memory_read",
            "personal_memory_write",
            "personal_memory_candidate",
        }
        assert "personal-memory-tools" in manager._plugin_commands
        assert "pre_llm_call" in loaded.hooks_registered
        assert "post_llm_call" in loaded.hooks_registered

    monkeypatch.setattr(local, "load", load)
    return local.make_host(home, manager)


def before(
    host, text=TEXT, *, sid=None, task_id="native-task", turn_id="native-turn", history=None
):
    from agent.turn_context import _collect_pre_llm_call_context

    return _collect_pre_llm_call_context(
        SimpleNamespace(session_id=sid or host.ref.session_id, model="synthetic", platform="cli"),
        effective_task_id=task_id,
        turn_id=turn_id,
        original_user_message=text,
        messages=[{"role": "user", "content": text}],
        conversation_history=history,
    )


def after(host, *, task_id="native-task", turn_id="native-turn"):
    from hermes_cli.lifecycle import invoke_hook

    return invoke_hook(
        "post_llm_call",
        session_id=host.ref.session_id,
        task_id=task_id,
        turn_id=turn_id,
        user_message=TEXT,
        assistant_response="Synthetic",
        conversation_history=[],
        model="synthetic",
        platform="cli",
    )


def enable(host):
    assert activate(host, "enable-read")["status"] == "ok"
    result = activate(host, "candidate-on")
    assert result["status"] == "ok", result


def propose(host, *, request_id="candidate-one", **changes):
    from model_tools import handle_function_call

    args = {
        "action": "propose",
        "content": "Prefer oat milk in coffee",
        "quote": QUOTE,
        "quote_start": 0,
        "request_id": request_id,
    }
    args.update(changes)
    return json.loads(
        handle_function_call(
            "personal_memory_candidate", args, session_id=host.ref.session_id, task_id="native-task"
        )
    )


def command(host, text):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-memory " + text})
    )
    assert result["type"] == "exec"
    return json.loads(result["output"])


def test_default_no_candidate_capture_or_storage_until_separate_optin(host):
    with turn(host):
        before(host)
        assert propose(host)["status"] == "error"
    assert not memory.database(host.home).exists()
    assert activate(host, "candidate-on")["status"] == "error"
    activate(host, "enable-read")
    with turn(host):
        before(host)
        assert propose(host)["status"] == "error"
    assert not memory.database(host.home).exists()


def test_read_activation_can_propose_but_never_write_canonical_memory(host):
    from test_session_memory_tools import call

    config = (host.home / "config.yaml").read_bytes()
    enable(host)
    with turn(host):
        before(host)
        result = propose(host)
        assert result["status"] == "ok", result
        assert call(host)["data"]["items"] == []
        assert (
            call(
                host,
                {"action": "remember", "content": "unauthorized", "request_id": "bad"},
                write=True,
            )["status"]
            == "error"
        )
        assert propose(host, action="accept")["status"] == "error"
    assert (host.home / "config.yaml").read_bytes() == config
    assert command(host, "list")["data"]["items"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"quote": "not in the current message"},
        {"quote_start": 1},
        {"quote_start": True},
        {"quote_start": -1},
        {"source": "verified_operator"},
        {"session_id": "forged"},
        {"action": "accept"},
        {"action": "discard"},
    ],
)
def test_candidate_model_arguments_cannot_invent_quote_or_authority(host, changes):
    enable(host)
    with turn(host):
        before(host)
        assert propose(host, **changes)["status"] == "error"
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize(
    "change",
    [
        {"platform": "telegram"},
        {"platform": "subagent"},
        {"parent": "parent-session"},
        {"key": "foreign-route"},
        {"sid": "foreign-session"},
        {"profile": "/synthetic/foreign"},
    ],
)
def test_candidate_capture_and_proposal_cannot_cross_native_scope(host, change):
    enable(host)
    with turn(host, **change):
        before(host, sid=change.get("sid"))
        assert propose(host)["status"] == "error"
    assert not memory.database(host.home).exists()


def test_missing_post_and_reused_turn_strings_cannot_reuse_old_turn_object(host):
    enable(host)
    with turn(host):
        before(host)
        assert propose(host)["status"] == "ok"
        # Native collector repeats cannot change this turn's captured statement.
        before(host, "I prefer green tea")
        assert propose(host, request_id="changed", quote="I prefer green tea")["status"] == "error"
    # Deliberately omit post hook. New actual turn has identical identifiers.
    with turn(host):
        assert propose(host, request_id="stale")["status"] == "error"
        before(host, "Only a new unrelated statement")
        assert propose(host, request_id="old-quote")["status"] == "error"


def test_post_hook_closes_capture_without_same_turn_recapture(host):
    enable(host)
    with turn(host):
        before(host)
        after(host)
        activate(host, "candidate-off")
        activate(host, "candidate-on")
        before(host)
        assert propose(host)["status"] == "error"


@pytest.mark.parametrize("renew", ["candidate-off", "enable-read", "enable-write", "disable"])
def test_candidate_revocation_or_activation_renewal_invalidates_captured_text(host, renew):
    enable(host)
    with turn(host):
        before(host)
        assert activate(host, renew)["status"] == "ok"
        if renew == "disable":
            activate(host, "enable-read")
        activate(host, "candidate-on")
        assert propose(host)["status"] == "error"


def pending(host):
    enable(host)
    with turn(host):
        before(host)
        result = propose(host)
        assert result["status"] == "ok", result
    return result["data"]


def test_operator_review_is_required_and_acceptance_replay_never_resurrects_forgotten_memory(host):
    candidate = pending(host)
    cid = candidate["candidate_id"]
    listed = command(host, "candidate-list")["data"]["items"]
    assert [item["candidate_id"] for item in listed] == [cid]
    assert "content" not in listed[0] and "quote" not in listed[0]
    shown = command(host, f"candidate-show {cid}")["data"]
    assert shown["quote"] == QUOTE and shown["quote_start"] == 0
    assert shown["content"] == "Prefer oat milk in coffee"
    assert shown["source"] == "unverified_current_native_input"
    assert command(host, "list")["data"]["items"] == []
    assert command(host, f"candidate-accept {cid} --expected-revision 1")["status"] == "error"
    assert (
        command(host, f"candidate-accept {cid} --expected-revision 2 --keep")["status"] == "error"
    )
    assert command(host, "changes")["data"]["current_watermark"] == 0
    accept = f"candidate-accept {cid} --expected-revision 1 --keep"
    receipt = command(host, accept)
    assert receipt["status"] == "ok", receipt
    assert receipt["data"]["state"] == "accepted" and not receipt["replayed"]
    record = receipt["data"]["record"]
    rid = record["record_id"]
    assert len(command(host, "list")["data"]["items"]) == 1
    assert command(host, "changes")["data"]["current_watermark"] == 1
    terminal = command(host, f"candidate-show {cid}")["data"]
    assert not {"content", "quote", "topic"} & terminal.keys()
    assert (
        command(host, f"forget {rid} --expected-revision 1 --request-id candidate-forget")["status"]
        == "ok"
    )
    host.manager.discover_and_load(force=True)
    retried = command(host, accept)
    assert retried["status"] == "ok" and retried["replayed"]
    assert retried["data"] == receipt["data"]
    assert command(host, "changes")["data"]["current_watermark"] == 2
    from test_memory_process_restart import restart

    fresh = restart(
        host.home,
        [
            {"activate": "status"},
            {"command": accept},
            {"command": "list"},
            {"command": "changes"},
        ],
    )
    assert fresh[0]["data"]["access"] == "disabled"
    assert fresh[0]["data"]["candidate_enabled"] is False
    assert fresh[1]["replayed"] and fresh[1]["data"] == receipt["data"]
    assert fresh[2]["data"]["items"] == []
    assert fresh[3]["data"]["current_watermark"] == 2
    assert command(host, "list")["data"]["items"] == []
    changed = command(
        host, f"candidate-accept {cid} --expected-revision 1 --expires-at 2035-01-01T00:00:00Z"
    )
    assert changed["status"] == "error"


def test_capture_disabled_still_allows_native_review_and_discard_purges_payload(host):
    cid = pending(host)["candidate_id"]
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["memory_candidates"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    with turn(host):
        before(host)
        assert propose(host, request_id="disabled")["status"] == "error"
    assert command(host, f"candidate-show {cid}")["data"]["quote"] == QUOTE
    discarded = command(host, f"candidate-discard {cid} --expected-revision 1")
    assert discarded["status"] == "ok", discarded
    assert discarded["data"]["state"] == "discarded"
    assert command(host, "candidate-list")["data"]["items"] == []
    terminal = command(host, f"candidate-show {cid}")["data"]
    assert not {"content", "quote", "topic"} & terminal.keys()
    assert (
        command(host, f"candidate-accept {cid} --expected-revision 1 --keep")["status"] == "error"
    )
    assert command(host, "list")["data"]["items"] == []


def test_expired_pending_candidate_cannot_be_accepted_and_lazy_purge_erases_payload(
    host, monkeypatch
):
    import importlib

    module = host.manager._plugins[PLUGIN_ID].module
    expiry = importlib.import_module(module.__name__ + ".personal_agent.memory_expiry")
    clock = ["2030-01-01T00:00:00Z"]
    monkeypatch.setattr(expiry, "utc_now", lambda: clock[0])
    cid = pending(host)["candidate_id"]
    clock[0] = "2030-01-09T00:00:00Z"
    purged = command(host, "candidate-purge-expired")
    assert purged["status"] == "ok", purged
    assert purged["data"]["purged"] == 1
    terminal = command(host, f"candidate-show {cid}")["data"]
    assert terminal["state"] == "expired"
    assert not {"content", "quote", "topic"} & terminal.keys()
    assert (
        command(host, f"candidate-accept {cid} --expected-revision 1 --keep")["status"] == "error"
    )
    assert command(host, "list")["data"]["items"] == []


def test_three_per_actual_turn_limit_survives_repeated_hooks_and_discard(host):
    enable(host)
    with turn(host):
        before(host)
        first = propose(host)["data"]
        same = propose(host)
        assert same["status"] == "ok" and same["replayed"]
        assert same["data"] == first
        cid = first["candidate_id"]
        assert command(host, f"candidate-discard {cid} --expected-revision 1")["status"] == "ok"
        for index in (2, 3):
            before(host)
            assert propose(host, request_id=f"candidate-{index}")["status"] == "ok"
        activate(host, "candidate-off")
        activate(host, "candidate-on")
        before(host)
        assert propose(host, request_id="candidate-four")["status"] == "error"
    with turn(host):
        before(host)
        assert propose(host, request_id="next-real-turn")["status"] == "ok"


def test_candidate_capture_refuses_delegated_and_cron_context(host):
    from agent.delegation_context import delegated_child_context
    from gateway.session_context import clear_session_vars, set_session_vars

    enable(host)
    with turn(host), delegated_child_context():
        before(host)
        assert propose(host)["status"] == "error"
    token = set_session_vars(cron_session="1")
    try:
        with turn(host):
            before(host)
            assert propose(host)["status"] == "error"
    finally:
        clear_session_vars(token)
    assert not memory.database(host.home).exists()


def test_unicode_quote_offsets_are_characters_and_do_not_authenticate_claims(host):
    text = "我喜欢茶。请记住偏好。"
    enable(host)
    with turn(host):
        before(host, text)
        bad = propose(host, quote="茶", quote_start=9, request_id="byte-offset")
        assert bad["status"] == "error"
        good = propose(
            host, quote="茶", quote_start=3, content="模型建议：喜欢茶", request_id="char-offset"
        )
        assert good["status"] == "ok", good
    shown = command(host, f"candidate-show {good['data']['candidate_id']}")["data"]
    assert shown["quote"] == "茶" and shown["quote_start"] == 3
    assert shown["source"] == "unverified_current_native_input"
    assert command(host, "list")["data"]["items"] == []


def test_current_input_must_be_plain_original_text_not_history_or_multimodal(host):
    enable(host)
    for current in (None, [{"type": "text", "text": TEXT}], "A completely unrelated current input"):
        with turn(host):
            before(host, current, history=[{"role": "user", "content": TEXT}])
            assert propose(host)["status"] == "error"
    assert not memory.database(host.home).exists()


def test_config_revocation_and_reload_invalidate_candidate_selection(host):
    enable(host)
    with turn(host):
        before(host)
        config = json.loads((host.home / "config.yaml").read_text())
        settings = config["plugins"]["entries"][PLUGIN_ID]["settings"]
        settings["memory_candidates"] = False
        (host.home / "config.yaml").write_text(json.dumps(config))
        assert propose(host)["status"] == "error"
        settings["memory_candidates"] = True
        (host.home / "config.yaml").write_text(json.dumps(config))
        assert propose(host)["status"] == "error"
    enable(host)
    host.manager.discover_and_load(force=True)
    activate(host, "enable-read")
    with turn(host):
        before(host)
        assert propose(host)["status"] == "error"
    assert not memory.database(host.home).exists()


def test_candidate_mode_requires_explicit_read_downgrade_from_write_activation(host):
    from test_session_memory_tools import call

    assert activate(host, "enable-write")["status"] == "ok"
    assert activate(host, "candidate-on")["status"] == "error"
    assert activate(host, "enable-read")["status"] == "ok"
    assert activate(host, "candidate-on")["status"] == "ok"
    with turn(host):
        before(host)
        assert propose(host)["status"] == "ok"
        denied = call(
            host,
            {"action": "remember", "content": "Not approved", "request_id": "write-denied"},
            write=True,
        )
        assert denied["status"] == "error"
    assert command(host, "list")["data"]["items"] == []


def test_off_on_cannot_replace_same_live_turn_source_with_new_claimed_input(host):
    enable(host)
    with turn(host):
        before(host)
        activate(host, "candidate-off")
        activate(host, "candidate-on")
        before(host, "Manufactured replacement quote")
        assert (
            propose(host, quote="Manufactured replacement quote", request_id="replaced")["status"]
            == "error"
        )
    assert not memory.database(host.home).exists()


def test_reused_request_key_on_distinct_actual_turn_is_not_old_candidate_replay(host):
    enable(host)
    with turn(host):
        before(host)
        first = propose(host)
        assert first["status"] == "ok" and not first["replayed"]
    with turn(host):
        before(host)
        second = propose(host)
        assert second["status"] == "ok" and not second["replayed"]
    assert first["data"]["candidate_id"] != second["data"]["candidate_id"]
    assert len(command(host, "candidate-list")["data"]["items"]) == 2
    assert command(host, "list")["data"]["items"] == []
