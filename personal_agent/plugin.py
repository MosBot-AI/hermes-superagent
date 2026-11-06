"""Thin native registration layer using documented PluginContext methods only."""

import argparse
import json
from typing import Any, Protocol

from .enforcement import build_enforcement_inventory
from .identity import build_access_diagnostic
from .status import build_status
from .task_cli import current_profile_home, run_tasks_cli, setup_tasks_cli
from .voice_cli import run_voice_cli, setup_voice_cli


class PluginContext(Protocol):
    """The small host surface consumed here, not a replacement host interface."""

    def get_config(self, key: str, default: Any = None) -> Any: ...

    def register_automation_blueprint(self, **kwargs: Any) -> Any: ...

    def register_tool(self, **kwargs: Any) -> Any: ...

    def register_cli_command(self, **kwargs: Any) -> Any: ...

    def register_command(self, name: str, handler: Any, **kwargs: Any) -> Any: ...


def access_command(
    raw_args: str,
    *,
    platform: str = "",
    source: object = None,
    session_id: str = "",
    session_key: str = "",
) -> str:
    """Public slash diagnostic only; never resolves owner, grants or task data."""
    return json.dumps(
        build_access_diagnostic(
            raw_args,
            platform=platform,
            source=source,
            session_id=session_id,
            session_key=session_key,
        ),
        sort_keys=True,
    )


def status_tool(args: dict[str, object], **_context: object) -> str:
    """Hermes handlers return strings. Do not reflect caller content into output."""
    return _status_result(args, "read_only")


def _status_result(args: dict[str, object], mode: str, *, local_conversation: bool = False) -> str:
    if not isinstance(args, dict) or args:
        return json.dumps(
            {
                "status": "blocked",
                "error": {"code": "invalid_arguments", "retryable": False},
                "summary": "personal_agent_status takes no arguments.",
            }
        )
    return json.dumps(
        build_status(mode=mode, local_conversation=local_conversation),
        ensure_ascii=False,
        sort_keys=True,
    )


def setup_cli(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="personal_command", required=True)
    subparsers.add_parser("status", help="Show the read-only foundation status as JSON")
    subparsers.add_parser("coverage", help="Show blocked write paths and baseline evidence as JSON")
    subparsers.add_parser("access", help="Explain the still-blocked owner/receiving-Bot boundary")
    setup_tasks_cli(subparsers)
    setup_voice_cli(subparsers)


def run_cli(args: argparse.Namespace) -> int | None:
    if args.personal_command == "voice":
        return run_voice_cli(args)
    if args.personal_command == "coverage":
        print(json.dumps(build_enforcement_inventory(), ensure_ascii=False, sort_keys=True))
    elif args.personal_command == "access":
        print(access_command(""))
    else:
        print(status_tool({}))


def register(ctx: PluginContext) -> None:
    """Local storage/conversation commands are opt-in; no personal-data model tools."""
    if ctx.get_config("mode", "read_only") not in ("read_only", "local_tasks"):
        raise ValueError("hermes-personal-agent supports only read_only or local_tasks mode")
    planning_enabled = ctx.get_config("planning_blueprint", False)
    if type(planning_enabled) is not bool:
        raise ValueError("planning_blueprint must be a boolean")
    conversation_enabled = ctx.get_config("local_conversation", False)
    if type(conversation_enabled) is not bool:
        raise ValueError("local_conversation must be a boolean")
    if conversation_enabled and ctx.get_config("mode", "read_only") != "local_tasks":
        raise ValueError("local_conversation requires local_tasks mode")
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
            local_conversation = ctx.get_config("local_conversation", False)
            if type(local_conversation) is not bool or (
                local_conversation and mode != "local_tasks"
            ):
                raise ValueError("invalid local conversation configuration")
            return _status_result(args, mode, local_conversation=local_conversation)
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
            return run_cli(args)
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
        help="Inspect the foundation, opt-in local tasks and synthetic voice checks",
        setup_fn=setup_cli,
        handler_fn=registered_cli,
        description="Diagnostics and opt-in local task inbox; no external actions.",
    )
    ctx.register_command(
        "personal-access",
        handler=access_command,
        description="Explain protected-access blockers without reading personal data.",
        args_hint="[status]",
    )

    if planning_enabled:
        from .blueprints import planning_check_in

        ctx.register_automation_blueprint(**planning_check_in())

    if conversation_enabled:
        from .conversation_tasks import run_conversation_tasks

        def local_tasks_command(
            raw_args: str,
            *,
            platform: str = "",
            source: object = None,
            session_id: str = "",
            session_key: str = "",
        ) -> str:
            return run_conversation_tasks(
                raw_args,
                read_config=ctx.get_config,
                bound_home=bound_home,
                platform=platform,
                source=source,
                session_id=session_id,
                session_key=session_key,
            )

        ctx.register_command(
            "personal-tasks",
            handler=local_tasks_command,
            description=(
                "Manage tasks/project groups in an explicitly trusted single-user local session."
            ),
            args_hint="<command> [arguments]",
        )
