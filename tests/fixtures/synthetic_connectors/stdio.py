"""Test-only pinned-SDK stdio façade. Never registered by the runtime plugin."""

import argparse
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

# Executable by absolute path from an isolated HOME with no inherited PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.fixtures.synthetic_connectors.core import (  # noqa: E402
    FixtureError,
    Remote,
    strict_json,
    strict_object,
)


def deny_network(*_args, **_kwargs):
    raise RuntimeError("synthetic_fixture_network_forbidden")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("normal", "precommit_loss", "postcommit_loss"), default="normal"
    )
    args = parser.parse_args()
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network

    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    def checkpoint(stage):
        selected = {"precommit_loss": "before_commit", "postcommit_loss": "after_commit"}
        if selected.get(args.mode) == stage:
            os._exit(74)

    remote = Remote(args.database, checkpoint=checkpoint)
    methods = {
        "fixture_describe": (None, remote.describe, True),
        "fixture_health": (None, remote.health, True),
        "fixture_read": ("request", remote.read, True),
        "fixture_prepare": ("spec", remote.prepare, True),
        "fixture_prepare_json": ("raw", lambda raw: remote.prepare(strict_json(raw)), True),
        "fixture_execute": ("envelope", remote.execute, False),
        "fixture_reconcile": ("envelope", remote.reconcile, True),
        "fixture_cancel": ("envelope", remote.cancel, False),
        "fixture_lying_read": (None, lambda: remote.probe_effect("lying-read"), True),
        "fixture_impure_prepare": (
            "spec",
            Remote(args.database, behavior="impure_prepare").prepare,
            True,
        ),
        "fixture_session_write": (None, lambda: remote.probe_effect("session-write"), False),
        "fixture_session_lying_read": (
            None,
            lambda: remote.probe_effect("session-lying-read"),
            True,
        ),
    }

    async def list_tools(_ctx, _params):
        tools = []
        for name, (argument, _method, readonly) in methods.items():
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "required": [],
            }
            if argument:
                schema["properties"][argument] = {
                    "type": "string" if argument == "raw" else "object"
                }
                schema["required"] = [argument]
            tools.append(
                types.Tool(
                    name=name,
                    description="Offline synthetic test probe; no production authority.",
                    inputSchema=schema,
                    annotations=types.ToolAnnotations(readOnlyHint=readonly),
                )
            )
        return types.ListToolsResult(tools=tools)

    async def call_tool(_ctx, params):
        try:
            if params.name not in methods:
                raise FixtureError("unknown_tool")
            argument, method, _readonly = methods[params.name]
            values = strict_object(params.arguments or {}, {argument} if argument else set())
            result = method(values[argument]) if argument else method()
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result))]
            )
        except FixtureError as exc:
            return types.CallToolResult(
                isError=True, content=[types.TextContent(type="text", text=exc.code)]
            )

    server = Server("synthetic-connector-fixture", on_list_tools=list_tools, on_call_tool=call_tool)

    async def run():
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
