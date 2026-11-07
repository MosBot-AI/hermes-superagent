"""Real LOCAL review/accept commands on isolated native boards, never execution."""

import json

import pytest
from test_kanban_handoff import board as board
from test_kanban_handoff import handoff, inspect_db
from test_kanban_handoff import handoff_host as handoff_host
from test_kanban_handoff import native as native
from test_local_conversation_tasks import command
from test_local_task_cli import PLUGIN_ID
from test_native_task_sync import confirmed, module, snapshot

RAW = "SYNTHETIC_PRIVATE_NATIVE_RESULT_未验证"


def stage(path, *, status="done", result=RAW, run=None):
    with inspect_db(path) as conn:
        conn.execute(
            "UPDATE tasks SET status=?,result=?,completed_at=1794000000,current_run_id=?",
            (status, result, run),
        )


def review(host, source, receipt, revision=1):
    return handoff(
        host, f"review {receipt['id']} --task {source['id']} --expected-revision {revision}"
    )


def accept(host, source, receipt, digest, *, revision=1, key="accept-one"):
    return handoff(
        host,
        f"accept-review {receipt['id']} --task {source['id']} --expected-revision {revision} "
        f"--expected-digest {digest} --note 'Operator inspected work' --request-id {key}",
    )


def test_review_accept_private_receipt_no_native_mutation_and_no_model_action(handoff_host, board):
    host = handoff_host
    source, receipt = confirmed(host)
    stage(board[1])
    before = snapshot(board[1])
    shown = review(host, source, receipt)
    assert shown["status"] == "ok", shown
    preview = shown["data"]
    assert preview["can_accept"] and preview["evidence"]["native"]["result"] == RAW
    assert "untrusted" in preview["notice"].lower()
    assert command(host, "show " + source["id"])["data"] == source
    first = accept(host, source, receipt, preview["review_digest"])
    assert first["status"] == "ok" and not first["replayed"], first
    task = first["data"]["task"]
    assert task["state"] == "done" and task["revision"] == 2
    assert task["work_status"] == source["work_status"]
    assert task["resolution_note"] == "Operator inspected work"
    assert RAW not in json.dumps(first, ensure_ascii=False)
    assert snapshot(board[1]) == before
    with module(host, "task_cli").open_task_store(host.home) as store:
        assert RAW not in "\n".join(store._connection.iterdump())
    contract = module(host, "task_tool_contract")
    assert not {"review", "accept-review", "native_review_accept"} & set(contract._WRITE_ACTIONS)
    # Existing generic review is unrelated; no native evidence read tool is added.
    assert "native_result_review" not in contract._READ_ACTIONS
    assert RAW not in module(host, "task_focus").task_context(task)
    host.manager.discover_and_load(force=True)
    retry = accept(host, source, receipt, preview["review_digest"])
    assert retry["replayed"] and retry["data"] == first["data"]


