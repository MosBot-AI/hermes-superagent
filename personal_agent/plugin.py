"""Thin native registration layer using documented PluginContext methods only."""

import argparse
import json
from typing import Any, Protocol

from .enforcement import build_enforcement_inventory
from .status import build_status
from .task_cli import current_profile_home, run_tasks_cli, setup_tasks_cli


class PluginContext(Protocol):
    """The small host surface consumed here, not a replacement host interface."""

    def get_config(self, key: str, default: Any = None) -> Any: ...

    def register_tool(self, **kwargs: Any) -> Any: ...

    def register_cli_command(self, **kwargs: Any) -> Any: ...


def status_tool(args: dict[str, object], **_context: object) -> str:
    """Hermes handlers return strings. Do not reflect caller content into output."""
    return _status_result(args, "read_only")


def _status_result(args: dict[str, object], mode: str) -> str:
    if not isinstance(args, dict) or args:
        return json.dumps(
            {
                "status": "blocked",
                "error": {"code": "invalid_arguments", "retryable": False},
                "summary": "personal_agent_status takes no arguments.",
            }
        )
    return json.dumps(build_status(mode=mode), ensure_ascii=False, sort_keys=True)


def setup_cli(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="personal_command", required=True)
    subparsers.add_parser("status", help="Show the read-only foundation status as JSON")
    subparsers.add_parser("coverage", help="Show blocked write paths and baseline evidence as JSON")
    setup_tasks_cli(subparsers)


def run_cli(args: argparse.Namespace) -> None:
    if args.personal_command == "coverage":
        print(json.dumps(build_enforcement_inventory(), ensure_ascii=False, sort_keys=True))
    else:
        print(status_tool({}))


def register(ctx: PluginContext) -> None:
    """Local storage is opt-in and CLI-only; register no personal-data tools."""
    if ctx.get_config("mode", "read_only") not in ("read_only", "local_tasks"):
        raise ValueError("hermes-personal-agent supports only read_only or local_tasks mode")
    bound_home = current_profile_home()

    def registered_status(args: dict[str, object], **_context: object) -> str:
        if not isinstance(args, dict) or args:
            return _status_result(args, "read_only")
        try:
            if not bound_home.is_dir() or current_profile_home() != bound_home:
                return json.dumps(
                    {"status": "blocked", "error": {"code": "profile_context_changed"}}
                )
            mode = ctx.get_config("mode", "read_only")
            if mode not in ("read_only", "local_tasks"):
                raise ValueError("invalid mode")
            return _status_result(args, mode)
        except Exception:
            return json.dumps({"status": "blocked", "error": {"code": "invalid_configuration"}})

    def registered_cli(args: argparse.Namespace) -> int | None:
        if args.personal_command == "tasks":
            return run_tasks_cli(
                args,
                read_mode=lambda: ctx.get_config("mode", "read_only"),
                bound_home=bound_home,
            )
        if args.personal_command == "status":
            result = registered_status({})
            print(result)
            if json.loads(result).get("status") == "blocked":
                return 1
        else:
            run_cli(args)
        return None

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
        handler=registered_status,
        description="Read-only personal-agent readiness",
    )
    ctx.register_cli_command(
        name="personal-agent",
        help="Inspect the personal-agent foundation and opt-in local tasks",
        setup_fn=setup_cli,
        handler_fn=registered_cli,
        description="Diagnostics and opt-in local task inbox; no external actions.",
    )
