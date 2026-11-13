"""Synthetic fault gate after result persistence and before native completion admission."""

import asyncio
import json
import os
import runpy
from pathlib import Path

from gateway.run_notifications import GatewayNotificationsMixin
from gateway.session_context import clear_session_vars, set_session_vars
from tools.process_registry import process_registry

root = Path(os.environ["HERMES_BOT_ACCEPTANCE_ROOT"])
original_enqueue = GatewayNotificationsMixin._enqueue_process_completion_notification


async def block_bot_completion(self, text, event):
    if event.get("platform") == "local" and "Synthetic recipient's push reply" in event.get(
        "output", ""
    ):
        if (root / "admit-finished-waiter").is_file():
            assert await original_enqueue(self, text, event) is True
        pid = event["session_id"]
        ready = root / "finished-waiter"
        ready.write_text(pid, encoding="ascii")
        async with asyncio.timeout(90):
            while True:
                consume = root / "consume-finished-waiter"
                if consume.is_file():
                    # Invoke the real process output read under the original session context.
                    tokens = set_session_vars(
                        platform="local", session_id=event["parent_session_id"]
                    )
                    try:
                        result = await asyncio.to_thread(process_registry.read_log, pid)
                    finally:
                        clear_session_vars(tokens)
                    proof = root / "consumed-waiter"
                    staged = proof.with_suffix(".tmp")
                    staged.write_text(json.dumps(result), encoding="utf-8")
                    staged.replace(proof)
                    consume.unlink()
                await asyncio.sleep(0.05)
    return await original_enqueue(self, text, event)


GatewayNotificationsMixin._enqueue_process_completion_notification = block_bot_completion
runpy.run_module("gateway.run", run_name="__main__")
