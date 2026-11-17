"""Actual pinned schedule APIs; no scheduler, storage repair or delivery."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from test_local_task_cli import entry, invoke
from test_local_task_cli import native as native


def preview(
    command,
    capsys,
    schedule="0 9 * * *",
    timezone="Asia/Shanghai",
    after="2027-01-01T08:00:00+08:00",
):
    return invoke(
        command,
        capsys,
        "schedule-preview",
        "--schedule",
        schedule,
        "--timezone",
        timezone,
        "--after",
        after,
        "--count",
        "3",
    )


def test_native_preview_never_reads_or_repairs_jobs(native, capsys, monkeypatch):
    from cron import jobs

    home, manager = native
    command = entry(manager)
    cron = home / "cron"
    cron.mkdir(exist_ok=True)
    path = cron / "jobs.json"
    path.write_text('[{"id":"malformed-private-record"}]')
    before = path.read_bytes()
    entries = sorted(p.name for p in cron.iterdir())
    forbidden = Mock(side_effect=AssertionError("native store access"))
    for name in ("load_jobs", "get_job", "list_jobs", "create_job", "save_jobs", "ensure_dirs"):
        monkeypatch.setattr(jobs, name, forbidden)
    code, result = preview(command, capsys)
    assert code == 0 and result["scheduled"] is False
    assert [x["local"] for x in result["occurrences"]] == [
        "2027-01-01T09:00:00+08:00",
        "2027-01-02T09:00:00+08:00",
        "2027-01-03T09:00:00+08:00",
    ]
    code, relative = preview(command, capsys, "in 30m")
    assert code == 0 and relative["kind"] == "once"
    assert [x["local"] for x in relative["occurrences"]] == ["2027-01-01T08:30:00+08:00"]
    assert path.read_bytes() == before
    assert sorted(p.name for p in cron.iterdir()) == entries
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    "schedule,zone,after,expected",
    [
        ("every 30m", "America/New_York", "2027-03-14T01:45:00-05:00", "2027-03-14T03:15:00-04:00"),
        (
            "2027-01-02T01:00:00+00:00",
            "Asia/Shanghai",
            "2027-01-01T00:00:00+00:00",
            "2027-01-02T09:00:00+08:00",
        ),
        (
            "30 1 * * *",
            "America/New_York",
            "2027-11-07T00:00:00-04:00",
            "2027-11-07T01:30:00-04:00",
        ),
    ],
)
def test_native_time_semantics(native, capsys, schedule, zone, after, expected):
    home, manager = native
    command = entry(manager)
    before = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
    code, result = preview(command, capsys, schedule, zone, after)
    assert code == 0 and result["occurrences"][0]["local"] == expected
    assert sorted(str(p.relative_to(home)) for p in home.rglob("*")) == before


def test_native_gap_requires_review(native, capsys):
    _, manager = native
    code, result = preview(
        entry(manager), capsys, "30 2 * * *", "America/New_York", "2027-03-14T00:00:00-05:00"
    )
    assert code == 0 and result["boundary"] == "dst_gap_requires_review"


@pytest.mark.parametrize(
    "after,expected_local,fold",
    [
        ("2027-03-14T01:45:00-05:00", "2027-03-14T03:15:00-04:00", 0),
        ("2027-11-07T05:45:00+00:00", "2027-11-07T01:15:00-05:00", 1),
    ],
)
def test_relative_preview_matches_native_paused_one_shot(
    native, capsys, monkeypatch, after, expected_local, fold
):
    from cron import jobs

    home, manager = native
    command = entry(manager)
    timezone = "America/New_York"
    cron = home / "cron"
    before = sorted(cron.rglob("*"))
    host_clock = Mock(side_effect=AssertionError("preview must use its explicit reference"))
    with monkeypatch.context() as isolated:
        isolated.setattr(jobs, "_hermes_now", host_clock)
        code, result = preview(command, capsys, "in 30m", timezone, after)
    host_clock.assert_not_called()
    assert sorted(cron.rglob("*")) == before
    assert code == 0 and result["kind"] == "once" and result["boundary"] == "one_shot"
    assert result["scheduled"] is False and result["delivery_verified"] is False
    (occurrence,) = result["occurrences"]
    assert occurrence["local"] == expected_local and occurrence["fold"] == fold
    assert occurrence["wall_time_valid"] is True

    # Use the actual native creation path under a frozen clock for comparison.
    monkeypatch.setattr(jobs, "_hermes_now", lambda: datetime.fromisoformat(after))
    job = jobs.create_job(
        prompt="Synthetic relative schedule comparison",
        schedule="in 30m",
        timezone=timezone,
        paused=True,
        deliver="local",
    )
    assert job["state"] == "paused" and job["next_run_at"] is None
    assert jobs.get_job(job["id"])["schedule"] == job["schedule"]
    assert job["schedule"]["kind"] == "once"
    actual = datetime.fromisoformat(job["schedule"]["run_at"]).astimezone(UTC)
    assert actual.isoformat() == occurrence["utc"]


@pytest.mark.parametrize(
    "schedule,expected_boundary,expected_count",
    [("in 0m", "not_after_reference", 0), ("30m", "count_limit", 3)],
)
def test_native_duration_forms_remain_distinct(
    native, capsys, schedule, expected_boundary, expected_count
):
    _, manager = native
    code, result = preview(entry(manager), capsys, schedule)
    assert code == 0 and result["boundary"] == expected_boundary
    assert len(result["occurrences"]) == expected_count


def test_unload_and_profile_change(native, capsys, monkeypatch, tmp_path):
    _, manager = native
    command = entry(manager)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))
    assert preview(command, capsys)[1]["error"]["code"] == "profile_context_changed"
    manager.unload()
    assert preview(command, capsys)[1]["error"]["code"] == "preview_closed"


@pytest.mark.parametrize("schedule", ["20270101T090000", "2027-W01-1T09:00:00"])
def test_alternate_iso_forms_require_offset(native, capsys, schedule):
    _, manager = native
    code, result = preview(entry(manager), capsys, schedule)
    assert code == 1 and result["error"]["code"] == "offset_required"


def test_non_file_backend_and_worker_are_rejected(native, capsys, monkeypatch):
    from agent import safe_worker_policy
    from hermes_cli import config_backend

    _, manager = native
    command = entry(manager)
    monkeypatch.setattr(config_backend, "get_config_backend", lambda: object())
    assert preview(command, capsys)[1]["error"]["code"] == "unsupported_config_backend"
    monkeypatch.setattr(safe_worker_policy, "worker_config_snapshot", lambda: {})
    assert preview(command, capsys)[1]["error"]["code"] == "unsupported_runtime"
