"""Real native task dependency gates and fresh focus, with no worker/model calls."""

from uuid import uuid4

import pytest
from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native
from test_local_task_cli import task as cli_task
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host
from test_task_focus import collect


def seed(host):
    result = command(host, "plan --project Demo --task First --task Second --request-id plan")
    assert result["status"] == "ok", result
    return result["data"]["items"]


def deps(host, target, needs, *, revision=1, key="deps"):
    flags = " ".join("--needs " + item["id"] for item in needs) if needs else "--clear"
    return command(
        host,
        f"dependencies {target['id']} {flags} --expected-revision {revision} --request-id {key}",
    )


def mutation(host, task, op, *, revision=1, key=None, extra=""):
    return command(
        host,
        f"{op} {task['id']} --expected-revision {revision} "
        f"--request-id {key or op} --note explicit {extra}",
    )


def show(host, item):
    return command(host, "show " + item["id"])["data"]


def test_native_plan_dependency_completion_ready_focus_and_retry(host):
    from agent.turn_context import compose_user_api_content

    first, second = seed(host)
    config = (host.home / "config.yaml").read_bytes()
    bound = deps(host, second, [first])
    assert bound["status"] == "ok", bound
    assert bound["data"]["revision"] == 2
    assert bound["data"]["dependencies"] == [
        {"task_id": first["id"], "revision": 1, "state": "captured"}
    ]
    assert bound["data"]["unsatisfied_dependency_count"] == 1
    assert not bound["data"]["dependencies_satisfied"]
    assert (
        mutation(host, second, "progress", revision=2, extra="--work-status in_progress")["status"]
        == "error"
    )
    assert mutation(host, second, "complete", revision=2)["status"] == "error"
    assert show(host, second)["revision"] == 2
    assert [x["id"] for x in command(host, "ready")["data"]["items"]] == [first["id"]]
    assert mutation(host, first, "complete", key="first-done")["status"] == "ok"
    ready = command(host, "ready")["data"]
    assert ready["total_eligible"] == 1
    assert [x["id"] for x in ready["items"]] == [second["id"]]
    assert show(host, second)["revision"] == 2  # Derived readiness is not an owned-field revision.
    activate(host, "enable-read")
    activate(host, "focus " + second["id"])
    before = database(host.home).read_bytes()
    with turn(host):
        context = collect(host)
        assert '"dependencies_satisfied": true' in context
        assert '"unsatisfied_dependency_count": 0' in context
        assert second["id"] in compose_user_api_content("Next?", "", context)
    assert database(host.home).read_bytes() == before
    done = mutation(host, second, "complete", revision=2, key="second-done")
    assert done["status"] == "ok", done
    host.manager.discover_and_load(force=True)
    retry = mutation(host, second, "complete", revision=2, key="second-done")
    assert retry["replayed"] and retry["data"] == done["data"]
    historical = deps(host, second, [first])
    assert historical["replayed"] and historical["data"] == bound["data"]
    assert command(host, "ready")["data"]["total_eligible"] == 0
    assert show(host, second)["state"] == "done"
    assert (host.home / "config.yaml").read_bytes() == config


def test_cancelled_prerequisite_blocks_until_explicit_edge_removal(host):
    first, second = seed(host)
    assert deps(host, second, [first])["status"] == "ok"
    assert mutation(host, first, "cancel")["status"] == "ok"
    assert not show(host, second)["dependencies_satisfied"]
    assert command(host, "ready")["data"]["items"] == []
    assert mutation(host, second, "complete", revision=2)["status"] == "error"
    assert deps(host, second, [], revision=2, key="clear")["status"] == "ok"
    assert mutation(host, second, "complete", revision=3)["status"] == "ok"


@pytest.mark.parametrize("which", ["dependent", "prerequisite"])
def test_project_change_on_either_endpoint_refused(host, which):
    first, second = seed(host)
    deps(host, second, [first])
    target, revision = (second, 2) if which == "dependent" else (first, 1)
    result = command(
        host,
        f"update {target['id']} --project Other --expected-revision {revision} --request-id move",
    )
    assert result["status"] == "error"
    assert show(host, target)["project"] == "Demo"
    assert show(host, target)["revision"] == revision


