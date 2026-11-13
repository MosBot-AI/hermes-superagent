"""Dial policy for a native Bot sender hosted in the isolated acceptance Gateway."""

import os
import sys
from pathlib import Path

from native_bot_socket_guard import activate


class FixturePorts:
    def __init__(self, root, model_port):
        self.owner_port = root / "gateway-port"
        self.model_port = model_port

    def __contains__(self, port):
        if port == self.model_port:
            return True
        try:
            return port == int(self.owner_port.read_text(encoding="ascii"))
        except FileNotFoundError:
            return False


def activate_push_child():
    root = Path(os.environ["HERMES_BOT_ACCEPTANCE_ROOT"])
    model_port = int(os.environ["HERMES_BOT_ACCEPTANCE_MODEL_PORT"])
    if not 1 <= model_port <= 65535:
        raise ValueError("Invalid private Bot model port")
    activate(root, dial_ports=FixturePorts(root, model_port), dial_host="127.0.0.1")
    try:
        sys.audit("socket.getaddrinfo", "blocked.invalid")
    except PermissionError:
        (root / f"socket-guard-{os.getpid()}").touch(mode=0o600, exist_ok=False)
    else:
        raise RuntimeError("Private Bot reply socket audit is inactive")
