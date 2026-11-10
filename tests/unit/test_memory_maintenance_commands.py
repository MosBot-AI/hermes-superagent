"""Strict explicit operator command surface for current-store maintenance."""

import pytest

from personal_agent.conversation_memory import HELP, parse_command
from personal_agent.memory_backend import MemoryError


@pytest.mark.parametrize(
    "text, operation, payload",
    [
        ("maintenance-preview", "maintenance_preview", {}),
        (
            "maintenance-prepare repack-1 --expected-watermark 5",
            "maintenance_prepare",
            {"name": "repack-1", "expected_watermark": 5},
        ),
        ("maintenance-commit repack-1", "maintenance_commit", {"name": "repack-1"}),
        ("maintenance-status repack-1", "maintenance_status", {"name": "repack-1"}),
        ("maintenance-recover repack-1", "maintenance_recover", {"name": "repack-1"}),
    ],
)
def test_explicit_maintenance_parser(text, operation, payload):
    assert parse_command(text) == (operation, payload)


@pytest.mark.parametrize(
    "text",
    [
        "maintenance-prepare x",
        "maintenance-prepare x --expected-watermark -1",
        "maintenance-commit ../x",
        "maintenance-status /tmp/x",
        "maintenance-recover x --rollback",
        "maintenance-prepare x --expected-watermark 0 --source y",
        "maintenance-preview --path x",
    ],
)
def test_no_implicit_source_restore_or_arbitrary_path(text):
    with pytest.raises(MemoryError, match="invalid_request"):
        parse_command(text)


def test_help_exposes_deployment_pending_and_retention_limits():
    assert "Stop old runtimes" in HELP
    assert "never historical restore" in HELP
    assert "blocks ordinary memory" in HELP
    assert "retain private plaintext" in HELP
