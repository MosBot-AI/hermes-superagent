"""Offline CLI boundary tests; real host integration lives in contracts."""

import argparse
import json
from contextlib import contextmanager
from uuid import uuid4

import pytest

from personal_agent import task_cli
from personal_agent.plugin import setup_cli
from personal_agent.tasks import TaskError


@pytest.fixture
def parser():
    result = argparse.ArgumentParser()
    setup_cli(result)
    return result


def test_request_extraction_maps_show_and_ignores_host_context(parser):
    task_id = str(uuid4())
    args = parser.parse_args(["tasks", "show", task_id])
    args.host_session = "synthetic-host-context"
    assert task_cli.command_request(args) == ("get", {"task_id": task_id})


def test_update_distinguishes_omitted_fields_from_explicit_empty_details(parser):
    task_id = str(uuid4())
    args = parser.parse_args(
        [
            "tasks",
            "update",
            task_id,
            "--expected-revision",
            "2",
            "--request-id",
            "update-1",
            "--details",
            "",
        ]
    )
    operation, payload = task_cli.command_request(args)
    assert operation == "update"
    assert payload == {
        "task_id": task_id,
        "expected_revision": 2,
        "request_id": "update-1",
        "details": "",
    }
    assert not hasattr(args, "title")


@pytest.mark.parametrize(
    "argv",
    [
        ["tasks"],
        ["tasks", "capture", "--title", "Synthetic"],
        ["tasks", "complete", "id", "--request-id", "r1", "--note", "Synthetic"],
        ["tasks", "list", "--state", "scheduled"],
        ["tasks", "list", "--limit", "NaN"],
        ["tasks", "list", "--home", "/synthetic/path"],
    ],
)
def test_parser_rejects_missing_or_unsupported_arguments(parser, argv):
    with pytest.raises(SystemExit) as error:
        parser.parse_args(argv)
    assert error.value.code == 2


