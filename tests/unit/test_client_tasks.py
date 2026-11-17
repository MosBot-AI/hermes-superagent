"""Shared projection and live pagination over synthetic, selected local stores."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4

import jsonschema
import pytest

from personal_agent import tasks
from personal_agent.client_api import build_client_capabilities
from personal_agent.client_tasks import (
    ClientTaskPageError,
    ClientTaskProjectionError,
    SharedTaskPager,
    project_local_task,
)
from personal_agent.tasks import TaskStore

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/personal-api/schema.json").read_text()
)
VALIDATOR = jsonschema.Draft202012Validator({**SCHEMA, "$ref": "#/$defs/Task"})
PAGE_VALIDATOR = jsonschema.Draft202012Validator({**SCHEMA, "$ref": "#/$defs/TasksPage"})


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


@pytest.fixture
def capture(monkeypatch):
    def add(store, position, title="Synthetic 中文"):
        task_id = UUID(f"00000000-0000-4000-8000-{position:012x}")
        monkeypatch.setattr(tasks, "uuid4", lambda: task_id)
        record = store.run(
            "capture",
            {"title": title, "details": "Private details", "request_id": f"seed-{position}"},
        )["data"]
        return record["id"]

    return add


def test_shared_task_pages_are_bounded_live_and_read_only(capture):
    with closing(sqlite3.connect(":memory:")) as connection:
        store = TaskStore(connection)
        store.initialize()
        pager = SharedTaskPager(store)
        empty = pager.page()
        PAGE_VALIDATOR.validate(empty)
        assert empty["data"] == {"items": [], "next_cursor": None, "consistency": "live"}
        ids = [capture(store, position) for position in range(64)]
        assert pager.page(limit=64)["data"]["next_cursor"] is None
        ids.extend(capture(store, position) for position in range(64, 70))
        reads = set()

        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if (
                action == sqlite3.SQLITE_READ
                and table == "tasks"
                and database == "main"
                and column in {"id", "title", "revision", "state", "work_status"}
            ):
                reads.add(column)
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        first = pager.page(limit=64)
        PAGE_VALIDATOR.validate(first)
        page = first["data"]
        assert [item["id"] for item in page["items"]] == ids[:64]
        assert page["next_cursor"]
        second = pager.page(limit=64, cursor=page["next_cursor"])
        PAGE_VALIDATOR.validate(second)
        assert [item["id"] for item in second["data"]["items"]] == ids[64:]
        assert second["data"]["next_cursor"] is None
        assert len(pager.page()["data"]["items"]) == 32
        assert "Private" not in json.dumps([first, second])
        assert reads == {"id", "title", "revision", "state", "work_status"}
        assert not connection.in_transaction


def test_shared_task_continuation_reads_current_records_and_keeps_its_keyset(capture):
    with closing(sqlite3.connect(":memory:")) as connection:
        store = TaskStore(connection)
        store.initialize()
        first_id = capture(store, 20)
        last_id = capture(store, 40)
        pager = SharedTaskPager(store)
        first = pager.page(limit=1)["data"]
        assert first["items"][0]["id"] == first_id

        earlier = capture(store, 10)
        later = capture(store, 30)
        store.run(
            "progress",
            {
                "task_id": last_id,
                "expected_revision": 1,
                "work_status": "blocked",
                "note": "Private work note",
                "request_id": "update-last",
            },
        )
        next_page = pager.page(cursor=first["next_cursor"])["data"]
        assert [item["id"] for item in next_page["items"]] == [later, last_id]
        assert next_page["items"][1]["wait_reason"] == "local_blocked"
        assert next_page["items"][1]["revision"] == "2"
        assert next_page["next_cursor"] is None
        assert pager.page(limit=1)["data"]["items"][0]["id"] == earlier


def test_shared_task_cursor_is_confined_to_the_pager_and_invalid_tokens_do_not_read(capture):
    with closing(sqlite3.connect(":memory:")) as one, closing(sqlite3.connect(":memory:")) as two:
        first, second = TaskStore(one), TaskStore(two)
        first.initialize()
        second.initialize()
        capture(first, 1)
        capture(first, 2)
        other = capture(second, 1, "Other selected scope")
        pager = SharedTaskPager(first)
        first_page = pager.page(limit=1)["data"]
        assert first_page["items"][0]["id"] == other
        cursor = first_page["next_cursor"]
        assert cursor is not None

        def deny_reads(action, table, column, database, trigger):
            pytest.fail("invalid cursor entered SQLite")

        one.set_authorizer(deny_reads)
        two.set_authorizer(deny_reads)
        for target, input_cursor in (
            (SharedTaskPager(second), cursor),
            (SharedTaskPager(first), cursor),
            (pager, ("A" if cursor[0] != "A" else "B") + cursor[1:]),
            (pager, cursor + "="),
            (pager, "a" * 2047 + "😀"),
        ):
            with pytest.raises(ClientTaskPageError) as error:
                target.page(cursor=input_cursor)
            assert (error.value.code, error.value.retryable) == ("cursor_invalid", False)

        for limit, input_cursor in ((0, None), (65, None), (True, None), (1, ""), (1, "x" * 2049)):
            with pytest.raises(ClientTaskPageError) as error:
                pager.page(limit=limit, cursor=input_cursor)
            assert (error.value.code, error.value.retryable) == ("invalid_request", False)

        two.set_authorizer(None)
        assert SharedTaskPager(second).page()["data"]["items"][0]["title"] == "Other selected scope"


def test_shared_task_page_discards_malformed_records_and_preserves_caller_transaction(capture):
    with closing(sqlite3.connect(":memory:")) as connection:
        store = TaskStore(connection)
        store.initialize()
        capture(store, 1)
        bad_id = capture(store, 2)
        connection.execute("UPDATE tasks SET title = ? WHERE id = ?", ("private\nsource", bad_id))
        connection.commit()
        pager = SharedTaskPager(store)
        with pytest.raises(ClientTaskPageError) as unavailable:
            pager.page()
        assert (unavailable.value.code, unavailable.value.retryable) == (
            "internal_unavailable",
            False,
        )
        assert "private" not in str(unavailable.value)
        assert unavailable.value.__cause__ is None
        connection.execute("BEGIN")
        with pytest.raises(ClientTaskPageError) as occupied:
            pager.page()
        assert occupied.value.code == "internal_unavailable"
        assert connection.in_transaction
        connection.rollback()
    with pytest.raises(ClientTaskPageError) as closed:
        pager.page()
    assert (closed.value.code, closed.value.retryable) == ("internal_unavailable", False)


def test_shared_task_page_reports_busy_storage_as_retryable(tmp_path, capture):
    path = tmp_path / "synthetic.sqlite3"
    with (
        closing(sqlite3.connect(path, timeout=0)) as reader,
        closing(sqlite3.connect(path)) as writer,
    ):
        store = TaskStore(reader)
        store.initialize()
        task_id = capture(store, 1)
        pager = SharedTaskPager(store)
        writer.execute("BEGIN EXCLUSIVE")
        with pytest.raises(ClientTaskPageError) as error:
            pager.page()
        assert (error.value.code, error.value.retryable) == ("internal_unavailable", True)
        writer.rollback()
        assert pager.page()["data"]["items"][0]["id"] == task_id
