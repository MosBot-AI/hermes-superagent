"""Process-local socket audit fence for the manual Bot Gateway acceptance."""

import ipaddress
import os
import socket
import sys
from pathlib import Path


def activate(root, *, dial_ports=None, dial_host=None):
    root = root.resolve()
    active = True

    def local_only(event, args):
        if not active:
            return
        if event in {"socket.connect", "socket.bind", "socket.sendto"}:
            peer, address = args
            if peer.family in (socket.AF_INET, socket.AF_INET6):
                host, port = address[:2]
                if not ipaddress.ip_address(host).is_loopback:
                    raise PermissionError("Native Bot fixture is loopback only")
                if dial_ports is not None and event != "socket.bind" and port not in dial_ports:
                    raise PermissionError("Native Bot fixture dial port is not permitted")
                if dial_host is not None and event != "socket.bind" and host != dial_host:
                    raise PermissionError("Native Bot fixture dial host is not permitted")
            elif peer.family == socket.AF_UNIX:
                if not isinstance(address, str) or not Path(address).resolve().is_relative_to(root):
                    raise PermissionError("Native Bot fixture Unix paths must be private")
            else:
                raise PermissionError("Native Bot fixture does not use this socket family")
        elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            if args[0] not in (None, "localhost", "127.0.0.1", "::1"):
                raise PermissionError("Native Bot fixture DNS is disabled")

    sys.addaudithook(local_only)

    def deactivate():
        nonlocal active
        active = False

    return deactivate


def activate_child():
    root = Path(os.environ["HERMES_BOT_ACCEPTANCE_ROOT"])
    model_port = os.environ.get("HERMES_BOT_ACCEPTANCE_MODEL_PORT")
    gateway_port = os.environ.get("HERMES_NATIVE_ACCEPTANCE_DIAL_PORT")
    if model_port is not None and gateway_port is not None:
        raise SystemExit("A native fixture child may dial only one declared endpoint")
    port = gateway_port if gateway_port is not None else model_port
    try:
        dial_ports = () if port is None else (int(port),)
    except ValueError:
        raise SystemExit("Native fixture dial port must be an integer") from None
    activate(
        root,
        dial_ports=dial_ports,
        dial_host="127.0.0.1" if gateway_port is not None else None,
    )
    try:
        sys.audit("socket.getaddrinfo", "blocked.invalid")
    except PermissionError:
        (root / f"socket-guard-{os.getpid()}").touch(mode=0o600)
