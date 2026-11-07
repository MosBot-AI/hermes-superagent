"""Offline deterministic local conversation commands and fail-closed routing."""

import json
import sqlite3
from contextlib import contextmanager
from enum import Enum
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from personal_agent import conversation_tasks as commands
from personal_agent.tasks import TaskError, TaskStore


@pytest.fixture
def local(monkeypatch, tmp_path):
    config = {"mode": "local_tasks", "local_conversation": True}
    calls = []
    monkeypatch.setattr(commands, "current_profile_home", lambda: tmp_path)

    @contextmanager
    def store(home):
        assert home == tmp_path
        calls.append(home)
        connection = sqlite3.connect(tmp_path / "synthetic.sqlite3", isolation_level=None)
        try:
            tasks = TaskStore(connection)
            tasks.initialize()
            yield tasks
        finally:
            connection.close()

    monkeypatch.setattr(commands, "open_task_store", store)

    def invoke(raw, **context):
        defaults = {
            "platform": "cli",
            "source": None,
            "session_id": "synthetic-session-1",
            "session_key": "synthetic-session-1",
        }
        return json.loads(
            commands.run_conversation_tasks(
                raw, read_config=config.get, bound_home=tmp_path, **{**defaults, **context}
            )
        )

    return invoke, config, calls


def test_capture_survives_reopen_and_explicit_key_replays_without_duplicate(local, capsys):
    invoke, _, calls = local
    command = 'add "Synthetic title" --details "Two words" --project "Demo project"'
    result = invoke(command)
    assert result["status"] == "ok"
    UUID(result["request_id"])
    assert result["data"]["title"] == "Synthetic title"
    assert result["data"]["revision"] == 1
    assert result["data"]["project"] == "Demo project"
    replay = invoke(command + " --request-id " + result["request_id"])
    assert replay["replayed"] is True
    assert replay["data"] == result["data"]
    listing = invoke("list")
    assert len(listing["data"]["items"]) == 1
    assert len(calls) == 3
    assert capsys.readouterr() == ("", "")


def test_read_project_agenda_search_and_mutation_workflow(local):
    invoke, _, _ = local
    captured = invoke('capture --title "Synthetic work" --due-date 2030-01-01 --project Demo')
    task = captured["data"]
    task_id = task["id"]
    assert invoke(f"show {task_id}")["data"] == task
    assert invoke('search "Synthetic"')["data"]["items"][0]["id"] == task_id
    assert invoke("agenda --on 2030-01-02 --project Demo")["data"]["items"][0]["id"] == task_id
    assert invoke("projects")["data"]["items"][0]["project"] == "Demo"
    updated = invoke(f'update {task_id} --expected-revision 1 --title "Changed" --clear-project')
    assert updated["data"]["revision"] == 2
    assert updated["data"]["project"] is None
    stale = invoke(f'done {task_id} --expected-revision 1 --note "Finished"')
    assert stale["error"]["code"] == "revision_conflict"
    done = invoke(f'done {task_id} --expected-revision 2 --note "Finished"')
    assert done["data"]["state"] == "done"
    assert done["data"]["revision"] == 3
    assert invoke("list")["data"]["items"] == []
    assert len(invoke("list --state all")["data"]["items"]) == 1
    history = invoke(f"history {task_id} --limit 2")["data"]
    assert history["current_revision"] == 3 and history["current_state"] == "done"
    assert [item["operation"] for item in history["items"]] == ["capture", "update"]
    last = invoke(f"history {task_id} --after-revision {history['next_cursor']}")["data"]
    assert [item["operation"] for item in last["items"]] == ["complete"]


def test_cancel_and_idempotency_conflict(local):
    invoke, _, _ = local
    result = invoke('add "Synthetic" --request-id explicit-key')
    conflict = invoke('add "Different" --request-id explicit-key')
    assert conflict["error"]["code"] == "idempotency_conflict"
    cancel = f'cancel {result["data"]["id"]} --expected-revision 1 --note "No longer needed"'
    cancelled = invoke(cancel + " --request-id cancel-key")
    assert cancelled["data"]["state"] == "cancelled"
    assert invoke(cancel + " --request-id cancel-key")["replayed"] is True


