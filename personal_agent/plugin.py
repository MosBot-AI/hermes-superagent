"""Thin native registration layer using documented PluginContext methods only."""

import argparse
import inspect
import json
from typing import Any, Protocol

from .enforcement import build_enforcement_inventory
from .identity import build_access_diagnostic
from .routing_cli import RoutingInspector, setup_routing_cli
from .routing_inspection import inspection_failure
from .status import build_status, validate_kanban_configuration
from .task_backup import run_backup_cli, setup_backup_cli
from .task_cli import current_profile_home, run_tasks_cli, setup_tasks_cli
from .voice_cli import run_voice_cli, setup_voice_cli


def plan_worker_host_status(ctx):
    """Inspect the narrow public contract, never resolve a route or create a client."""
    try:
        service = getattr(ctx, "subagent_lifecycle", None)
        marker = inspect.getattr_static(type(service), "text_worker_contract", None)
        if (
            not isinstance(marker, property)
            or marker.fset is not None
            or marker.fdel is not None
            or getattr(service, "text_worker_contract", None) != "hermes.text-worker.v1"
        ):
            return "unsupported_host"
        if not all(
            callable(getattr(service, name, None))
            for name in ("launch_text", "authorize_text_route", "result")
        ):
            return "unsupported_host"
        consent = getattr(ctx, "has_capability", None)
        if not callable(consent) or consent("llm.text_worker") is not True:
            return "consent_required"
        return "available"
    except Exception:
        return "host_check_failed"


class PluginContext(Protocol):
    """The small host surface consumed here, not a replacement host interface."""

    def get_config(self, key: str, default: Any = None) -> Any: ...

    def register_automation_blueprint(self, **kwargs: Any) -> Any: ...

    def register_tool(self, **kwargs: Any) -> Any: ...

    def on_unload(self, callback: Any) -> Any: ...

    def register_cli_command(self, **kwargs: Any) -> Any: ...

    def register_command(self, name: str, handler: Any, **kwargs: Any) -> Any: ...

    def register_hook(self, hook_name: str, callback: Any, **kwargs: Any) -> Any: ...


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


def _status_result(
    args: dict[str, object],
    mode: str,
    *,
    local_conversation: bool = False,
    local_model_tools: bool = False,
    local_memory: bool = False,
    memory_model_tools: bool = False,
    memory_candidates: bool = False,
    kanban_handoff: bool = False,
    kanban_handoff_board: str = "",
    plan_worker: bool = False,
    plan_worker_registered: bool = False,
    plan_worker_host: str = "not_checked",
) -> str:
    if not isinstance(args, dict) or args:
        return json.dumps(
            {
                "status": "blocked",
                "error": {"code": "invalid_arguments", "retryable": False},
                "summary": "personal_agent_status takes no arguments.",
            }
        )
    return json.dumps(
        build_status(
            mode=mode,
            local_conversation=local_conversation,
            local_model_tools=local_model_tools,
            local_memory=local_memory,
            memory_model_tools=memory_model_tools,
            memory_candidates=memory_candidates,
            kanban_handoff=kanban_handoff,
            kanban_handoff_board=kanban_handoff_board,
            plan_worker=plan_worker,
            plan_worker_registered=plan_worker_registered,
            plan_worker_host=plan_worker_host,
        ),
        ensure_ascii=False,
        sort_keys=True,
    )


def setup_cli(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="personal_command", required=True)
    subparsers.add_parser("status", help="Show the read-only foundation status as JSON")
    subparsers.add_parser("coverage", help="Show blocked write paths and baseline evidence as JSON")
    subparsers.add_parser("access", help="Explain the still-blocked owner/receiving-Bot boundary")
    setup_tasks_cli(subparsers)
    setup_backup_cli(subparsers)
    setup_voice_cli(subparsers)
    setup_routing_cli(subparsers)


def run_cli(args: argparse.Namespace) -> int | None:
    if args.personal_command == "task-backup":
        print(json.dumps({"status": "error", "error": {"code": "host_context_unavailable"}}))
        return 1
    if args.personal_command == "routing":
        print(json.dumps(inspection_failure("host_inspection_unavailable"), sort_keys=True))
        return 1
    if args.personal_command == "voice":
        return run_voice_cli(args)
    if args.personal_command == "coverage":
        print(json.dumps(build_enforcement_inventory(), ensure_ascii=False, sort_keys=True))
    elif args.personal_command == "access":
        print(access_command(""))
    else:
        print(status_tool({}))


