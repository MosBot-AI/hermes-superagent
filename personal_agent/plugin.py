"""Thin native registration layer using documented PluginContext methods only."""

import argparse
import json
from typing import Any, Protocol

from .enforcement import build_enforcement_inventory
from .status import build_status


class PluginContext(Protocol):
    """The small host surface consumed here, not a replacement host interface."""

    def get_config(self, key: str, default: Any = None) -> Any: ...

    def register_tool(self, **kwargs: Any) -> Any: ...

    def register_cli_command(self, **kwargs: Any) -> Any: ...


def status_tool(args: dict[str, object], **_context: object) -> str:
    """Hermes handlers return strings. Do not reflect caller content into output."""
    if not isinstance(args, dict) or args:
        return json.dumps(
            {
                "status": "blocked",
                "error": {"code": "invalid_arguments", "retryable": False},
                "summary": "personal_agent_status takes no arguments.",
            }
        )
    return json.dumps(build_status(), ensure_ascii=False, sort_keys=True)


def setup_cli(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="personal_command", required=True)
    subparsers.add_parser("status", help="Show the read-only foundation status as JSON")
    subparsers.add_parser("coverage", help="Show blocked write paths and baseline evidence as JSON")


def run_cli(args: argparse.Namespace) -> None:
    if args.personal_command == "coverage":
        print(json.dumps(build_enforcement_inventory(), ensure_ascii=False, sort_keys=True))
    else:
        print(status_tool({}))


def register(ctx: PluginContext) -> None:
    """Reject unsupported mode before registering anything; never enable writes."""
    if ctx.get_config("mode", "read_only") != "read_only":
        raise ValueError("hermes-personal-agent supports only mode: read_only")

    ctx.register_tool(
        name="personal_agent_status",
        toolset="personal_agent",
        schema={
            "name": "personal_agent_status",
            "description": (
                "Show this plugin's development readiness and unsupported capabilities. "
                "Does not read personal data or prove that other Hermes tools are safe."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        handler=status_tool,
        description="Read-only personal-agent readiness",
    )
    ctx.register_cli_command(
        name="personal-agent",
        help="Inspect the personal-agent foundation",
        setup_fn=setup_cli,
        handler_fn=run_cli,
        description="Read-only diagnostics; no personal data or external actions.",
    )
