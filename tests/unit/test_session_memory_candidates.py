"""Exact live-source admission; backend persistence and native host have separate tests."""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from personal_agent import session_memory_candidates as candidates
from personal_agent import session_memory_tools, session_task_tools
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_candidate_tool_contract import normalize_candidate_tool_request
from personal_agent.session_memory_recall import RecallingSessionMemoryTools
from personal_agent.tasks import TaskError


@dataclass
class Turn:
    turn_id: str = "actual-turn"
    task_id: str = "task"
    closed: bool = False
    lease: object = None


@pytest.fixture
def access(tmp_path, monkeypatch):
    config = {
        "mode": "local_tasks",
        "local_conversation": True,
        "local_memory": True,
        "memory_model_tools": True,
        "memory_candidates": True,
    }
    turn = Turn(
        lease=SimpleNamespace(
            released=False,
            session_id="session",
            profile_key=str(tmp_path),
            platform="cli",
            parent_session_id="",
        )
    )
    state = {"turn": turn, "route": "route", "home": tmp_path, "now": 100.0, "commits": []}
    monkeypatch.setattr(session_memory_tools, "current_profile_home", lambda: state["home"])
    monkeypatch.setattr(session_task_tools, "_bound_key", lambda: state["route"])
    monkeypatch.setattr(session_task_tools, "_supported_origin", lambda *args: True)
    monkeypatch.setattr(session_task_tools.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(candidates, "_active_turn", lambda sid: state["turn"])

    @contextmanager
    def native(home, sid, tid):
        current = state["turn"]
        if (
            current is None
            or current.closed
            or current.lease.released
            or current.task_id != tid
            or current.lease.session_id != sid
            or current.lease.profile_key != str(home)
            or current.lease.platform != "cli"
            or current.lease.parent_session_id
            or not state["route"]
        ):
            raise TaskError("no_active_local_turn")
        yield state["route"]

    monkeypatch.setattr(session_task_tools, "native_tool_turn", native)
    instance = candidates.CandidateSessionMemoryTools(bound_home=tmp_path, read_config=config.get)
    receipts = {}

    def execute(operation, payload, sid):
        assert operation == "candidate_propose" and sid == "session"
        key = payload["request_id"]
        if key in receipts:
            if receipts[key][0] != payload:
                raise TaskError("idempotency_conflict")
            return {"data": receipts[key][1], "replayed": True}
        state["commits"].append(deepcopy(payload))
        data = {
            "candidate_id": "synthetic-id",
            "revision": 1,
            "state": "pending",
            "created_at": "2030-01-01T00:00:00Z",
            "expires_at": "2030-01-08T00:00:00Z",
        }
        receipts[key] = deepcopy(payload), data
        return {"data": data, "replayed": False}

    monkeypatch.setattr(instance, "_execute", execute)

    def command(verb, **changes):
        context = {"platform": "local", "session_id": "session", "session_key": "route", **changes}
        return json.loads(instance.command(verb, **context))

    def capture(text="I prefer 茶 without sugar.", **changes):
        context = {
            "session_id": "session",
            "task_id": "task",
            "turn_id": "actual-turn",
            "user_message": text,
            **changes,
        }
        return instance.turn_context(**context)

    def propose(**changes):
        payload = {
            "action": "propose",
            "content": "Tea without sugar",
            "quote": "茶",
            "quote_start": 9,
            "request_id": "first",
            **changes,
        }
        return json.loads(
            instance.run("personal_memory_candidate", payload, session_id="session", task_id="task")
        )

    yield instance, command, capture, propose, config, state
    instance.close()


def enable(command):
    assert command("enable-read")["status"] == "ok"
    assert command("candidate-on")["data"]["candidate_enabled"]


def test_separate_optin_with_read_access_never_enables_canonical_writes(access):
    instance, command, capture, propose, config, state = access
    assert capture() is None and not state["commits"]
    assert command("candidate-on")["error"]["code"] == "session_tools_not_activated"
    config["memory_candidates"] = False
    command("enable-read")
    assert command("candidate-on")["error"]["code"] == "memory_candidates_disabled"
    config["memory_candidates"] = True
    enable(command)
    assert command("status")["data"]["access"] == "read"
    assert not command("status")["data"]["recall_enabled"]
    assert "Review-only" in capture()["context"]
    result = propose()
    assert result["status"] == "ok" and result["data"]["revision"] == 1
    assert "Tea" not in json.dumps(result) and "茶" not in json.dumps(result, ensure_ascii=False)
    denied = json.loads(
        instance.run("personal_memory_write", {}, session_id="session", task_id="task")
    )
    assert denied["error"]["code"] == "session_write_not_activated"
    assert propose()["replayed"] and len(state["commits"]) == 1
    commit = state["commits"][0]
    assert (
        commit["source_digest"] == hashlib.sha256("I prefer 茶 without sugar.".encode()).hexdigest()
    )
    assert commit["request_id"].startswith("candidate-propose.")
    assert len(commit["source_turn"]) == 64 and commit["topic"] == ""


def test_exact_quote_offsets_no_normalization_or_forged_origin(access):
    _, command, capture, propose, _, state = access
    enable(command)
    capture()
    assert propose(quote_start=10)["error"]["code"] == "candidate_quote_mismatch"
    assert propose(quote="茶 ", quote_start=9)["status"] == "ok"
    assert (
        propose(quote="茶", quote_start=9, request_id="second", source_turn="fake")["error"]["code"]
        == "invalid_request"
    )
    assert propose(action="accept")["error"]["code"] == "invalid_request"
    assert len(state["commits"]) == 1


def test_first_capture_cannot_be_changed_or_rearmed_after_post(access):
    instance, command, capture, propose, _, state = access
    enable(command)
    first = capture()
    assert capture() == first
    assert capture("Different source") is None
    assert propose()["error"]["code"] == "candidate_source_unavailable"
    assert capture() is None  # Failed proposal cannot erase the rejection tombstone.
    state["turn"] = Turn(turn_id="next", lease=state["turn"].lease)
    assert capture(turn_id="next")
    instance.clear_turn_context(session_id="session", task_id="task", turn_id="wrong")
    assert propose()["status"] == "ok"
    instance.clear_turn_context(
        session_id="session",
        task_id="task",
        turn_id="next",
        assistant_response="ignored",
        side_question_token="ignored",
    )
    assert propose()["error"]["code"] == "candidate_source_unavailable"
    assert capture(turn_id="next") is None


def test_missing_post_and_reused_task_or_turn_strings_never_reuse_old_source(access):
    _, command, capture, propose, _, state = access
    enable(command)
    capture()
    old = state["turn"]
    state["turn"] = Turn(lease=old.lease)  # Same IDs, different actual native object.
    assert propose()["error"]["code"] == "candidate_source_unavailable"
    assert capture("New user 茶 text")
    assert propose(quote_start=9)["status"] == "ok"
    assert (
        state["commits"][0]["source_digest"]
        != hashlib.sha256("I prefer 茶 without sugar.".encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "text", [None, [], [{"text": "茶"}], {}, "", " ", "x" * 8193, "hello\x00", "hello\u202e"]
)
def test_unbounded_or_nonplain_sources_latch_without_capture(access, text):
    _, command, capture, propose, _, state = access
    enable(command)
    assert capture(text, conversation_history="I prefer 茶", messages="I prefer 茶") is None
    assert capture() is None
    assert propose()["error"]["code"] == "candidate_source_unavailable"
    assert not state["commits"]


@pytest.mark.parametrize(
    "change",
    ["parent", "profile", "session", "task", "closed", "released", "missing", "route", "turn_id"],
)
def test_wrong_live_scope_refused(access, change):
    _, command, capture, propose, _, state = access
    enable(command)
    if change == "parent":
        state["turn"].lease.parent_session_id = "parent"
    elif change == "profile":
        state["turn"].lease.profile_key = "/other"
    elif change == "session":
        state["turn"].lease.session_id = "other"
    elif change == "task":
        state["turn"].task_id = "other"
    elif change == "closed":
        state["turn"].closed = True
    elif change == "released":
        state["turn"].lease.released = True
    elif change == "missing":
        state["turn"] = None
    elif change == "route":
        state["route"] = "other"
    else:
        state["turn"].turn_id = "other"
    assert capture() is None
    assert propose()["status"] == "error" and not state["commits"]


@pytest.mark.parametrize(
    "stop", ["candidate-off", "disable", "enable-read", "enable-write", "expiry", "config", "close"]
)
def test_selection_revocation_invalidates_captured_input(access, stop):
    instance, command, capture, propose, config, state = access
    enable(command)
    capture()
    if stop == "expiry":
        state["now"] += 1800
    elif stop == "config":
        config["memory_candidates"] = False
    elif stop == "close":
        instance.close()
    else:
        command(stop)
    assert propose()["status"] == "error" and not state["commits"]
    assert not instance._sources
    if stop != "close":
        assert not command("status")["data"]["candidate_enabled"]


def test_candidate_and_recall_selection_are_independent_and_parent_context_preserved(
    access, monkeypatch
):
    _, command, capture, _, _, _ = access
    enable(command)
    command("recall-on")
    command("candidate-off")
    assert command("status")["data"]["recall_enabled"]
    command("candidate-on")
    command("recall-off")
    assert command("status")["data"]["candidate_enabled"]
    monkeypatch.setattr(
        RecallingSessionMemoryTools, "turn_context", lambda *a, **k: {"context": "recall"}
    )
    assert capture()["context"].startswith("recall\n\nReview-only")


def test_revocation_waits_for_bounded_admitted_commit(access, monkeypatch):
    instance, command, capture, propose, _, state = access
    enable(command)
    capture()
    entered, release, stopping = threading.Event(), threading.Event(), threading.Event()
    execute = instance._execute

    def held(*args):
        entered.set()
        assert release.wait(5)
        return execute(*args)

    def off():
        stopping.set()
        return command("candidate-off")

    monkeypatch.setattr(instance, "_execute", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = pool.submit(propose)
        assert entered.wait(5)
        stopped = pool.submit(off)
        assert stopping.wait(5)
        try:
            assert not stopped.done()
        finally:
            release.set()
        assert admitted.result(timeout=5)["status"] == "ok"
        assert not stopped.result(timeout=5)["data"]["candidate_enabled"]
    assert propose()["status"] == "error" and len(state["commits"]) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"content": ""},
        {"content": "x" * 2049},
        {"quote": ""},
        {"quote": "x" * 1025},
        {"topic": "x" * 129},
        {"topic": "line\nbreak"},
        {"quote_start": True},
        {"quote_start": -1},
        {"quote_start": 8193},
        {"quote_start": 1.0},
        {"request_id": "中文"},
        {"request_id": "x" * 129},
        {"request_id": "has space"},
        {"action": "discard"},
        {"origin": "owner"},
        {"source_digest": "forged"},
    ],
)
def test_pure_contract_rejects_oversize_or_forged_fields(fields):
    args = {
        "action": "propose",
        "content": "Draft",
        "quote": "tea",
        "quote_start": 0,
        "request_id": "key",
        **fields,
    }
    with pytest.raises(MemoryError):
        normalize_candidate_tool_request(args)


