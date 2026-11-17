from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from personal_agent.schedule_preview import preview_schedule


def call(**kwargs):
    defaults = dict(
        schedule="every 30m", timezone="Asia/Shanghai", after="2026-11-08T09:00:00+08:00", count=3
    )
    defaults.update(kwargs)
    parse = defaults.pop("parse", lambda _: {"kind": "interval", "minutes": 30})
    parse_duration = defaults.pop("parse_duration", Mock(side_effect=AssertionError))
    next_run = defaults.pop(
        "next_run",
        lambda _, last, **kw: (datetime.fromisoformat(last) + timedelta(minutes=30)).isoformat(),
    )
    return preview_schedule(
        **defaults, parse=parse, parse_duration=parse_duration, next_run=next_run
    )


def test_bounded_explicit_reference():
    result = call()
    assert len(result["occurrences"]) == 3
    assert result["occurrences"][0]["local"] == "2026-11-08T09:30:00+08:00"
    assert result["scheduled"] is False and result["delivery_verified"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"count": True},
        {"count": 0},
        {"count": 21},
        {"schedule": "x" * 241},
        {"schedule": "a\nb"},
        {"timezone": "no/such-zone"},
        {"after": "bad"},
        {"after": "2026-11-08T09:00:00"},
        {"schedule": "2026-11-08T09:00:00"},
        {"schedule": "20270101T090000"},
        {"schedule": "2027-W01-1T09:00:00"},
    ],
)
def test_rejected_inputs_do_not_call_native(overrides):
    parse = Mock()
    assert call(parse=parse, **overrides)["status"] == "error"
    parse.assert_not_called()


def test_absolute_once_is_not_evaluated_against_real_clock():
    next_run = Mock(side_effect=AssertionError("must not use current clock grace"))
    result = call(
        schedule="2026-11-09T09:00:00+08:00",
        parse=lambda _: {"kind": "once", "run_at": "2026-11-09T09:00:00+08:00"},
        next_run=next_run,
    )
    assert result["boundary"] == "one_shot"
    assert len(result["occurrences"]) == 1
    next_run.assert_not_called()


def test_relative_once_resolves_elapsed_time_before_native_schedule_parsing():
    parse_duration = Mock(return_value=30)
    parse = Mock(side_effect=lambda text: {"kind": "once", "run_at": text})
    next_run = Mock(side_effect=AssertionError)
    result = call(
        schedule="IN  30m",
        timezone="America/New_York",
        after="2027-11-07T05:45:00+00:00",
        parse=parse,
        parse_duration=parse_duration,
        next_run=next_run,
    )
    parse_duration.assert_called_once_with("30m")
    parse.assert_called_once_with("2027-11-07T01:15:00-05:00")
    next_run.assert_not_called()
    assert result["kind"] == "once" and result["boundary"] == "one_shot"
    assert result["occurrences"] == [
        {
            "native_time": "2027-11-07T01:15:00-05:00",
            "local": "2027-11-07T01:15:00-05:00",
            "utc": "2027-11-07T06:15:00+00:00",
            "fold": 1,
            "wall_time_valid": True,
        }
    ]


def test_invalid_relative_duration_never_reaches_native_schedule_parser():
    parse_duration = Mock(side_effect=ValueError("synthetic private diagnostic"))
    parse = Mock()
    result = call(schedule="in invalid", parse=parse, parse_duration=parse_duration)
    assert result == {"status": "error", "error": {"code": "invalid_schedule"}, "scheduled": False}
    parse.assert_not_called()


def test_spring_gap_is_reported_not_silently_normalized():
    result = call(
        timezone="America/New_York",
        after="2027-03-14T01:00:00-05:00",
        parse=lambda _: {"kind": "cron"},
        next_run=lambda *a, **k: "2027-03-14T02:30:00-05:00",
    )
    assert result["boundary"] == "dst_gap_requires_review"
    assert result["occurrences"][0]["wall_time_valid"] is False
    assert result["occurrences"][0]["local"] == "2027-03-14T03:30:00-04:00"


@pytest.mark.parametrize(
    "value,boundary",
    [(None, "no_native_candidate"), ("2026-11-08T08:00:00+08:00", "not_after_reference")],
)
def test_no_progress_stops(value, boundary):
    result = call(next_run=lambda *a, **k: value)
    assert result["occurrences"] == [] and result["boundary"] == boundary


def test_native_error_does_not_leak_message():
    def bad(_):
        raise ValueError("secret")

    result = call(parse=bad)
    assert result["status"] == "error" and "secret" not in str(result)
