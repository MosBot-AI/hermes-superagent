"""Real native registration of the offline voice self-test, not a voice session."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_local_task_cli import configure, entry, invoke
from test_local_task_cli import native as native


@pytest.mark.parametrize("mode", ["default", "read_only", "local_tasks"])
def test_native_cli_self_test_does_not_open_storage_or_change_settings(
    native, capsys, monkeypatch, mode
):
    home, manager = native
    configure(home, mode)
    before = (home / "config.yaml").read_bytes()
    command = entry(manager)
    forbidden = Mock(side_effect=AssertionError("synthetic voice tried to open task storage"))
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    code, result = invoke(command, capsys, "voice", "self-test")
    assert code == 0
    assert result["simulation"] is True
    assert result["status"] == "ok"
    assert result["live_voice_enabled"] is False
    assert result["provider_calls"] == result["native_turns_submitted"] == 0
    forbidden.assert_not_called()
    assert (home / "config.yaml").read_bytes() == before
    assert not (home / "plugin-data").exists()


def test_real_top_level_cli_runs_only_offline_simulation(native, tmp_path):
    from hermes_cli import main

    home, _ = native
    upstream = Path(main.__file__).resolve().parents[1]
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_PYTHON": sys.executable,
        "HERMES_BUNDLED_PLUGINS": os.environ["HERMES_BUNDLED_PLUGINS"],
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
    }
    bootstrap = """
import socket, sys
def refuse(*args, **kwargs):
    raise AssertionError('Voice self-test must not connect to the network')
socket.create_connection = refuse
socket.socket.connect = refuse
socket.socket.connect_ex = refuse
sys.argv = ['hermes', 'personal-agent', 'voice', 'self-test']
from hermes_cli.main import main
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=upstream,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "personal.voice.self-test.v1"
    assert payload["simulation"] is True
    assert payload["microphone_used"] is False
    assert payload["provider_calls"] == 0
    assert not (home / "plugin-data").exists()
