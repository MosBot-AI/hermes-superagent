"""Simulation CLI is a diagnostic, never a voice activation or credential flow."""

import argparse
import json

import pytest

from personal_agent.plugin import run_cli, setup_cli
from personal_agent.status import build_status


def test_offline_self_test_report_and_exit_code(capsys):
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    assert run_cli(parser.parse_args(["voice", "self-test"])) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "personal.voice.self-test.v1"
    assert report["simulation"] is True
    assert report["status"] == "ok"
    assert report["checks"] and all(row["passed"] is True for row in report["checks"])
    assert report["live_voice_enabled"] is False
    assert report["microphone_used"] is False
    assert report["provider_calls"] == report["native_turns_submitted"] == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ["voice"],
        ["voice", "start"],
        ["voice", "self-test", "--api-key", "synthetic-secret"],
        ["voice", "self-test", "--provider", "online"],
        ["voice", "self-test", "--microphone"],
        ["voice", "self-test", "--profile", "voice_local_example"],
    ],
)
def test_unknown_actions_and_activation_arguments_are_rejected(arguments):
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    with pytest.raises(SystemExit) as result:
        parser.parse_args(arguments)
    assert result.value.code == 2


def test_failed_simulation_exits_nonzero(capsys, monkeypatch):
    import personal_agent.voice

    monkeypatch.setattr(personal_agent.voice, "run_voice_self_test", lambda: {"status": "failed"})
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    assert run_cli(parser.parse_args(["voice", "self-test"])) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_simulation_never_changes_production_readiness():
    status = build_status()
    assert status["voice"]["synthetic_self_test_implemented"] is True
    assert status["voice"]["live_voice_enabled"] is False
    assert status["voice"]["provider_connections_enabled"] is False
    assert status["capabilities"]["identity_binding"] is False
    assert status["safety"]["release_gate"] == "blocked"
