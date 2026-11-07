"""Pure schema/normalization checks and real in-memory schema-3 task lifecycles."""

import json
import sqlite3
from uuid import uuid4

import pytest

from personal_agent.task_tool_contract import (
    PERSONAL_TASKS_READ_SCHEMA,
    PERSONAL_TASKS_WRITE_SCHEMA,
    normalize_task_tool_request,
)
from personal_agent.tasks import TaskError, TaskStore, validate_request

READ = "personal_tasks_read"
WRITE = "personal_tasks_write"
TASK_ID = str(uuid4())


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:")
    result = TaskStore(connection)
    result.initialize()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
    yield result
    connection.close()


def run(store, tool, **arguments):
    return store.run(*normalize_task_tool_request(tool, arguments))


def test_complete_lifecycle_and_read_actions(store):
    captured = run(
        store,
        WRITE,
        action="capture",
        title="Synthetic review",
        details="Read notes",
        due_date="2026-11-06",
        project="Research",
        request_id="capture-1",
    )["data"]
    task_id = captured["id"]
    assert run(store, READ, action="show", task_id=task_id)["data"] == captured
    assert run(store, READ, action="list")["data"]["items"] == [captured]
    assert run(store, READ, action="search", query="notes")["data"]["items"] == [captured]
    assert run(store, READ, action="agenda", on="2026-11-06")["data"]["items"] == [captured]
    projects = run(store, READ, action="projects")["data"]["items"]
    assert projects == [
        {"project": "Research", "captured": 1, "done": 0, "cancelled": 0, "total": 1}
    ]
    update = dict(
        action="update",
        task_id=task_id,
        expected_revision=1,
        request_id="update-1",
        title="Reviewed",
        due_date=None,
        project=None,
    )
    updated = run(store, WRITE, **update)["data"]
    assert updated["revision"] == 2
    assert updated["project"] is None and updated["due_date"] is None
    assert run(store, READ, action="agenda", on="2026-11-06")["data"]["items"] == []
    assert run(store, READ, action="list", unassigned=True)["data"]["items"] == [updated]
    complete = dict(
        action="complete",
        task_id=task_id,
        expected_revision=2,
        request_id="complete-1",
        note="User confirmed done",
    )
    finished = run(store, WRITE, **complete)["data"]
    assert finished["state"] == "done" and finished["revision"] == 3
    assert run(store, WRITE, **complete) == {"data": finished, "replayed": True}
    assert run(store, WRITE, **update) == {"data": updated, "replayed": True}
    assert run(store, READ, action="list")["data"]["items"] == []
    assert run(store, READ, action="list", state="done")["data"]["items"] == [finished]


def test_cancel_capture_replay_and_cas(store):
    capture = dict(action="capture", title="Synthetic", request_id="stable")
    first = run(store, WRITE, **capture)["data"]
    assert run(store, WRITE, **capture) == {"data": first, "replayed": True}
    with pytest.raises(TaskError, match="idempotency_conflict"):
        run(store, WRITE, **{**capture, "title": "Different"})
    with pytest.raises(TaskError, match="revision_conflict"):
        run(
            store,
            WRITE,
            action="cancel",
            task_id=first["id"],
            expected_revision=2,
            request_id="cancel",
            note="No longer needed",
        )
    result = run(
        store,
        WRITE,
        action="cancel",
        task_id=first["id"],
        expected_revision=1,
        request_id="cancel",
        note="No longer needed",
    )["data"]
    assert result["state"] == "cancelled" and result["revision"] == 2


@pytest.mark.parametrize(
    "tool,arguments",
    [
        (READ, None),
        (READ, []),
        (READ, "{}"),
        (None, {}),
        ([], {}),
        ("unknown", {}),
        (READ, {}),
        (READ, {"action": None}),
        (READ, {"action": []}),
        (READ, {"action": "get", "task_id": TASK_ID}),
        (READ, {"action": "capture", "title": "x", "request_id": "x"}),
        (WRITE, {"action": "list"}),
        (WRITE, {"action": "add"}),
        (WRITE, {"action": "done"}),
        (READ, {"action": "list", "limit": True}),
        (READ, {"action": "list", "limit": 1.0}),
        (READ, {"action": "list", "limit": "1"}),
        (READ, {"action": "list", "limit": 101}),
        (READ, {"action": "list", "state": []}),
        (READ, {"action": "list", "project": " Research"}),
        (READ, {"action": "list", "project": None}),
        (READ, {"action": "list", "project": "Research", "unassigned": False}),
        (READ, {"action": "list", "unassigned": 1}),
        (READ, {"action": "show", "task_id": TASK_ID, "limit": 1}),
        (READ, {"action": "search", "query": ""}),
        (READ, {"action": "agenda", "on": "tomorrow"}),
        (READ, {"action": "agenda", "on": "2026-02-30"}),
        (READ, {"action": "projects", "project": "Research"}),
        (WRITE, {"action": "capture", "title": "x"}),
        (WRITE, {"action": "capture", "title": "x", "request_id": ""}),
        (WRITE, {"action": "capture", "title": "x", "request_id": True}),
        (WRITE, {"action": "capture", "title": "x", "request_id": "x", "due_date": None}),
        (WRITE, {"action": "capture", "title": True, "request_id": "x"}),
        (WRITE, {"action": "capture", "title": "x", "request_id": "x", "note": "no"}),
        (
            WRITE,
            {"action": "update", "task_id": TASK_ID, "request_id": "x", "expected_revision": 1},
        ),
        (
            WRITE,
            {
                "action": "update",
                "task_id": TASK_ID,
                "request_id": "x",
                "expected_revision": True,
                "title": "x",
            },
        ),
        (
            WRITE,
            {"action": "complete", "task_id": TASK_ID, "request_id": "x", "expected_revision": 1},
        ),
        (
            WRITE,
            {
                "action": "cancel",
                "task_id": TASK_ID,
                "request_id": "x",
                "expected_revision": 1,
                "note": " ",
            },
        ),
    ],
)
def test_invalid_requests(tool, arguments):
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request(tool, arguments)