def register(ctx: PluginContext) -> None:
    """Explicit local entry points; model tools additionally need session activation."""
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
    model_tools_enabled = ctx.get_config("local_model_tools", False)
    if type(model_tools_enabled) is not bool:
        raise ValueError("local_model_tools must be a boolean")
    if model_tools_enabled and not conversation_enabled:
        raise ValueError("local_model_tools requires local_conversation and local_tasks")
    worker_enabled = ctx.get_config("plan_worker", False)
    if type(worker_enabled) is not bool or (worker_enabled and not model_tools_enabled):
        raise ValueError("plan_worker must be boolean and requires local_model_tools")
    worker_registered = False
    worker_host = plan_worker_host_status(ctx) if worker_enabled else "not_checked"
    memory_enabled = ctx.get_config("local_memory", False)
    if type(memory_enabled) is not bool:
        raise ValueError("local_memory must be a boolean")
    if memory_enabled and not conversation_enabled:
        raise ValueError("local_memory requires local_conversation and local_tasks")
    memory_models_enabled = ctx.get_config("memory_model_tools", False)
    if type(memory_models_enabled) is not bool:
        raise ValueError("memory_model_tools must be a boolean")
    if memory_models_enabled and not memory_enabled:
        raise ValueError("memory_model_tools requires local_memory and local_conversation")
    candidates_enabled = ctx.get_config("memory_candidates", False)
    if type(candidates_enabled) is not bool:
        raise ValueError("memory_candidates must be a boolean")
    if candidates_enabled and not memory_models_enabled:
        raise ValueError("memory_candidates requires memory_model_tools and local_memory")
    handoff_enabled = ctx.get_config("kanban_handoff", False)
    handoff_board = ctx.get_config("kanban_handoff_board", "")
    validate_kanban_configuration(
        ctx.get_config("mode", "read_only"), conversation_enabled, handoff_enabled, handoff_board
    )
    bound_home = current_profile_home()
    routing_inspector = RoutingInspector(bound_home)
    ctx.on_unload(routing_inspector.close)

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
            local_model_tools = ctx.get_config("local_model_tools", False)
            if type(local_model_tools) is not bool or (
                local_model_tools and not local_conversation
            ):
                raise ValueError("invalid local model tools configuration")
            local_memory = ctx.get_config("local_memory", False)
            if type(local_memory) is not bool or (local_memory and not local_conversation):
                raise ValueError("invalid local memory configuration")
            memory_model_tools = ctx.get_config("memory_model_tools", False)
            if type(memory_model_tools) is not bool or (memory_model_tools and not local_memory):
                raise ValueError("invalid memory model tools configuration")
            memory_candidates = ctx.get_config("memory_candidates", False)
            if type(memory_candidates) is not bool or (
                memory_candidates and not memory_model_tools
            ):
                raise ValueError("invalid memory candidates configuration")
            handoff = ctx.get_config("kanban_handoff", False)
            board = ctx.get_config("kanban_handoff_board", "")
            validate_kanban_configuration(mode, local_conversation, handoff, board)
            worker = ctx.get_config("plan_worker", False)
            if type(worker) is not bool or (worker and not local_model_tools):
                raise ValueError("invalid plan worker configuration")
            return _status_result(
                args,
                mode,
                local_conversation=local_conversation,
                local_model_tools=local_model_tools,
                local_memory=local_memory,
                memory_model_tools=memory_model_tools,
                memory_candidates=memory_candidates,
                kanban_handoff=handoff,
                kanban_handoff_board=board,
                plan_worker=worker,
                plan_worker_registered=worker_registered,
                plan_worker_host=plan_worker_host_status(ctx) if worker else "not_checked",
            )
        except Exception:
            return json.dumps({"status": "blocked", "error": {"code": "invalid_configuration"}})

    def registered_cli(args: argparse.Namespace) -> int | None:
        if args.personal_command == "routing":
            return routing_inspector.run(args)
        if args.personal_command == "task-backup":
            return run_backup_cli(
                args, read_mode=lambda: ctx.get_config("mode", "read_only"), bound_home=bound_home
            )
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
        from .kanban_handoff import LocalKanbanHandoff

        handoff = LocalKanbanHandoff(bound_home=bound_home, read_config=ctx.get_config)
        ctx.on_unload(handoff.close)
        ctx.register_command(
            "personal-handoff",
            handler=handoff.command,
            description="Explicitly park a local task on a shared native board; no dispatch.",
            args_hint="prepare | commit | reconcile | sync | show | list | cancel",
        )

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
                default_format="text",
            )

        ctx.register_command(
            "personal-tasks",
            handler=local_tasks_command,
            description=(
                "Manage tasks/project groups in an explicitly trusted single-user local session."
            ),
            args_hint="[--json] <command> [arguments]",
        )

    if memory_enabled:
        from .conversation_memory import LocalMemoryCommands

        memory = LocalMemoryCommands(bound_home=bound_home, read_config=ctx.get_config)
        ctx.on_unload(memory.close)
        ctx.register_command(
            "personal-memory",
            handler=memory.command,
            description="Explicitly save, inspect, correct or forget local operator records.",
            args_hint=(
                "remember | list | search | recall | changes | show | "
                "correct | forget | export | candidate-list | candidate-show | "
                "candidate-accept | candidate-discard | candidate-purge-expired | help"
            ),
        )

    if memory_models_enabled:
        from .memory_tool_contract import PERSONAL_MEMORY_READ_SCHEMA, PERSONAL_MEMORY_WRITE_SCHEMA
        from .session_memory_recall import RecallingSessionMemoryTools

        schemas = [PERSONAL_MEMORY_READ_SCHEMA, PERSONAL_MEMORY_WRITE_SCHEMA]
        if candidates_enabled:
            from .memory_candidate_tool_contract import PERSONAL_MEMORY_CANDIDATE_SCHEMA
            from .session_memory_candidates import CandidateSessionMemoryTools

            memory_access = CandidateSessionMemoryTools(
                bound_home=bound_home, read_config=ctx.get_config
            )
            ctx.register_hook("post_llm_call", memory_access.clear_turn_context)
            schemas.append(PERSONAL_MEMORY_CANDIDATE_SCHEMA)
        else:
            memory_access = RecallingSessionMemoryTools(
                bound_home=bound_home, read_config=ctx.get_config
            )
        ctx.on_unload(memory_access.close)
        ctx.register_hook("pre_llm_call", memory_access.turn_context)
        ctx.register_command(
            "personal-memory-tools",
            handler=memory_access.command,
            description="Separately activate memory model access in this trusted native session.",
            args_hint=(
                "enable-read | enable-write | recall-on | recall-off | "
                "candidate-on | candidate-off | disable | status"
            ),
        )

        def bind_memory_handler(name):
            def handler(args, *, session_id="", task_id="", **context):
                return memory_access.run(
                    name, args, session_id=session_id, task_id=task_id, **context
                )

            return handler

        for schema in schemas:
            ctx.register_tool(
                name=schema["name"],
                toolset="personal_agent",
                schema=schema,
                handler=bind_memory_handler(schema["name"]),
                description="Bounded memory access after separate native session activation.",
            )

    if model_tools_enabled:
        from .task_focus import FocusedSessionTaskTools
        from .task_tool_contract import PERSONAL_TASKS_READ_SCHEMA, PERSONAL_TASKS_WRITE_SCHEMA

        access = FocusedSessionTaskTools(bound_home=bound_home, read_config=ctx.get_config)
        ctx.on_unload(access.close)
        ctx.register_hook("pre_llm_call", access.turn_context)
        ctx.register_command(
            "personal-tools",
            handler=access.command,
            description="Activate local task model access for this trusted native session.",
            args_hint=(
                "enable-read | enable-write | focus <task-id> | clear-focus | disable | status"
            ),
        )

        def bind_handler(name):
            def handler(args, *, session_id="", task_id="", **context):
                return access.run(name, args, session_id=session_id, task_id=task_id, **context)

            return handler

        for schema in (PERSONAL_TASKS_READ_SCHEMA, PERSONAL_TASKS_WRITE_SCHEMA):
            ctx.register_tool(
                name=schema["name"],
                toolset="personal_agent",
                schema=schema,
                handler=bind_handler(schema["name"]),
                description="Bounded task access after explicit native session activation.",
            )

    if worker_enabled and worker_host == "available":
        from .task_plan_worker import register as register_plan_worker

        register_plan_worker(ctx)
        worker_registered = True
