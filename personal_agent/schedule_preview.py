"""Explicit operator-only schedule preview; never create or inspect native jobs."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .task_cli import current_profile_home


def setup_schedule_cli(parent: argparse._SubParsersAction) -> None:
    parser = parent.add_parser("schedule-preview", help="Preview native times; does not schedule")
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--timezone", required=True, help="Explicit IANA timezone")
    parser.add_argument("--after", required=True, help="Offset-aware ISO reference instant")
    parser.add_argument("--count", type=int, default=3)


def failure(code):
    return {"status": "error", "error": {"code": code}, "scheduled": False}


def preview_schedule(schedule, timezone, after, count, *, parse, next_run):
    """Reuse host computation with explicit anchors, returning no execution guarantee."""
    if (
        type(schedule) is not str
        or not 1 <= len(schedule) <= 240
        or any(ord(c) < 32 or ord(c) == 127 for c in schedule)
        or type(timezone) is not str
        or not 1 <= len(timezone) <= 128
        or type(after) is not str
        or len(after) > 64
        or type(count) is not int
        or not 1 <= count <= 20
    ):
        return failure("invalid_request")
    try:
        zone = ZoneInfo(timezone)
        anchor = datetime.fromisoformat(after)
        if anchor.tzinfo is None or anchor.utcoffset() is None:
            return failure("offset_required")
        # Host relative one-shots use its real clock; never pretend --after controls it.
        text = schedule.strip()
        if text.lower().startswith("in "):
            return failure("relative_oneshot_unsupported")
        try:
            instant = datetime.fromisoformat(text)
        except ValueError:
            instant = None
        if instant is not None and (instant.tzinfo is None or instant.utcoffset() is None):
            return failure("offset_required")
        spec = parse(text)
        if type(spec) is not dict or spec.get("kind") not in ("once", "interval", "cron"):
            return failure("unsupported_schedule")
        if spec["kind"] == "once" and instant is None:
            return failure("absolute_oneshot_required")
        values = []
        boundary = "count_limit"
        for _ in range(count):
            # Native one-shot next_run includes real-clock grace policy. This is a
            # nominal future preview, not a prediction of missed-run recovery.
            raw = (
                spec.get("run_at")
                if spec["kind"] == "once"
                else next_run(spec, anchor.isoformat(), timezone=timezone)
            )
            if raw is None:
                boundary = "no_native_candidate"
                break
            candidate = datetime.fromisoformat(raw)
            if candidate.tzinfo is None or candidate.utcoffset() is None:
                return failure("invalid_native_result")
            utc = candidate.astimezone(UTC)
            if utc <= anchor.astimezone(UTC):
                boundary = "not_after_reference"
                break
            local = utc.astimezone(zone)
            # Native cron can propose a nonexistent spring-forward wall clock.
            # Surface that candidate, stop, and require user review rather than
            # silently presenting a normalized different time as intended.
            gap = spec["kind"] == "cron" and candidate.replace(tzinfo=None) != local.replace(
                tzinfo=None
            )
            values.append(
                {
                    "native_time": raw,
                    "utc": utc.isoformat(),
                    "local": local.isoformat(),
                    "fold": local.fold,
                    "wall_time_valid": not gap,
                }
            )
            if gap:
                boundary = "dst_gap_requires_review"
                break
            if spec["kind"] == "once":
                boundary = "one_shot"
                break
            anchor = local
        return {
            "status": "ok",
            "scheduled": False,
            "kind": spec["kind"],
            "timezone": timezone,
            "reference": after,
            "occurrences": values,
            "boundary": boundary,
            "delivery_verified": False,
            "note": "Nominal candidates only; no job, catch-up, execution or delivery is promised.",
        }
    except ValueError, TypeError, KeyError, OverflowError:
        return failure("invalid_schedule")


class SchedulePreview:
    def __init__(self, home: Path):
        self.home = home
        self.closed = False

    def close(self):
        self.closed = True

    def inspect(self, args):
        if self.closed:
            return failure("preview_closed")
        try:
            from agent.safe_worker_policy import (  # ty: ignore[unresolved-import]
                worker_config_snapshot,
            )
            from hermes_cli.config_backend import (  # ty: ignore[unresolved-import]
                FileBackend,
                get_config_backend,
            )

            if worker_config_snapshot() is not None:
                return failure("unsupported_runtime")
            if current_profile_home() != self.home or not self.home.is_dir():
                return failure("profile_context_changed")
            if type(get_config_backend()) is not FileBackend:
                return failure("unsupported_config_backend")
            from cron.jobs import compute_next_run, parse_schedule  # ty: ignore[unresolved-import]

            result = preview_schedule(
                args.schedule,
                args.timezone,
                args.after,
                args.count,
                parse=parse_schedule,
                next_run=compute_next_run,
            )
            if self.closed or current_profile_home() != self.home:
                return failure("profile_context_changed")
            return result
        except Exception, SystemExit:
            return failure("native_preview_unavailable")

    def run(self, args):
        result = self.inspect(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
