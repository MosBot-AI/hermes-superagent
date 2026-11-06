"""Disabled storage must do no host imports or filesystem work."""

import argparse
from pathlib import Path

import pytest

from personal_agent import enrollment_storage
from personal_agent.enrollment import EnrollmentError
from personal_agent.plugin import setup_cli
from personal_agent.status import build_status


@pytest.mark.parametrize("enabled", [False, None, 0, 1, "true", [], {}])
def test_disabled_and_malformed_gate_precedes_all_path_and_host_work(monkeypatch, enabled):
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled persistence reached the filesystem or host")

    monkeypatch.setattr(Path, "is_dir", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(enrollment_storage, "_profile_home", forbidden)
    monkeypatch.setattr(enrollment_storage.os, "open", forbidden)
    with pytest.raises(EnrollmentError) as error:
        with enrollment_storage.open_enrollment_store(Path("/synthetic-home"), enabled=enabled):
            pytest.fail("Unreachable")
    assert error.value.code == (
        "enrollment_storage_disabled" if enabled is False else "invalid_configuration"
    )


def test_gate_defaults_to_disabled():
    with pytest.raises(EnrollmentError, match="enrollment_storage_disabled"):
        with enrollment_storage.open_enrollment_store(Path("/nonexistent-synthetic-home")):
            pytest.fail("Unreachable")


@pytest.mark.parametrize("command", ["enrollment", "policy", "grant", "activate"])
def test_no_production_cli_for_enrollment_or_activation(command):
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    with pytest.raises(SystemExit) as error:
        parser.parse_args([command])
    assert error.value.code == 2


@pytest.mark.parametrize("mode", ["read_only", "local_tasks"])
def test_status_distinguishes_storage_core_from_live_authority(mode):
    result = build_status(mode=mode)
    assert result["enrollment_policy"] == {
        "persistence_core_implemented": True,
        "production_adapter_enabled": False,
        "activation_supported": False,
        "grant_issuance_supported": False,
        "scope": "Unwired pending/revoked metadata only; profiles are not authenticated owners.",
    }
    assert result["read_authorization"]["protected_reads_enabled"] is False
    assert result["capabilities"]["identity_binding"] is False


def test_unsupported_platform_stops_before_path_resolution(monkeypatch):
    monkeypatch.setattr(enrollment_storage.os, "name", "nt")
    with pytest.raises(EnrollmentError, match="unsupported_storage_platform"):
        with enrollment_storage.open_enrollment_store(None, enabled=True):
            pytest.fail("Unreachable")