@pytest.mark.parametrize("kind", ["self", "missing", "cross_project", "unassigned", "cycle"])
def test_invalid_graph_change_is_atomic(host, kind):
    first, second = seed(host)
    if kind == "self":
        needs = [second]
    elif kind == "missing":
        needs = [{"id": str(uuid4())}]
    elif kind in ("cross_project", "unassigned"):
        flag = "--project Other" if kind == "cross_project" else ""
        needs = [command(host, f"add Third {flag} --request-id third")["data"]]
    else:
        assert deps(host, first, [second], key="reverse")["status"] == "ok"
        needs = [first]
    before = show(host, second)
    assert deps(host, second, needs)["status"] == "error"
    assert show(host, second) == before


def test_in_progress_cannot_gain_unsatisfied_dependency(host):
    first, second = seed(host)
    assert mutation(host, second, "progress", extra="--work-status in_progress")["status"] == "ok"
    assert deps(host, second, [first], revision=2)["status"] == "error"
    assert show(host, second)["dependencies"] == []
    assert mutation(host, first, "complete")["status"] == "ok"
    assert deps(host, second, [first], revision=2)["status"] == "ok"
    assert command(host, "ready")["data"]["items"] == []  # No implicit progress rewrite.


def test_model_dependency_action_requires_current_write_grant(host):
    first, second = seed(host)
    args = {
        "action": "set_dependencies",
        "task_id": second["id"],
        "expected_revision": 1,
        "dependency_ids": [first["id"]],
        "request_id": "model-edge",
    }
    activate(host, "enable-read")
    with turn(host):
        assert call(host, args, write=True)["status"] == "error"
    activate(host)
    with turn(host):
        assert call(host, args, write=True)["status"] == "ok"
        premature = {
            "action": "complete",
            "task_id": second["id"],
            "expected_revision": 2,
            "request_id": "premature",
            "note": "claimed done",
        }
        assert call(host, premature, write=True)["status"] == "error"
        assert [x["id"] for x in call(host, {"action": "ready"})["data"]["items"]] == [first["id"]]
    activate(host, "disable")
    with turn(host):
        assert call(host, args, write=True)["status"] == "error"


@pytest.mark.parametrize(
    "change",
    [
        {"platform": "subagent"},
        {"parent": "parent"},
        {"key": "foreign"},
        {"sid": "foreign"},
        {"profile": "/synthetic/foreign"},
    ],
)
def test_model_edge_mutation_cannot_cross_live_scope(host, change):
    first, second = seed(host)
    activate(host)
    with turn(host, **change):
        assert (
            call(
                host,
                {
                    "action": "set_dependencies",
                    "task_id": second["id"],
                    "expected_revision": 1,
                    "dependency_ids": [first["id"]],
                    "request_id": "wrong-scope",
                },
                write=True,
            )["status"]
            == "error"
        )
    assert show(host, second)["dependencies"] == []


