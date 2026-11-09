"""Real pinned LOCAL operator admission, command and CLI date-only workflow."""

from dataclasses import replace

import pytest
from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import host as host
from test_local_conversation_tasks import native as native
from test_local_task_cli import entry as load_cli
from test_local_task_cli import native as _cli_fixture
from test_local_task_cli import task
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as _model_host
from test_task_workbench import human

native_cli = _cli_fixture
model_host = _model_host


def test_native_full_review_apply_reload_and_readable_receipt(host):
    t = command(host, 'add "中文任务" --project Demo --due-date 2028-02-28 --request-id seed')[
        "data"
    ]
    command(host, 'add "No date" --project Demo --request-id undated')
    before = database(host.home).read_bytes()
    p = command(host, "project-reschedule-preview --project Demo --days 2")["data"]
    assert p["affected_count"] == 1 and p["excluded_counts"]["undated"] == 1
    assert database(host.home).read_bytes() == before
    text = human(host, "project-reschedule-preview --project Demo --days 2")
    assert t["id"] in text and "2028-02-28 -> 2028-03-01" in text
    op = (
        "reschedule-project --project Demo --days 2 "
        f"--expected-snapshot {p['snapshot']} --request-id shift"
    )
    assert "rescheduled" in human(host, op)
    assert command(host, f"show {t['id']}")["data"]["due_date"] == "2028-03-01"
    host.manager.discover_and_load(force=True)
    assert command(host, op)["replayed"]
    assert "not shifted again" in human(host, op)


def test_cli_preview_and_apply(native_cli, capsys):
    home, manager = native_cli
    cli = load_cli(manager)
    _, captured = task(
        cli,
        capsys,
        "capture",
        "--title",
        "CLI",
        "--project",
        "p",
        "--due-date",
        "2028-03-01",
        "--request-id",
        "seed",
    )
    code, p = task(cli, capsys, "project-reschedule-preview", "--project", "p", "--days", "-1")
    assert code == 0
    code, result = task(
        cli,
        capsys,
        "reschedule-project",
        "--project",
        "p",
        "--days",
        "-1",
        "--expected-snapshot",
        p["data"]["snapshot"],
        "--request-id",
        "shift",
    )
    assert code == 0 and result["data"]["items"][0]["new_due_date"] == "2028-02-29"
    _, current = task(cli, capsys, "show", captured["data"]["id"])
    assert current["data"]["revision"] == 2


@pytest.mark.parametrize("operation", ["project-reschedule-preview", "reschedule-project"])
def test_foreign_actor_refused_before_storage(host, operation):
    from hermes_state_runtime import RuntimeStoreError

    host.connection.actor = replace(host.connection.actor, subject="foreign")
    with pytest.raises(RuntimeStoreError):
        command(host, operation)
    assert not database(host.home).exists()


def test_revoked_control_after_preview_cannot_apply_or_replay(host):
    from hermes_state_runtime import RuntimeStoreError

    command(host, 'add "Task" --project p --due-date 2028-01-01 --request-id seed')
    p = command(host, "project-reschedule-preview --project p --days 2")["data"]
    op = (
        "reschedule-project --project p --days 2 "
        f"--expected-snapshot {p['snapshot']} --request-id shift"
    )
    actor = host.connection.actor
    host.connection.actor = replace(
        actor, capabilities=frozenset({"session:read", "session:respond"})
    )
    before = database(host.home).read_bytes()
    with pytest.raises(RuntimeStoreError):
        command(host, op)
    assert database(host.home).read_bytes() == before
    host.connection.actor = actor
    assert command(host, op)["status"] == "ok"
    host.connection.actor = replace(actor, subject="revoked")
    with pytest.raises(RuntimeStoreError):
        command(host, op)


def test_model_cannot_request_project_rescheduling(model_host):
    activate(model_host)
    with turn(model_host):
        for action in ("project_reschedule_preview", "reschedule_project"):
            result = call(model_host, {"action": action}, write=True)
            assert result["error"]["code"] == "invalid_request"
    assert not database(model_host.home).exists()
