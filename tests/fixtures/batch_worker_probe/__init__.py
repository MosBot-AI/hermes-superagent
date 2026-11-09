"""Synthetic effects only; the loader and hook admission remain native."""

import json

HOOKS = []
EFFECTS = []
DENIED = {"denied"}


def guard(tool_name, args, **context):
    if tool_name in {"batch_worker_probe", "connectors__batchfixture__effect"}:
        HOOKS.append((dict(args), context.get("session_id")))
        if args["item"] in DENIED:
            return {"action": "block", "message": "synthetic item veto"}
    return None


def handler(args, **_context):
    EFFECTS.append(args["item"])
    if args.get("lose_response"):
        raise RuntimeError("synthetic response lost after effect")
    return json.dumps({"effect": args["item"]})


def register(ctx):
    ctx.register_hook("pre_tool_call", guard)
    ctx.register_tool(
        name="batch_worker_probe",
        toolset="batch_worker_probe",
        schema={
            "name": "batch_worker_probe",
            "description": "Record synthetic in-memory effect",
            "parameters": {
                "type": "object",
                "properties": {"item": {"type": "string"}, "lose_response": {"type": "boolean"}},
                "required": ["item"],
            },
        },
        handler=handler,
    )
