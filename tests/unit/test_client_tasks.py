"""Conformance of pure local-task projection; no remote authority is inferred."""

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from personal_agent.client_api import build_client_capabilities
from personal_agent.client_tasks import ClientTaskProjectionError, project_local_task
from personal_agent.tasks import TaskStore

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/personal-api/schema.json").read_text()
)
VALIDATOR = jsonschema.Draft202012Validator({**SCHEMA, "$ref": "#/$defs/Task"})


def record(**changes):
    return {
        "id": "00000000-0000-4000-8000-000000000001",
        "title": "中文 synthetic task",
        "revision": 1,
        "state": "captured",
        "work_status": "ready",
        **changes,
    }


@pytest.mark.parametrize("lifecycle", ["captured", "done", "cancelled"])
@pytest.mark.parametrize("progress", ["ready", "in_progress", "waiting", "blocked"])
def test_actual_store_records_and_terminal_precedence(lifecycle, progress):
    with sqlite3.connect(":memory:") as connection:
        store = TaskStore(connection)
        store.initialize()
        task = store.run("capture", {"title": "中文 synthetic", "request_id": str(uuid4())})["data"]
        task = store.run(
            "progress",
            {
                "task_id": task["id"],
                "expected_revision": task["revision"],
                "work_status": progress,
                "note": "PRIVATE progress and external effects are not verified",
                "request_id": str(uuid4()),
            },
        )["data"]
        if lifecycle != "captured":
            task = store.run(
                "complete" if lifecycle == "done" else "cancel",
                {
                    "task_id": task["id"],
                    "expected_revision": task["revision"],
                    "note": "PRIVATE terminal note",
                    "request_id": str(uuid4()),
                },
            )["data"]
        task = store.run("get", {"task_id": task["id"]})["data"]
        before = dict(task)
        result = project_local_task(task)
        assert task == before
        VALIDATOR.validate(result)
        expected = {"ready": "queued", "in_progress": "running"}.get(progress, "waiting")
        if lifecycle != "captured":
            expected = "completed" if lifecycle == "done" else "cancelled"
        assert result["state"] == expected
        assert result["wait_reason"] == ("local_" + progress if expected == "waiting" else None)
        assert set(result) == {"id", "title", "revision", "state", "wait_reason"}
        assert result["revision"] == str(task["revision"])
        assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("field", ["id", "title", "revision", "state", "work_status"])
def test_missing_current_fields_fail_instead_of_inventing_legacy_defaults(field):
    value = record()
    del value[field]
    with pytest.raises(ClientTaskProjectionError):
        project_local_task(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("id", ""),
        ("id", "a" * 257),
        ("id", "00000000-0000-1000-8000-000000000001"),
        ("id", "FFFFFFFF-FFFF-4FFF-8FFF-FFFFFFFFFFFF"),
        ("title", None),
        ("title", ""),
        ("title", "  "),
        ("title", "x" * 241),
        ("title", "secret\nline"),
        ("title", "secret\x00line"),
        ("title", "secret\u202eline"),
        ("title", "\ud800"),
        ("revision", True),
        ("revision", False),
        ("revision", "1"),
        ("revision", 1.0),
        ("revision", 0),
        ("revision", -1),
        ("revision", 2**63),
        ("state", None),
        ("state", []),
        ("state", "running"),
        ("state", "cancelling"),
        ("state", "unknown"),
        ("work_status", None),
        ("work_status", []),
        ("work_status", "paused"),
        ("work_status", "unknown"),
    ],
)
def test_invalid_fields_fail_with_redacted_error(field, value):
    with pytest.raises(ClientTaskProjectionError) as error:
        project_local_task(record(**{field: value}))
    assert str(error.value) == "Invalid local task record for shared projection."
    assert error.value.__cause__ is None


@pytest.mark.parametrize("value", [None, [], "private", True])
def test_non_records_are_not_coerced(value):
    with pytest.raises(ClientTaskProjectionError):
        project_local_task(value)


def test_maximum_native_bounds_conform_and_revision_is_decimal_string():
    result = project_local_task(record(title="中" * 240, revision=2**63 - 1))
    VALIDATOR.validate(result)
    assert result["revision"] == "9223372036854775807"


def test_extra_payload_and_native_observation_never_override_or_leak():
    class DoNotSerialize:
        def __str__(self):
            raise AssertionError("must not inspect extra payload")

    value = record(
        details=DoNotSerialize(),
        progress_note=DoNotSerialize(),
        native_observation={"status": "done"},
        authority={"owner": "forged"},
    )
    result = project_local_task(value)
    assert result["state"] == "queued"
    result["title"] = "changed"
    assert project_local_task(value)["title"] == "中文 synthetic task"
    assert all(not c["available"] for c in build_client_capabilities()["data"]["capabilities"])


def test_custom_dict_or_scalar_subclasses_are_not_called():
    class CustomDict(dict):
        def get(self, *args):
            raise AssertionError("custom mapping hook")

    class CustomStr(str):
        pass

    class CustomInt(int):
        pass

    for value in [
        CustomDict(record()),
        record(title=CustomStr("title")),
        record(revision=CustomInt(1)),
    ]:
        with pytest.raises(ClientTaskProjectionError):
            project_local_task(value)