def test_exact_retry_before_optin_ledger_and_native_access(handoff_host, board, monkeypatch):
    host = handoff_host
    source, receipt = confirmed(host)
    stage(board[1])
    digest = review(host, source, receipt)["data"]["review_digest"]
    first = accept(host, source, receipt, digest)
    assert first["status"] == "ok", first
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["kanban_handoff"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    ledger = host.home / "plugin-data" / PLUGIN_ID / "kanban-handoff" / "receipts.sqlite3"
    ledger.rename(ledger.with_suffix(".gone"))
    board[1].rename(board[1].with_suffix(".gone"))

    def forbidden(*args, **kwargs):
        raise AssertionError("Historical retry attempted native/ledger access")

    monkeypatch.setattr(module(host, "kanban_handoff"), "open_handoff_store", forbidden)
    monkeypatch.setattr(module(host, "native_kanban"), "observe_result", forbidden)
    retry = accept(host, source, receipt, digest)
    assert retry["replayed"] and retry["data"] == first["data"]
    assert not ledger.exists() and not board[1].exists()


@pytest.mark.parametrize("case", ["running", "archived", "empty", "large", "active"])
def test_unavailable_result_cannot_complete(handoff_host, board, case):
    host = handoff_host
    source, receipt = confirmed(host)
    stage(
        board[1],
        status=case if case in {"running", "archived"} else "done",
        result=" " if case == "empty" else "x" * 8001 if case == "large" else RAW,
        run=1 if case == "active" else None,
    )
    before = snapshot(board[1])
    shown = review(host, source, receipt)
    assert shown["status"] == "ok", shown
    assert not shown["data"]["can_accept"]
    assert shown["data"]["evidence"]["native"]["result"] is None
    denied = accept(host, source, receipt, shown["data"]["review_digest"])
    assert denied["status"] == "error", denied
    assert command(host, "show " + source["id"])["data"] == source
    assert snapshot(board[1]) == before


@pytest.mark.parametrize("change", ["result", "identity", "event_gc", "key"])
def test_changed_native_evidence_never_accepts_old_digest(handoff_host, board, change):
    host = handoff_host
    source, receipt = confirmed(host)
    stage(board[1])
    digest = review(host, source, receipt)["data"]["review_digest"]
    with inspect_db(board[1]) as conn:
        conn.execute(
            {
                "result": "UPDATE tasks SET result='changed'",
                "identity": "UPDATE tasks SET created_at=created_at+1",
                "event_gc": "DELETE FROM task_events WHERE kind='created'",
                "key": "UPDATE tasks SET idempotency_key='other'",
            }[change]
        )
    before = snapshot(board[1])
    denied = accept(host, source, receipt, digest)
    assert denied["status"] == "error", denied
    fresh = review(host, source, receipt)
    assert fresh["status"] == "ok", fresh
    if change != "result":
        assert fresh["data"]["evidence"]["native"]["result"] is None
        assert not fresh["data"]["can_accept"]
    assert command(host, "show " + source["id"])["data"] == source
    assert snapshot(board[1]) == before


def test_local_revision_source_and_parser_guards(handoff_host, board):
    host = handoff_host
    source, receipt = confirmed(host)
    stage(board[1])
    digest = review(host, source, receipt)["data"]["review_digest"]
    assert review(host, source, receipt, revision=2)["status"] == "error"
    other = command(host, 'add "Other" --request-id other')["data"]
    assert review(host, other, receipt)["status"] == "error"
    for suffix in [
        "",
        " --expected-digest bad --note note --request-id key",
        " --expected-digest " + digest + " --request-id key",
    ]:
        response = handoff(
            host,
            f"accept-review {receipt['id']} --task {source['id']} --expected-revision 1" + suffix,
        )
        assert response["status"] == "error", response
    assert command(host, "show " + source["id"])["data"] == source


@pytest.mark.parametrize("change", ["disabled", "board", "base_disabled"])
def test_current_configuration_gates_fresh_review_and_accept(handoff_host, board, change):
    host = handoff_host
    source, receipt = confirmed(host)
    stage(board[1])
    digest = review(host, source, receipt)["data"]["review_digest"]
    config = json.loads((host.home / "config.yaml").read_text())
    settings = config["plugins"]["entries"][PLUGIN_ID]["settings"]
    settings.update(
        {
            "disabled": {"kanban_handoff": False},
            "board": {"kanban_handoff_board": "different"},
            "base_disabled": {"local_conversation": False},
        }[change]
    )
    (host.home / "config.yaml").write_text(json.dumps(config))
    before = snapshot(board[1])
    assert review(host, source, receipt)["status"] == "error"
    assert accept(host, source, receipt, digest)["status"] == "error"
    assert snapshot(board[1]) == before


def test_dependencies_block_manual_accept_until_explicitly_done(handoff_host, board):
    host = handoff_host
    source, receipt = confirmed(host)
    stage(board[1])
    prerequisite = command(host, 'add "Gate" --project PrivateProject --request-id gate')["data"]
    changed = command(
        host,
        f"dependencies {source['id']} --needs {prerequisite['id']} "
        "--expected-revision 1 --request-id deps",
    )
    assert changed["status"] == "ok", changed
    preview = review(host, source, receipt, revision=2)
    assert preview["status"] == "ok" and not preview["data"]["can_accept"], preview
    assert (
        accept(host, source, receipt, preview["data"]["review_digest"], revision=2)["status"]
        == "error"
    )
    done = command(
        host,
        f"complete {prerequisite['id']} --expected-revision 1 "
        "--note inspected --request-id gate-done",
    )
    assert done["status"] == "ok", done
    preview = review(host, source, receipt, revision=2)
    assert preview["data"]["can_accept"]
    result = accept(host, source, receipt, preview["data"]["review_digest"], revision=2)
    assert result["status"] == "ok" and result["data"]["task"]["state"] == "done", result


def test_integrated_breakdown_then_explicit_native_review_accept(handoff_host, board):
    """Merged features share CAS/dependency gates, not automatic completion."""
    host = handoff_host
    source, receipt = confirmed(host)
    prerequisite = command(
        host, 'add "Existing gate" --project PrivateProject --request-id integration-gate'
    )["data"]
    linked = command(
        host,
        f"dependencies {source['id']} --needs {prerequisite['id']} "
        "--expected-revision 1 --request-id integration-deps",
    )
    assert linked["status"] == "ok", linked
    breakdown = command(
        host,
        f"breakdown {source['id']} --expected-revision 2 "
        '--tasks-json \'[{"title":"Draft"},{"title":"Check","depends_on":[1]}]\' '
        "--request-id integration-breakdown",
    )
    assert breakdown["status"] == "ok", breakdown
    parent = breakdown["data"]["parent"]
    steps = breakdown["data"]["items"]
    assert parent["revision"] == 3 and parent["state"] == "captured"
    assert breakdown["data"]["inherited_dependency_ids"] == [prerequisite["id"]]
    stage(board[1])
    native_before = snapshot(board[1])
    preview = review(host, source, receipt, revision=3)
    assert preview["status"] == "ok" and not preview["data"]["can_accept"], preview
    with module(host, "task_cli").open_task_store(host.home) as store:
        local_before = list(store._connection.iterdump())
    rejected = accept(
        host,
        source,
        receipt,
        preview["data"]["review_digest"],
        revision=3,
        key="integration-accept",
    )
    assert rejected["status"] == "error", rejected
    assert rejected["error"]["code"] == "dependencies_unsatisfied"
    with module(host, "task_cli").open_task_store(host.home) as store:
        assert list(store._connection.iterdump()) == local_before
    assert snapshot(board[1]) == native_before
    for index, task in enumerate([prerequisite, *steps]):
        completed = command(
            host,
            f"complete {task['id']} --expected-revision 1 --note inspected "
            f"--request-id integration-complete-{index}",
        )
        assert completed["status"] == "ok", completed
        current = command(host, "show " + source["id"])["data"]
        assert current["state"] == "captured" and current["revision"] == 3
    preview = review(host, source, receipt, revision=3)
    assert preview["status"] == "ok" and preview["data"]["can_accept"], preview
    first = accept(
        host,
        source,
        receipt,
        preview["data"]["review_digest"],
        revision=3,
        key="integration-accept",
    )
    assert first["status"] == "ok" and not first["replayed"], first
    assert first["data"]["task"]["state"] == "done"
    assert first["data"]["task"]["revision"] == 4
    host.manager.discover_and_load(force=True)
    retry = accept(
        host,
        source,
        receipt,
        preview["data"]["review_digest"],
        revision=3,
        key="integration-accept",
    )
    assert retry["replayed"] and retry["data"] == first["data"]
    assert command(host, "show " + source["id"])["data"]["revision"] == 4
    assert snapshot(board[1]) == native_before