def test_write_activation_requires_explicit_downgrade_for_candidate_mode(access):
    _, command, capture, propose, _, state = access
    command("enable-write")
    assert command("candidate-on")["error"]["code"] == "candidate_requires_read_only_activation"
    assert command("status")["data"]["access"] == "write"
    assert not command("status")["data"]["candidate_enabled"]
    assert capture() is None and propose()["status"] == "error"
    command("enable-read")
    command("candidate-on")
    assert capture() and propose()["status"] == "ok"
    command("enable-write")
    assert propose(request_id="second")["status"] == "error"
    assert len(state["commits"]) == 1


def test_nonce_and_first_source_digest_survive_selection_and_activation_toggles(access):
    _, command, capture, propose, _, state = access
    enable(command)
    capture()
    assert propose()["status"] == "ok"
    original = state["commits"][0]
    command("candidate-off")
    command("candidate-on")
    capture()
    assert propose()["replayed"]
    command("enable-read")
    command("candidate-on")
    capture()
    assert propose(request_id="second")["status"] == "ok"
    assert state["commits"][1]["source_turn"] == original["source_turn"]
    command("candidate-off")
    command("candidate-on")
    assert capture("different evidence 茶") is None
    assert propose(request_id="third")["status"] == "error"
    # A genuinely new live object gets a new durable turn scope, even with reused IDs.
    old = state["turn"]
    state["turn"] = Turn(lease=old.lease)
    capture()
    assert propose()["status"] == "ok"
    assert state["commits"][-1]["source_turn"] != original["source_turn"]
    assert state["commits"][-1]["request_id"] != original["request_id"]


