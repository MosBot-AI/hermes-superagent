"""Readable views preserve structured data, retry receipts and bounded pages."""

import argparse
import copy
import json
import shlex
import sqlite3

import pytest
from test_conversation_tasks import local as local

from personal_agent.conversation_tasks import _parse, run_conversation_tasks
from personal_agent.task_cli import command_request, setup_tasks_cli
from personal_agent.task_presentation import render_task_result
from personal_agent.tasks import TaskStore


@pytest.fixture
def store():
    with sqlite3.connect(":memory:") as connection:
        store = TaskStore(connection)
        store.initialize()
        yield store


def result(store, operation, payload):
    return {"status": "ok", "error": None, **store.run(operation, payload)}


def capture(store, key="one", **extra):
    return result(store, "capture", {"title": "Synthetic task", "request_id": key, **extra})


def render(store, operation, payload, **options):
    return render_task_result(
        result(store, operation, payload), operation=operation, payload=payload, **options
    )


def test_full_record_progress_replay_and_terminal_are_not_execution_claims(store):
    captured = capture(store, details="Private details", due_date="2026-11-07", project="Demo")
    task = captured["data"]
    args = {
        "task_id": task["id"],
        "expected_revision": 1,
        "request_id": "progress",
        "work_status": "blocked",
        "note": "Missing attachment",
    }
    first = render(store, "progress", args)
    assert "Local progress recorded." in first and "[blocked]" in first
    assert 'Progress note: "Missing attachment"' in first
    assert "Request ID: progress" in first and "revision: 2" in first
    assert "no work, reminder or external action was executed" in first
    replay = render(store, "progress", args)
    assert replay.startswith("Replayed saved receipt.") and "older revision" in replay
    done = render(
        store,
        "complete",
        {
            "task_id": task["id"],
            "expected_revision": 2,
            "request_id": "done",
            "note": "User confirmed done",
        },
    )
    assert "Task marked done in the local inbox." in done and "[done]" in done
    assert 'Last recorded progress note: "Missing attachment"' in done
    assert "[blocked]" not in done
    legacy = copy.deepcopy(captured)
    for key in ("work_status", "progress_note", "progress_updated_at", "project", "due_date"):
        legacy["data"].pop(key)
    legacy["replayed"] = True
    text = render_task_result(legacy, operation="capture", payload={"request_id": "one"})
    assert "not recorded in this receipt" in text and "Request ID: one" in text


@pytest.mark.parametrize(
    "operation,extra",
    [("list", {}), ("search", {"query": "--needle"}), ("agenda", {"on": "2026-11-07"})],
)
def test_display_limited_pages_generate_exact_safe_continuation(store, operation, extra):
    label = "--label ' ; [not a command]"
    for index in range(25):
        capture(
            store,
            str(index),
            title=f"--needle {index}",
            project=label,
            due_date="2026-11-07",
            details="Do not show private body",
        )
    payload = {**extra, "project": label, "limit": 100}
    raw = result(store, operation, payload)
    assert len(raw["data"]["items"]) == 25 and raw["data"]["has_more"] is False
    before = copy.deepcopy(raw)
    text = render_task_result(raw, operation=operation, payload=payload)
    assert text.count("  ID: ") == 20 and "Do not show" not in text
    assert raw == before
    command = next(
        line.removeprefix("More: /personal-tasks ")
        for line in text.splitlines()
        if line.startswith("More: ")
    )
    selected, next_payload, _ = _parse(command)
    assert selected == operation and next_payload["project"] == label
    assert next_payload["after"] == raw["data"]["items"][19]["id"]
    page = store.run(selected, next_payload)["data"]
    assert len(page["items"]) == 5
    assert {task["id"] for task in page["items"]}.isdisjoint(
        task["id"] for task in raw["data"]["items"][:20]
    )
    cli = render_task_result(
        raw, operation=operation, payload=payload, prefix="hermes personal-agent tasks"
    )
    command = next(
        line.removeprefix("More: hermes personal-agent ")
        for line in cli.splitlines()
        if line.startswith("More: ")
    )
    parser = argparse.ArgumentParser()
    setup_tasks_cli(parser.add_subparsers(dest="command"))
    args = parser.parse_args(shlex.split(command))
    assert args.output_format == "text" and command_request(args) == (selected, next_payload)


def test_project_and_history_display_paging_is_lossless(store):
    for index in range(25):
        capture(store, str(index), project=f"label-{index:02}")
    text = render(store, "projects", {"limit": 100})
    continuation = next(
        line.removeprefix("More: /personal-tasks ")
        for line in text.splitlines()
        if line.startswith("More: ")
    )
    operation, payload, _ = _parse(continuation)
    assert payload["after"] == "label-19"
    assert len(store.run(operation, payload)["data"]["items"]) == 5
    task = store.run("list", {})["data"]["items"][0]
    for index in range(24):
        task = store.run(
            "update",
            {
                "task_id": task["id"],
                "expected_revision": task["revision"],
                "title": "Updated",
                "request_id": f"u{index}",
            },
        )["data"]
    text = render(store, "history", {"task_id": task["id"], "limit": 100})
    assert "prior text" in text and "Updated" not in text
    continuation = next(
        line.removeprefix("More: /personal-tasks ")
        for line in text.splitlines()
        if line.startswith("More: ")
    )
    operation, payload, _ = _parse(continuation)
    assert payload["after_revision"] == 20
    assert len(store.run(operation, payload)["data"]["items"]) == 5