@pytest.mark.parametrize(
    "context",
    [
        {"platform": "telegram"},
        {"platform": "CLI"},
        {"platform": None},
        {"platform": "http"},
        {"source": {}},
        {"source": "cli"},
        {"session_id": ""},
        {"session_key": "different"},
        {"session_id": None},
        {"session_id": "x" * 129, "session_key": "x" * 129},
        {"session_id": "a\nb", "session_key": "a\nb"},
        {"session_id": "../other", "session_key": "../other"},
    ],
)
def test_origin_denial_precedes_config_parse_and_storage(monkeypatch, tmp_path, context, capsys):
    def forbidden(*args):
        pytest.fail("Unsupported origin reached private work")

    monkeypatch.setattr(commands, "_parse", forbidden)
    monkeypatch.setattr(commands, "current_profile_home", forbidden)
    monkeypatch.setattr(commands, "open_task_store", forbidden)
    defaults = {"platform": "cli", "source": None, "session_id": "a", "session_key": "a"}
    result = commands.run_conversation_tasks(
        object(), read_config=forbidden, bound_home=tmp_path, **{**defaults, **context}
    )
    assert json.loads(result)["error"]["code"] == "unsupported_origin"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"local_conversation": False}, "local_conversation_disabled"),
        ({"local_conversation": "true"}, "invalid_configuration"),
        ({"local_conversation": 1}, "invalid_configuration"),
        ({"local_conversation": None}, "invalid_configuration"),
        ({"mode": "read_only", "local_conversation": False}, "local_conversation_disabled"),
        ({"mode": {}}, "invalid_configuration"),
        ({"mode": "read_only", "local_conversation": True}, "invalid_configuration"),
    ],
)
def test_runtime_gate_rechecked_before_parse(local, monkeypatch, changes, code):
    invoke, config, calls = local
    assert invoke("list")["status"] == "ok"
    config.update(changes)
    monkeypatch.setattr(commands, "_parse", lambda _: pytest.fail("Gate must precede parse"))
    assert invoke('add "private"')["error"]["code"] == code
    assert len(calls) == 1


def test_profile_change_precedes_config_read(local, monkeypatch, tmp_path):
    invoke, _, calls = local
    monkeypatch.setattr(commands, "current_profile_home", lambda: tmp_path / "different")
    assert invoke("list")["error"]["code"] == "profile_context_changed"
    assert calls == []


def test_deleted_profile_does_not_read_config(monkeypatch, tmp_path):
    def forbidden(*args):
        pytest.fail("Missing profile reached host configuration")

    result = commands.run_conversation_tasks(
        "list",
        read_config=forbidden,
        bound_home=tmp_path / "absent",
        platform="cli",
        session_id="a",
        session_key="a",
    )
    assert json.loads(result)["error"]["code"] == "profile_context_changed"


@pytest.mark.parametrize(
    "raw",
    [
        'add "unterminated',
        "list --state private",
        "list --limit NaN",
        "list --home /private",
        "x" * (commands.MAX_RAW_ARGUMENTS + 1),
        "list " + "x " * commands.MAX_TOKENS,
        "list\x00",
        None,
        {},
        'capture --title ""',
        'add "x" --request-id "invalid/key"',
        "show invalid",
        "history invalid",
        f"history {uuid4()} --after-revision -1",
        f"history {uuid4()} --after-revision 1.5",
        f"history {uuid4()} --limit 101",
        'capture --tit "x"',
        "list --help",
        "list --limit -1",
        f'update {uuid4()} --title "private"',
        f"done {uuid4()} --expected-revision 1",
        f'cancel {uuid4()} --note "private"',
    ],
)
def test_bad_arguments_are_redacted_and_never_open_store(local, raw, capsys):
    invoke, _, calls = local
    output = invoke(raw)
    assert output["error"]["code"] == "invalid_request"
    assert output["data"] is None
    assert output["request_id"] is None
    assert calls == []
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("raw", ["", "help", "--help", "-h"])
def test_help_is_local_and_never_opens_storage(local, raw):
    invoke, _, calls = local
    output = invoke(raw)
    assert "POSIX" in output["data"]["help"]
    assert "No automatic retries" in output["data"]["help"]
    assert calls == []


@pytest.mark.parametrize(
    "failure,code",
    [
        (RuntimeError("secret /private/path"), "local_tasks_unavailable"),
        (TaskError("storage_busy", retryable=True), "storage_busy"),
    ],
)
def test_unknown_outcome_keeps_request_id_without_retry_or_error_leak(
    local, monkeypatch, failure, code, capsys
):
    invoke, _, _ = local
    attempts = []

    @contextmanager
    def failed(home):
        attempts.append(home)
        raise failure
        yield  # pragma: no cover

    monkeypatch.setattr(commands, "open_task_store", failed)
    result = invoke('add "Synthetic" --request-id retain-this-key')
    assert result["request_id"] == "retain-this-key"
    assert result["error"]["code"] == code
    assert "secret" not in json.dumps(result)
    assert len(attempts) == 1
    assert capsys.readouterr() == ("", "")