def test_unknown_operation_is_redacted():
    with pytest.raises(TaskError, match="invalid_request"):
        task_cli.command_request(argparse.Namespace(task_operation="synthetic-private-input"))


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("read_only", "local_tasks_disabled"),
        (None, "invalid_configuration"),
        ({}, "invalid_configuration"),
        (True, "invalid_configuration"),
    ],
)
def test_disabled_or_invalid_mode_does_not_open_storage(
    parser, monkeypatch, tmp_path, capsys, mode, expected
):
    monkeypatch.setattr(task_cli, "current_profile_home", lambda: tmp_path)

    def forbidden(*args):
        pytest.fail("Storage opened before mode validation")

    monkeypatch.setattr(task_cli, "open_task_store", forbidden)
    code = task_cli.run_tasks_cli(
        parser.parse_args(["tasks", "list"]), read_mode=lambda: mode, bound_home=tmp_path
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == expected


@pytest.mark.parametrize(
    "error,expected,retryable",
    [
        (RuntimeError("Synthetic private title /private/path"), "local_tasks_unavailable", False),
        (TaskError("storage_busy", retryable=True), "storage_busy", True),
    ],
)
def test_error_boundary_redacts_unexpected_errors_and_preserves_retryability(
    parser, monkeypatch, tmp_path, capsys, error, expected, retryable
):
    monkeypatch.setattr(task_cli, "current_profile_home", lambda: tmp_path)

    @contextmanager
    def failing_store(home):
        raise error
        yield  # pragma: no cover

    monkeypatch.setattr(task_cli, "open_task_store", failing_store)
    args = parser.parse_args(
        [
            "tasks",
            "capture",
            "--title",
            "Synthetic private title",
            "--details",
            "Synthetic private body",
            "--request-id",
            "r1",
        ]
    )
    assert task_cli.run_tasks_cli(args, read_mode=lambda: "local_tasks", bound_home=tmp_path) == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert "Synthetic private" not in output.out and "/private/path" not in output.out
    result = json.loads(output.out)
    assert result["error"] == {"code": expected, "retryable": retryable}
    assert result["data"] is None and result["replayed"] is False


def test_valid_request_is_dispatched_once_and_result_is_returned(
    parser, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(task_cli, "current_profile_home", lambda: tmp_path)
    calls = []

    class Store:
        def run(self, operation, payload):
            calls.append((operation, payload))
            return {
                "data": {"items": [], "next_cursor": None, "has_more": False},
                "replayed": False,
            }

    @contextmanager
    def opened(home):
        assert home == tmp_path
        yield Store()

    monkeypatch.setattr(task_cli, "open_task_store", opened)
    args = parser.parse_args(["tasks", "list", "--state", "all", "--limit", "5"])
    assert task_cli.run_tasks_cli(args, read_mode=lambda: "local_tasks", bound_home=tmp_path) == 0
    assert calls == [("list", {"state": "all", "limit": 5, "after": None})]
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok" and result["error"] is None
    assert result["schema_version"] == "personal.local-tasks.v1"


def test_changed_profile_is_rejected_before_config_or_storage(
    parser, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(task_cli, "current_profile_home", lambda: tmp_path / "another-profile")

    def forbidden(*args):
        pytest.fail("A stale handler must not read another profile's config or data")

    monkeypatch.setattr(task_cli, "open_task_store", forbidden)
    code = task_cli.run_tasks_cli(
        parser.parse_args(["tasks", "list"]), read_mode=forbidden, bound_home=tmp_path
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "profile_context_changed"


def test_configuration_reader_failure_is_redacted(parser, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(task_cli, "current_profile_home", lambda: tmp_path)

    def broken_config():
        raise ValueError("Synthetic private configuration /synthetic/private/path")

    code = task_cli.run_tasks_cli(
        parser.parse_args(["tasks", "list"]), read_mode=broken_config, bound_home=tmp_path
    )
    assert code == 1
    output = capsys.readouterr().out
    assert "Synthetic private" not in output and "/synthetic/private/path" not in output
    assert json.loads(output)["error"]["code"] == "local_tasks_unavailable"


def test_invalid_payload_never_reaches_store(parser, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(task_cli, "current_profile_home", lambda: tmp_path)

    def forbidden(*args):
        pytest.fail("Invalid input must be rejected before any storage side effect")

    monkeypatch.setattr(task_cli, "open_task_store", forbidden)
    code = task_cli.run_tasks_cli(
        parser.parse_args(["tasks", "capture", "--title", "", "--request-id", "request-1"]),
        read_mode=lambda: "local_tasks",
        bound_home=tmp_path,
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_request"


def test_capture_without_due_keeps_legacy_digest_fields(parser):
    args = parser.parse_args(["tasks", "capture", "--title", "Synthetic", "--request-id", "r1"])
    assert task_cli.command_request(args) == (
        "capture",
        {"title": "Synthetic", "details": "", "request_id": "r1"},
    )


def test_due_date_edit_and_clear_remain_distinct(parser):
    task_id = str(uuid4())
    common = ["tasks", "update", task_id, "--expected-revision", "1", "--request-id", "r2"]
    assert (
        task_cli.command_request(parser.parse_args([*common, "--due-date", "2028-02-29"]))[1][
            "due_date"
        ]
        == "2028-02-29"
    )
    assert (
        task_cli.command_request(parser.parse_args([*common, "--clear-due"]))[1]["due_date"] is None
    )
    with pytest.raises(SystemExit) as error:
        parser.parse_args([*common, "--due-date", "2028-02-29", "--clear-due"])
    assert error.value.code == 2


def test_agenda_requires_explicit_date_and_extracts_only_declared_fields(parser):
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["tasks", "agenda"])
    assert error.value.code == 2
    args = parser.parse_args(["tasks", "agenda", "--on", "2028-02-29", "--limit", "3"])
    args.owner = "not-trusted"
    assert task_cli.command_request(args) == (
        "agenda",
        {"on": "2028-02-29", "limit": 3, "after": None},
    )
