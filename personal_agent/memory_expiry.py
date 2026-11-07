"""Trusted wall-clock eligibility, not monotonic deletion or a background job."""

from datetime import UTC, datetime


def utc_now() -> str:
    """Capture one canonical UTC second; callers cannot supply time authority."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
