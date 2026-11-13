"""Synthetic fault gate after result persistence and before native completion admission."""

import asyncio
import errno
import json
import os
import runpy
from pathlib import Path

import utils
from gateway.run_notifications import GatewayNotificationsMixin
from gateway.session_context import clear_session_vars, set_session_vars
from tools import process_registry_results
from tools.process_registry import process_registry

root = Path(os.environ["HERMES_BOT_ACCEPTANCE_ROOT"])
results = Path(os.environ["HERMES_HOME"]) / "profiles/scout/logs/process-results"
original_enqueue = GatewayNotificationsMixin._enqueue_process_completion_notification
original_result_write = process_registry_results.atomic_json_write
original_checkpoint_write = utils.atomic_json_write


def write_checkpoint(path, record, **kwargs):
    if (
        path == results.parent.parent / "processes.json"
        and (root / "fail-bot-checkpoint").is_file()
    ):
        (root / "bot-checkpoint-write-failed").touch(mode=0o600)
        raise OSError(errno.ENOSPC, "Synthetic Bot checkpoint write failure")
    return original_checkpoint_write(path, record, **kwargs)


def write_process_result(path, record, **kwargs):
    fault = root / "fail-finished-result"
    if (
        path.parent == results
        and fault.is_file()
        and path.stem == fault.read_text(encoding="ascii")
    ):
        (root / "finished-result-write-failed").touch(mode=0o600)
        raise OSError(errno.ENOSPC, "Synthetic Bot result write failure")
    return original_result_write(path, record, **kwargs)


async def block_bot_completion(self, text, event):
    if event.get("platform") == "local" and "Synthetic recipient's push reply" in event.get(
        "output", ""
    ):
        if (root / "admit-finished-waiter").is_file():
            assert await original_enqueue(self, text, event) is True
        pid = event["session_id"]
        ready = root / "finished-waiter"
        staged = ready.with_suffix(".tmp")
        staged.write_text(json.dumps([pid, event["started_at"]]), encoding="ascii")
        staged.replace(ready)
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
process_registry_results.atomic_json_write = write_process_result
utils.atomic_json_write = write_checkpoint
runpy.run_module("gateway.run", run_name="__main__")
