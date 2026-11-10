"""Fresh pre-import policy binding and offline guards for production-package probes.

This is not an installed plugin. It runs assertions from the contract file without
adding that repository to sys.path, so only the staged namespaced package can load.
"""

import importlib.util
import json
import os
import runpy
import socket
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


def main():
    host, contract, scenario, variant = sys.argv[1:]
    sys.path.insert(0, host)
    assert importlib.util.find_spec("personal_agent") is None
    assert "SYNTHETIC_TEST_CREDENTIAL" not in os.environ
    home = Path(os.environ["HERMES_HOME"])
    snapshot = json.loads((home / "config.yaml").read_text())
    safe = scenario == "safe" or variant == "safe_opt_in"
    if scenario in {"frozen", "safe"} or safe:
        from agent.managed_worker import bind_worker_policy

        bind_worker_policy(
            {
                "safe_mode": safe,
                "ignore_user_config": safe or variant == "config_only",
                "policy": {"config_json": json.dumps(snapshot)},
            }
        )

    attempts = []

    def forbidden(*_args, **_kwargs):
        attempts.append("network/process/storage")
        raise AssertionError("Production exposure probes forbid external effects and SQLite")

    socket.create_connection = forbidden
    socket.getaddrinfo = forbidden
    socket.socket.bind = forbidden
    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden
    subprocess.Popen = forbidden
    sqlite3.connect = forbidden

    # croniter asks the stdlib to run `file` just to determine pointer width.
    # Supply that host fact without allowing a subprocess in the probe.
    with patch("platform.architecture", return_value=(f"{8 * struct.calcsize('P')}bit", "")):
        __import__("croniter")

    # urllib3 otherwise binds ::1 at import solely to detect IPv6 availability.
    with patch.object(socket, "has_ipv6", False):
        __import__("urllib3")

    from agent.plugin_llm import PluginLlm
    from agent.subagent_lifecycle import SubagentLifecycleService
    from cron import jobs, scheduler
    from hermes_cli.plugins import get_plugin_manager

    def fallback(*_args, **_kwargs):
        attempts.append("worker/llm fallback")
        raise AssertionError("No generic worker or LLM fallback is allowed")

    manager = get_plugin_manager()
    # These inert refusal endpoints are in place before actual registration.
    with (
        patch.object(SubagentLifecycleService, "launch", fallback),
        patch.object(PluginLlm, "complete", fallback),
        patch.object(PluginLlm, "acomplete", fallback),
        patch.object(PluginLlm, "complete_structured", fallback),
        patch.object(PluginLlm, "acomplete_structured", fallback),
        patch.object(jobs, "create_job", forbidden),
        patch.object(scheduler, "create_job_with_scheduler_registration", forbidden),
    ):
        try:
            manager.discover_and_load()
            runpy.run_path(contract)["probe_" + scenario](manager, home, variant)
        finally:
            manager.unload()
        assert attempts == [], attempts
    assert importlib.util.find_spec("personal_agent") is None
    assert not any(
        name == "personal_agent" or name.startswith("personal_agent.") for name in sys.modules
    )
    print("PRODUCTION_EXPOSURE_OK")


if __name__ == "__main__":
    main()