class _Platform(Enum):
    LOCAL = "local"
    TELEGRAM = "telegram"


def _local_source(**changes):
    # Public projection only: no private host pointer or owner credential.
    fields = {
        "platform": _Platform.LOCAL,
        "chat_type": "dm",
        "chat_id": "original-chat-id",
        "user_id": "opaque-principal:operator",
        "is_bot": False,
        "delivered_via_upstream_relay": False,
        "profile_route_rejected": False,
        "thread_id": None,
        "parent_chat_id": None,
        "scope_id": None,
        "guild_id": None,
        "detached_route": None,
        "prospective_thread_id": None,
        "profile": "synthetic-profile",
    }
    return SimpleNamespace(**{**fields, **changes})


@pytest.mark.parametrize("platform", ["local", _Platform.LOCAL])
def test_native_local_projection_accepts_different_chat_and_session_lineage(local, platform):
    invoke, _, calls = local
    context = {
        "platform": "local",
        "source": _local_source(platform=platform),
        "session_id": "fresh-session",
        "session_key": "agent:local:dm:original-chat-id",
    }
    result = invoke('add "Native local task" --request-id native-key', **context)
    assert result["status"] == "ok"
    assert result["scope"] == "trusted_local_conversation"
    assert result["data"]["title"] == "Native local task"
    assert invoke("list", **context)["data"]["items"][0]["id"] == result["data"]["id"]
    assert len(calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"platform": "telegram"},
        {"platform": _Platform.TELEGRAM},
        {"platform": None},
        {"chat_type": "group"},
        {"chat_type": "thread"},
        {"chat_type": None},
        {"is_bot": True},
        {"is_bot": None},
        {"is_bot": 0},
        {"delivered_via_upstream_relay": True},
        {"delivered_via_upstream_relay": None},
        {"profile_route_rejected": True},
        {"profile_route_rejected": None},
        {"thread_id": "thread"},
        {"parent_chat_id": "parent"},
        {"scope_id": "scope"},
        {"guild_id": "guild"},
        {"detached_route": "detached"},
        {"prospective_thread_id": "next"},
        {"chat_id": ""},
        {"chat_id": None},
        {"chat_id": "x" * 257},
        {"chat_id": "a\nb"},
        {"user_id": ""},
        {"user_id": None},
        {"user_id": 42},
        {"user_id": " "},
        {"user_id": "x" * 257},
        {"user_id": "a\nb"},
    ],
)
def test_native_local_rejects_unsupported_source_before_private_work(
    local, monkeypatch, change, capsys
):
    invoke, _, calls = local
    monkeypatch.setattr(commands, "_parse", lambda _: pytest.fail("Unexpected private parse"))
    monkeypatch.setattr(commands, "current_profile_home", lambda: pytest.fail("Unexpected profile"))
    result = invoke(object(), platform="local", source=_local_source(**change))
    assert result["error"]["code"] == "unsupported_origin"
    assert calls == []
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("key", [None, "", " ", "x" * 1025, "a\nb", "a\x00b"])
def test_native_local_requires_bounded_session_key(local, key):
    invoke, _, calls = local
    result = invoke("list", platform="local", source=_local_source(), session_key=key)
    assert result["error"]["code"] == "unsupported_origin"
    assert calls == []


def test_native_local_gate_change_and_profile_change_still_deny(local, monkeypatch, tmp_path):
    invoke, config, calls = local
    context = {"platform": "local", "source": _local_source()}
    config["local_conversation"] = False
    assert invoke("list", **context)["error"]["code"] == "local_conversation_disabled"
    config["local_conversation"] = True
    monkeypatch.setattr(commands, "current_profile_home", lambda: tmp_path / "other")
    assert invoke("list", **context)["error"]["code"] == "profile_context_changed"
    assert calls == []


def test_native_local_missing_or_malformed_source_fails_closed(local):
    invoke, _, calls = local

    class BrokenProjection:
        @property
        def platform(self):
            raise RuntimeError("private transport internals")

    for source in (None, {}, SimpleNamespace(), BrokenProjection()):
        output = invoke("list", platform="local", source=source)
        assert output["error"]["code"] == "unsupported_origin"
        assert "private" not in json.dumps(output)
    assert calls == []


def test_dash_prefixed_title_uses_equals_option_syntax(local):
    invoke, _, _ = local
    result = invoke("capture --title=-draft --request-id dash-title")
    assert result["status"] == "ok"
    assert result["data"]["title"] == "-draft"
