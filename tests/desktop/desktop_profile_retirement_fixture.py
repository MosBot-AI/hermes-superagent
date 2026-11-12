"""Native control and independent ownership observations in the Desktop fixture."""

import fcntl
import json
import socket
import sqlite3
from contextlib import closing
from pathlib import Path

PROFILE = "scout"
INSTALL_ID = "7" * 32


def _homes():
    from hermes_constants import get_hermes_home

    root = get_hermes_home().resolve()
    assert root == (Path.home() / ".hermes").resolve(), "fixture uses its own HOME"
    assert (root / "install_id").read_text().strip() == INSTALL_ID, "owned install is required"
    assert [name for _, name in socket.if_nameindex()] == ["lo"], "loopback namespace is required"
    return {"default": root, PROFILE: root / "profiles" / PROFILE}


def _lock_held(home):
    try:
        with (home / "gateway.lock").open("rb") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream, fcntl.LOCK_UN)
    except FileNotFoundError:
        pass
    return False


def _epoch(home):
    with closing(sqlite3.connect((home / "state.db").as_uri() + "?mode=ro", uri=True)) as db:
        return db.execute(
            "SELECT epoch, instance_id FROM runtime_epoch WHERE singleton=1"
        ).fetchone()


def inspect():
    from hermes_cli.gateway_runtime_discovery import query_identify

    homes = _homes()
    root = homes["default"]
    state = query_identify(root, timeout=1)
    if state is None:
        return None
    names = {str(home): name for name, home in homes.items()}
    advertised = sorted(names[entry["profile_id"]] for entry in state["served_profiles"])
    recorded = json.loads((root / "gateway_state.json").read_text())["served_profiles"]
    return {
        "pid": state["pid"],
        "instanceId": state["instance_id"],
        "advertised": advertised,
        "recorded": sorted(recorded),
        "locks": {name: _lock_held(home) for name, home in homes.items()},
        "epochs": {name: _epoch(home) for name, home in homes.items()},
        "parked": (homes[PROFILE] / "gateway.parked").is_file(),
    }


def change_serving(serve):
    from gateway.control_socket import request_serve_profile_hot, request_unserve_profile
    from hermes_cli.profiles import parked_marker_path

    homes = _homes()
    marker = parked_marker_path(homes[PROFILE])
    if serve:
        marker.unlink()
        response = request_serve_profile_hot(homes["default"], PROFILE)
        key = "served"
        watcher_race = f"profile '{PROFILE}' is already served"
    else:
        marker.touch(mode=0o600, exist_ok=False)
        response = request_unserve_profile(homes["default"], PROFILE)
        key = "unserved"
        watcher_race = f"profile '{PROFILE}' is not served"
    assert response, "the owned host answered the private lifecycle control"
    # A concurrent housekeeping reconciliation can apply the same marker intent.
    assert (
        response.get(key) == PROFILE
        or response.get("pending") is True
        or response.get("error") == watcher_race
    ), "the native lifecycle transition was accepted or already reconciled"