@pytest.mark.parametrize("field", ["owner", "profile", "session", "approved", "extra"])
@pytest.mark.parametrize(
    "tool,arguments",
    [
        (READ, {"action": "list"}),
        (WRITE, {"action": "capture", "title": "Synthetic", "request_id": "x"}),
    ],
)
def test_no_context_or_unknown_fields(tool, arguments, field):
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request(tool, {**arguments, field: True})


@pytest.mark.parametrize(
    "action,payload",
    [
        ("list", {}),
        ("show", {"task_id": TASK_ID}),
        ("search", {"query": "x"}),
        ("projects", {"after": "Research", "limit": 100}),
        ("agenda", {"on": "2026-11-06"}),
        ("history", {"task_id": TASK_ID, "after_revision": 2}),
        ("capture", {"title": "x", "request_id": "x", "project": None}),
        (
            "update",
            {
                "task_id": TASK_ID,
                "expected_revision": 1,
                "request_id": "x",
                "due_date": None,
                "project": None,
            },
        ),
        ("complete", {"task_id": TASK_ID, "expected_revision": 1, "request_id": "x", "note": "x"}),
        ("cancel", {"task_id": TASK_ID, "expected_revision": 1, "request_id": "x", "note": "x"}),
    ],
)
def test_reuses_store_validation_without_mutating_input(action, payload):
    tool = WRITE if "request_id" in payload else READ
    arguments = {"action": action, **payload}
    original = dict(arguments)
    operation = "get" if action == "show" else action
    assert normalize_task_tool_request(tool, arguments) == (
        operation,
        validate_request(operation, payload),
    )
    assert arguments == original


def test_schemas_are_flat_closed_json_objects():
    for schema, name, actions, required in [
        (
            PERSONAL_TASKS_READ_SCHEMA,
            READ,
            ["list", "show", "search", "projects", "agenda", "history", "review", "ready"],
            ["action"],
        ),
        (
            PERSONAL_TASKS_WRITE_SCHEMA,
            WRITE,
            [
                "capture",
                "capture_plan",
                "update",
                "complete",
                "cancel",
                "progress",
                "set_dependencies",
            ],
            ["action", "request_id"],
        ),
    ]:
        assert json.loads(json.dumps(schema)) == schema
        assert schema["name"] == name
        parameters = schema["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        assert parameters["required"] == required
        assert parameters["properties"]["action"]["enum"] == actions
        assert not {"owner", "profile", "session", "approved"} & parameters["properties"].keys()
        assert all("properties" not in prop for prop in parameters["properties"].values())
        assert "configured model" in schema["description"]
        assert "No external action" in schema["description"]
    read = PERSONAL_TASKS_READ_SCHEMA["parameters"]["properties"]
    write = PERSONAL_TASKS_WRITE_SCHEMA["parameters"]["properties"]
    assert read["limit"]["maximum"] == 100
    assert write["expected_revision"]["maximum"] == 2**63 - 2
    assert write["title"]["maxLength"] == 240
    assert write["details"]["maxLength"] == 5000
    assert write["note"]["maxLength"] == 2000
    assert write["project"]["maxLength"] == 80


@pytest.mark.parametrize("action", ["capture", "update", "complete", "cancel"])
def test_read_tool_cannot_mutate_store(store, action):
    captured = run(store, WRITE, action="capture", title="Synthetic", request_id="seed")["data"]
    payload = {"action": action, "request_id": "blocked"}
    if action == "capture":
        payload["title"] = "Forbidden"
    else:
        payload.update(task_id=captured["id"], expected_revision=1)
        payload.update({"title": "Forbidden"} if action == "update" else {"note": "Forbidden"})
    with pytest.raises(TaskError, match="invalid_request"):
        run(store, READ, **payload)
    assert run(store, READ, action="list", state="all")["data"]["items"] == [captured]