def test_cli_ready_pagination_and_dependency_clear(host, capsys):
    first, second = seed(host)
    cli = host.manager._cli_commands["personal-agent"]
    code, edge = cli_task(
        cli,
        capsys,
        "dependencies",
        second["id"],
        "--needs",
        first["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "cli-edge",
    )
    assert code == 0 and edge["status"] == "ok"
    code, cleared = cli_task(
        cli,
        capsys,
        "dependencies",
        second["id"],
        "--clear",
        "--expected-revision",
        "2",
        "--request-id",
        "cli-clear",
    )
    assert code == 0 and cleared["status"] == "ok"
    page = command(host, "ready --limit 1")["data"]
    assert page["total_eligible"] == 2 and page["items"][0]["id"] == first["id"]
    next_page = command(host, "ready --limit 1 --after " + page["next_cursor"])["data"]
    assert next_page["items"][0]["id"] == second["id"]
    assert next_page["total_eligible"] == 2


@pytest.mark.parametrize(
    "kind", ["duplicate", "over_limit", "not_list", "bool_revision", "unknown_field"]
)
def test_model_dependency_schema_rejects_malformed_without_mutation(host, kind):
    first, second = seed(host)
    args = {
        "action": "set_dependencies",
        "task_id": second["id"],
        "expected_revision": 1,
        "dependency_ids": [first["id"]],
        "request_id": "malformed",
    }
    if kind == "duplicate":
        args["dependency_ids"] *= 2
    elif kind == "over_limit":
        args["dependency_ids"] = [str(uuid4()) for _ in range(21)]
    elif kind == "not_list":
        args["dependency_ids"] = {"untrusted": first["id"]}
    elif kind == "bool_revision":
        args["expected_revision"] = True
    else:
        args["dispatch"] = True
    activate(host)
    with turn(host):
        assert call(host, args, write=True)["status"] == "error"
    assert show(host, second)["revision"] == 1


def test_sorted_retry_terminal_refusal_and_review_counts(host):
    first, second = seed(host)
    third = command(host, "add Third --project Demo --request-id third")["data"]
    original = deps(host, third, [second, first])
    retry = deps(host, third, [first, second])
    assert retry["replayed"] and retry["data"] == original["data"]
    assert deps(host, third, [], key="deps")["status"] == "error"
    assert command(host, "review --on 2030-01-01")["data"]["dependency_counts"] == {
        "satisfied": 2,
        "blocked": 1,
    }
    assert mutation(host, third, "cancel", revision=2)["status"] == "ok"
    assert deps(host, third, [], revision=3, key="terminal-clear")["status"] == "error"
    assert show(host, third)["revision"] == 3
    assert command(host, "review --on 2030-01-01")["data"]["dependency_counts"] == {
        "satisfied": 2,
        "blocked": 0,
    }


def test_dependency_tool_excludes_delegated_and_cron_context(host):
    from agent.delegation_context import delegated_child_context
    from gateway.session_context import clear_session_vars, set_session_vars

    first, second = seed(host)
    activate(host)
    args = {
        "action": "set_dependencies",
        "task_id": second["id"],
        "expected_revision": 1,
        "dependency_ids": [first["id"]],
        "request_id": "child",
    }
    with turn(host), delegated_child_context():
        assert call(host, args, write=True)["status"] == "error"
    tokens = set_session_vars(cron_session="1")
    try:
        with turn(host):
            assert call(host, args, write=True)["status"] == "error"
    finally:
        clear_session_vars(tokens)
    assert show(host, second)["dependencies"] == []


def test_actual_fresh_process_cli_reads_and_replays_without_dispatch(host):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    import hermes_cli

    first, second = seed(host)
    original = deps(host, second, [first])
    environment = {
        "PATH": os.defpath,
        "HOME": str(host.home.parent / "os-home"),
        "HERMES_HOME": str(host.home),
        "HERMES_RUNTIME_DIR": str(host.home.parent / "runtime"),
        "HERMES_BUNDLED_PLUGINS": str(host.home.parent / "empty-bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }
    bootstrap = """
import socket, sys
def deny(*args, **kwargs):
    raise AssertionError('Dependency restart must not use network/listeners')
socket.create_connection = deny
for name in ('connect', 'connect_ex', 'bind', 'listen', 'sendto', 'sendmsg'):
    if hasattr(socket.socket, name): setattr(socket.socket, name, deny)
sys.argv = ['hermes', 'personal-agent', 'tasks', *sys.argv[1:]]
from hermes_cli.main import main
main()
"""

    def run(*args):
        result = subprocess.run(
            [sys.executable, "-c", bootstrap, *args],
            cwd=Path(hermes_cli.__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    result = run(
        "dependencies",
        second["id"],
        "--needs",
        first["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "deps",
    )
    assert result["replayed"] and result["data"] == original["data"]
    assert run("show", second["id"])["data"]["unsatisfied_dependency_count"] == 1
    assert [x["id"] for x in run("ready")["data"]["items"]] == [first["id"]]


def test_host_normalizes_bare_uuid_before_plugin_schema_validation(host):
    first, second = seed(host)
    activate(host)
    with turn(host):
        result = call(
            host,
            {
                "action": "set_dependencies",
                "task_id": second["id"],
                "expected_revision": 1,
                "dependency_ids": first["id"],
                "request_id": "normalized",
            },
            write=True,
        )
    assert result["status"] == "ok", result
    assert [item["task_id"] for item in result["data"]["dependencies"]] == [first["id"]]
