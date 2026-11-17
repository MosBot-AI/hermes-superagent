"""Pause one native admission after claim and before executing it."""

import asyncio
import json
import os
import runpy
import sys
from pathlib import Path

from native_bot_socket_guard import activate_child


def run():
    activate_child()
    sys.path.insert(0, str(Path.cwd()))

    from gateway.session_authority import SessionAuthority

    marker = Path(os.environ["HERMES_BOT_ACCEPTANCE_ROOT"]) / "claimed.json"

    async def pause_claim(_authority, ref, _live, row):
        assert row["request_id"] == "fixture-lost-head"
        assert row["status"] == "started" and ref.session_id == row["target_session_id"]
        record = {"admission_id": row["admission_id"], "generation": row["generation"]}
        staged = marker.with_suffix(".tmp")
        with staged.open("x", encoding="ascii") as output:
            json.dump(record, output)
        staged.replace(marker)
        await asyncio.Event().wait()

    SessionAuthority._execute_claimed = pause_claim
    runpy.run_module("gateway.run", run_name="__main__")


if __name__ == "__main__":
    run()