def test_post_closure_survives_selection_toggles(access):
    instance, command, capture, propose, _, _ = access
    enable(command)
    capture()
    command("candidate-off")
    instance.clear_turn_context(session_id="session", task_id="task", turn_id="actual-turn")
    command("candidate-on")
    assert capture() is None and propose()["status"] == "error"


def test_source_and_quote_limits_use_exact_python_character_offsets(access):
    _, command, capture, propose, _, state = access
    enable(command)
    assert capture("😀" + "x" * 8190 + "茶")
    assert propose(quote_start=8191)["status"] == "ok"
    assert (
        propose(quote_start=8192, request_id="outside")["error"]["code"]
        == "candidate_quote_mismatch"
    )
    assert len(state["commits"]) == 1


def test_new_instance_never_recovers_old_source_or_selection(access):
    instance, command, capture, _, config, state = access
    enable(command)
    capture()
    instance.close()
    restarted = candidates.CandidateSessionMemoryTools(
        bound_home=state["home"], read_config=config.get
    )
    for verb in ("enable-read", "candidate-on"):
        assert (
            json.loads(
                restarted.command(verb, platform="local", session_id="session", session_key="route")
            )["status"]
            == "ok"
        )
    result = json.loads(
        restarted.run(
            "personal_memory_candidate",
            {
                "action": "propose",
                "content": "Tea",
                "quote": "茶",
                "quote_start": 9,
                "request_id": "after-restart",
            },
            session_id="session",
            task_id="task",
        )
    )
    assert result["error"]["code"] == "candidate_source_unavailable"
    assert not restarted._sources and not state["commits"]
    restarted.close()
