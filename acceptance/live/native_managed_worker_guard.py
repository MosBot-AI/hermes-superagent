"""Fixture-only startup audit for the owned Gateway and its named worker."""

import os
import sys
from pathlib import Path

from native_bot_socket_guard import activate


def activate_managed_child():
    try:
        root = Path(os.environ["HERMES_MANAGED_FIXTURE_ROOT"])
        model_port = int(os.environ["HERMES_MANAGED_FIXTURE_MODEL_PORT"])
        is_worker = sys.orig_argv[-2:] == ["-m", "agent.managed_worker"]
        ports = (model_port,)
        if is_worker:
            owner_port = int((root / "gateway-port").read_text(encoding="ascii"))
            if Path(os.environ["HERMES_HOME"]) != root / "h/profiles/scout":
                raise ValueError("unexpected named worker home")
            ports += (owner_port,)
        if any(not 1 <= port <= 65535 for port in ports):
            raise ValueError("invalid fixture port")

        activate(root, dial_ports=ports, dial_host="127.0.0.1")
        try:
            sys.audit("socket.getaddrinfo", "blocked.invalid")
        except PermissionError:
            (root / f"socket-guard-{os.getpid()}").touch(mode=0o600, exist_ok=False)
        else:
            raise ValueError("fixture socket audit inactive")
    except KeyError, OSError, ValueError:
        # sitecustomize prints and suppresses ordinary exceptions.
        raise SystemExit("Could not activate the managed-worker fixture socket audit") from None
