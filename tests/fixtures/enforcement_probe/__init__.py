"""Test-only native plugin. Its sole tool records calls in memory, never external I/O."""

import json
import threading

TOOL_NAME = "enforcement_probe"
HOOK_MODE = "allow"
MIDDLEWARE_MODE = "allow"
HOOK_CALLS = []
HANDLER_CALLS = []
MIDDLEWARE_CALLS = []
HOOK_THREADS = []
STARTED = threading.Event()
RELEASE = threading.Event()


def guard(tool_name, args, **_context):
    if tool_name != TOOL_NAME:
        return None
    HOOK_CALLS.append(dict(args))
    HOOK_THREADS.append(threading.current_thread())
    if HOOK_MODE == "block":
        return {"action": "block", "message": "synthetic policy denial"}
    if HOOK_MODE == "exception":
        raise RuntimeError("synthetic policy exception")
    if HOOK_MODE == "system_exit":
        raise SystemExit("synthetic policy exit")
    if HOOK_MODE == "wait":
        STARTED.set()
        if not RELEASE.wait(timeout=20):
            raise RuntimeError("test did not release its callback")
    return None


def execution(tool_name, args, next_call, **_context):
    if tool_name != TOOL_NAME:
        return next_call(args)
    MIDDLEWARE_CALLS.append(dict(args))
    if MIDDLEWARE_MODE == "raise_before":
        raise RuntimeError("synthetic middleware exception before dispatch")
    result = next_call(args)
    if MIDDLEWARE_MODE == "raise_after":
        raise RuntimeError("synthetic middleware exception after dispatch")
    if MIDDLEWARE_MODE == "call_twice":
        return next_call(args)
    return result


def handler(args, **_context):
    HANDLER_CALLS.append(dict(args))
    return json.dumps({"ran": len(HANDLER_CALLS)})


def register(ctx):
    ctx.register_hook("pre_tool_call", guard)
    ctx.register_middleware("tool_execution", execution)
    ctx.register_tool(
        name=TOOL_NAME,
        toolset="enforcement_probe",
        schema={
            "name": TOOL_NAME,
            "description": "Record a synthetic call in memory only",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=handler,
    )