def test_review_preserves_total_omissions_status_and_explicit_dates(store):
    for index in range(8):
        capture(store, str(index), due_date="2026-11-07", details="Private", project="Demo")
    text = render(store, "review", {"on": "2026-11-07", "per_bucket_limit": 20})
    assert "Active: 8" in text and "Due today: 8" in text
    assert "Not shown: 3 task(s)" in text and text.count("  ID: ") == 5
    assert "Recorded progress: ready 8" in text
    assert "upcoming through 2026-11-14" in text and "Private" not in text
    assert "not a priority or execution decision" in text


def test_maximum_fields_are_delimited_and_human_output_is_bounded(store):
    task = capture(store, title='"' * 240, project='"' * 80, details="x" + "\n" * 4999)["data"]
    task = store.run(
        "progress",
        {
            "task_id": task["id"],
            "expected_revision": 1,
            "work_status": "blocked",
            "note": "x" + "\n" * 1999,
            "request_id": "progress",
        },
    )["data"]
    task = store.run(
        "complete",
        {
            "task_id": task["id"],
            "expected_revision": 2,
            "note": "x" + "\n" * 1999,
            "request_id": "complete",
        },
    )["data"]
    text = render(store, "get", {"task_id": task["id"]})
    assert len(text) < 24000
    assert "\\n\\n" in text and "\n\n\n" not in text
    assert 'Details: "x\\n' in text
    for index in range(100):
        capture(store, f"long-{index}", title='"' * 240, project='"' * 80)
    assert len(render(store, "list", {"limit": 100})) < 24000


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("list", {}),
        ("search", {"query": "missing"}),
        ("agenda", {"on": "2026-11-07"}),
        ("projects", {}),
        ("review", {"on": "2026-11-07"}),
    ],
)
def test_empty_views_do_not_claim_all_work_done(store, operation, payload):
    text = render(store, operation, payload)
    assert "all work done" not in text.lower() and "More:" not in text
    assert not text.startswith("{")


def test_error_messages_preserve_retry_key_without_private_diagnostics():
    for code in ("revision_conflict", "idempotency_conflict", "storage_busy", "unsupported_origin"):
        value = {
            "status": "error",
            "error": {"code": code, "retryable": False},
            "request_id": "same-key",
            "data": None,
        }
        text = render_task_result(value, operation="", payload={})
        assert code in text and "Request ID: same-key" in text
    unexpected = {"status": "error", "error": {"code": "/private/path contains secret"}}
    assert "secret" not in render_task_result(unexpected, operation="", payload={})


def test_unexpected_result_shape_falls_back_to_actual_receipt_not_failed_write():
    value = {"status": "ok", "data": {"legacy": "record"}, "replayed": True}
    assert json.loads(render_task_result(value, operation="capture", payload={})) == value


def human(tmp_path, config, raw, **extra):
    return run_conversation_tasks(
        raw,
        read_config=config.get,
        bound_home=tmp_path,
        platform="cli",
        session_id="synthetic",
        session_key="synthetic",
        default_format="text",
        **extra,
    )


def test_native_text_and_json_share_one_mutation_and_identical_retry(local, tmp_path):
    _, config, calls = local
    raw = 'add "Readable task" --request-id once'
    text = human(tmp_path, config, raw)
    assert text.startswith("Task saved.") and "Request ID: once" in text
    data = json.loads(human(tmp_path, config, "--json " + raw))
    assert data["replayed"] and data["data"]["title"] == "Readable task"
    listing = json.loads(human(tmp_path, config, "list --format json"))
    assert len(listing["data"]["items"]) == 1 and len(calls) == 3
    assert human(tmp_path, config, "help").startswith("Local task workbench")
    assert json.loads(human(tmp_path, config, "--json help"))["status"] == "ok"
    error = human(tmp_path, config, 'add "PRIVATE UNFINISHED')
    assert "invalid_request" in error and "PRIVATE" not in error
    assert (
        "invalid_request" in json.loads(human(tmp_path, config, '--json add "bad'))["error"]["code"]
    )


@pytest.mark.parametrize("raw", ["--json list", "--json\tlist", "  --json list"])
def test_machine_prefix_preserves_errors_before_private_parse(local, tmp_path, monkeypatch, raw):
    import personal_agent.conversation_tasks as commands

    _, config, calls = local
    config["local_conversation"] = False
    monkeypatch.setattr(commands, "_parse", lambda *_: pytest.fail("Private parse before gate"))
    value = json.loads(human(tmp_path, config, raw))
    assert value["error"]["code"] == "local_conversation_disabled" and not calls


def test_format_selectors_cannot_create_authority_or_reinterpret_data(local, tmp_path):
    _, config, _ = local
    task = json.loads(human(tmp_path, config, "--json add --title=--json --request-id literal"))[
        "data"
    ]
    assert task["title"] == "--json"
    denied = human(tmp_path, config, "--json list --format text")
    assert json.loads(denied)["error"]["code"] == "invalid_request"
    assert (
        _parse('add "Literal --format text" --request-id data')[1]["title"]
        == "Literal --format text"
    )
