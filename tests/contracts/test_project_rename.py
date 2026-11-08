"""Official native command/CLI fixture, without network transport or model calls."""

from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import host as host
from test_local_conversation_tasks import native as native
from test_local_task_cli import entry as load_cli
from test_local_task_cli import native as _cli_fixture
from test_local_task_cli import task

native_cli = _cli_fixture


def test_native_dependency_rename_and_reload_replay(host):
    plan = command(host, "plan --project Demo --task First --task Second --request-id plan")
    first, second = plan["data"]["items"]
    command(
        host,
        f"dependencies {second['id']} --needs {first['id']} --expected-revision 1 --request-id dep",
    )
    command(host, f"done {first['id']} --expected-revision 1 --note accepted --request-id done")
    before = database(host.home).read_bytes()
    preview = command(host, "project-rename-preview --project Demo --new-project New")
    assert preview["status"] == "ok", preview
    assert preview["data"]["state_counts"] == {"captured": 1, "done": 1, "cancelled": 0}
    assert database(host.home).read_bytes() == before
    op = (
        "rename-project --project Demo --new-project New --expected-snapshot "
        + preview["data"]["snapshot"]
        + " --request-id rename"
    )
    changed = command(host, op)
    assert changed["status"] == "ok", changed
    task_state = command(host, "show " + second["id"])["data"]
    assert task_state["project"] == "New" and task_state["dependencies_satisfied"]
    assert task_state["dependencies"][0]["task_id"] == first["id"]
    host.manager.discover_and_load(force=True)
    replay = command(host, op)
    assert replay["replayed"] and replay["data"] == changed["data"]


def test_cli_preview_apply_and_stale_edit(native_cli, capsys):
    home, manager = native_cli
    cli = load_cli(manager)
    _, capture = task(
        cli, capsys, "capture", "--title", "Synthetic", "--project", "old", "--request-id", "c"
    )
    code, preview = task(
        cli, capsys, "project-rename-preview", "--project", "old", "--new-project", "new"
    )
    assert code == 0
    code, result = task(
        cli,
        capsys,
        "rename-project",
        "--project",
        "old",
        "--new-project",
        "new",
        "--expected-snapshot",
        preview["data"]["snapshot"],
        "--request-id",
        "r",
    )
    assert code == 0 and result["data"]["task_count"] == 1
    code, stale = task(
        cli,
        capsys,
        "update",
        capture["data"]["id"],
        "--title",
        "changed",
        "--expected-revision",
        "1",
        "--request-id",
        "stale",
    )
    assert code == 1 and stale["error"]["code"] == "revision_conflict"
