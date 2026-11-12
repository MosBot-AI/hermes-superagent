"""Process custody for the manual native Gateway socket checks."""

import socket
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from urllib.parse import urlsplit

import pytest


@contextmanager
def gateway_daemon(host, home, child_env, label):
    from gateway.status import get_process_start_time, terminate_pid, write_planned_stop_marker
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_cli.gateway_runtime_discovery import query_identify

    # Logs stay in this private test directory. Never echo them into pytest or JUnit.
    log_path = home.parent / f"{label}.log"
    with log_path.open("w", encoding="utf-8") as log:
        log_path.chmod(0o600)
        process = subprocess.Popen(
            [sys.executable, "-m", "gateway.run"],
            cwd=host,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            umask=0o077,
        )
        initial_start = None
        try:
            deadline = time.monotonic() + 60
            while process.poll() is None and time.monotonic() < deadline:
                initial_start = initial_start or get_process_start_time(process.pid)
                observed = discover_gateway_endpoint(home, timeout=1)
                if observed.state == "ready":
                    endpoint = observed.endpoint
                    break
                time.sleep(0.1)
            else:
                pytest.fail(f"{label}: owned Gateway readiness was not established", pytrace=False)
            assert endpoint is not None
            origin = urlsplit(endpoint.api_origin)
            assert origin.scheme == "http" and origin.hostname == "127.0.0.1" and origin.port
            assert endpoint.profile_id == str(home) and endpoint.runtime_protocol == 1
            assert "session-authority-v1" in endpoint.capabilities
            identity = query_identify(home, timeout=2)
            assert (
                identity["pid"] == process.pid and identity["instance_id"] == endpoint.instance_id
            )
            assert initial_start and get_process_start_time(process.pid) == initial_start
            assert (home.parent / f"socket-guard-{process.pid}").is_file()
            yield endpoint
            assert process.poll() is None and get_process_start_time(process.pid) == initial_start
            assert write_planned_stop_marker(process.pid)
            assert process.wait(timeout=35) == 0
            assert discover_gateway_endpoint(home, timeout=2).state == "absent"
            assert not (home / "gateway.pid").exists()
            with pytest.raises(ConnectionRefusedError):
                with socket.create_connection(("127.0.0.1", origin.port), timeout=2):
                    pass
        finally:
            if process.poll() is None:
                # Failure cleanup owns only the child we launched and never counts as planned stop.
                if initial_start is not None:
                    with suppress(ProcessLookupError):
                        terminate_pid(process.pid, force=True, expected_start_time=initial_start)
                else:
                    process.kill()
                process.wait(timeout=8)
