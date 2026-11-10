"""Deterministic commands for an explicitly trusted single-user local profile.

The public fields are routing filters, not authentication or profile ownership
proof. Native LOCAL sessions rely on the host's registered live-source checks,
session:read/session:control authorization and admission gate before dispatch.
Already-authorized host controllers share access; LOCAL does not prove physical
locality. Exposed/multi-user gateways, non-LOCAL messaging and model tools are
unsupported, as is hostile same-process/same-UID code. Only explicit commands
read or mutate tasks. Nothing is automatically injected into model context.
"""

import argparse
import json
import re
import shlex
import unicodedata
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from uuid import uuid4

from .task_cli import command_request, current_profile_home, open_task_store, setup_tasks_cli
from .task_presentation import render_task_result
from .tasks import TaskError

MAX_RAW_ARGUMENTS = 32768
MAX_TOKENS = 256
_SESSION = re.compile(r"[A-Za-z0-9._-]{1,128}")
_WRITES = frozenset(("capture", "update", "complete", "cancel", "progress"))
HELP = (
    'Use POSIX quotes: add "Title" [--details "Text"] [--project "Project"] '
    "[--priority high|normal|low] [--due-date YYYY-MM-DD]; "
    "list [--state all] [--project LABEL | --unassigned]; "
    'search "Text"; show TASK_ID; projects; agenda --on YYYY-MM-DD; '
    'plan --project "Project" --task "First" --task "Second" --request-id KEY '
    "(1-20 tasks, one atomic write; a stable request ID is required); "
    "--tasks-json accepts explicit depends_on one-based positions in the same batch; "
    "array order alone creates no prerequisites. JSON tasks may specify priority high|normal|low; "
    "omitted priority is normal for new tasks, never inherited from a parent. "
    "breakdown TASK_ID --expected-revision N (--tasks-json JSON | --task TITLE [--task TITLE...]) "
    "--request-id KEY records explicit steps atomically in the parent's existing named project. "
    "The parent must be captured and not in_progress. Every step inherits all existing "
    "prerequisites; the parent keeps them and gains every new step as a prerequisite. "
    "No automatic parent completion, execution or copying of parent details. "
    "A stable explicit request key is required. "
    "review --on YYYY-MM-DD [--lookahead-days N] [--per-bucket-limit N] [--max-chars N]; "
    "native-review --on YYYY-MM-DD [--stale-after-days N] [--per-bucket-limit N] "
    "[--max-chars N] [--project LABEL | --unassigned] reads saved observations only; "
    "it never refreshes the board or changes task completion. "
    "history TASK_ID [--limit N] [--after-revision N] (operation metadata only). "
    "Readers support --limit and --after where applicable. "
    "list/search/agenda/review accept --work-status ready|in_progress|waiting|blocked "
    "for active tasks. "
    'progress TASK_ID --expected-revision N --work-status STATUS --note "Progress or blocker"; '
    "update TASK_ID --expected-revision N [--title TITLE] [--details TEXT] "
    "[--priority high|normal|low] [--project LABEL | --clear-project] "
    "[--due-date YYYY-MM-DD | --clear-due]; "
    'done TASK_ID --expected-revision N --note "Reason"; '
    'cancel TASK_ID --expected-revision N --note "Reason". '
    "add is an alias for capture; done is an alias for complete. "
    "Projects are task label groups, not native Project entities. "
    "project-reschedule-preview --project LABEL --days N reviews all date changes; "
    "reschedule-project --project LABEL --days N --expected-snapshot HASH --request-id KEY "
    "shifts only captured dated tasks, with explicit nonzero -3650..3650 days. "
    "project-rename-preview --project OLD --new-project NEW returns a bounded whole-group "
    "snapshot; rename-project --project OLD --new-project NEW --expected-snapshot HASH "
    "--request-id KEY atomically relabels every active and terminal task, preserving edges. "
    "Destination must be unused; preview again after any source task changes. "
    "Writes accept --request-id KEY. "
    "For capture/update/complete/cancel/progress, if omitted a fresh key is returned. "
    "dependencies TASK_ID --expected-revision N (--needs ID [--needs ID...] | --clear) "
    "--request-id KEY replaces the whole prerequisite set (0-20, same named project, no cycles). "
    "A stable explicit key is required. Starting or completing requires all prerequisites done; "
    "cancelled prerequisites block. ready [--project LABEL | --unassigned] lists captured "
    "tasks with recorded ready status and all prerequisites done, oldest first, not priority. "
    "next [--limit N] [--project LABEL | --unassigned] returns the top eligible ready tasks "
    "by explicit high/normal/low priority, due date (undated last), then capture order. "
    "Default 5, maximum 20; no cursor or automatic selection/dispatch. "
    "Priority is an explicit local planning label, not permission. "
    "progress/update accept --follow-up-on YYYY-MM-DD or --clear-follow-up-on. "
    "A date is allowed only on active waiting/blocked tasks; ready/in_progress/done/cancel "
    "clear it. It is separate from the deadline, not an automatic reminder. "
    "followups --on YYYY-MM-DD [--limit N] [--project LABEL | --unassigned] shows due "
    "waiting/blocked follow-ups (default 20, maximum 100; no cursor). No implied today, "
    "automatic status change, cron, outreach or dispatch. "
    "Dependencies never start work or advance tasks automatically. "
    "For an uncertain outcome, reuse that exact "
    "key and identical command manually; a fresh key may duplicate capture. "
    "No automatic retries. Dates are explicit, not inferred. Local storage only. "
    "Native conversation output defaults to readable text; "
    "prefix the command with --json for structured results, including admission errors."
)


class _SilentParser(argparse.ArgumentParser):
    """No argparse printing or SystemExit, including in nested subparsers."""

    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise TaskError("invalid_request")

    def exit(self, status=0, message=None):
        raise TaskError("invalid_request")

    def _print_message(self, message, file=None):
        pass


def _parse(raw_args: str) -> tuple[str, dict, str | None]:
    if type(raw_args) is not str or len(raw_args) > MAX_RAW_ARGUMENTS or "\x00" in raw_args:
        raise TaskError("invalid_request")
    try:
        tokens = shlex.split(raw_args, comments=False, posix=True)
    except ValueError:
        raise TaskError("invalid_request") from None
    if len(tokens) > MAX_TOKENS:
        raise TaskError("invalid_request")
    machine = bool(tokens and tokens[0] == "--json")
    if machine:
        tokens.pop(0)
    if not tokens:
        return "help", {}, "json" if machine else None
    if tokens[0] in ("help", "--help", "-h"):
        parser = _SilentParser(prog="/personal-tasks")
        parser.add_argument("--format", choices=("json", "text"), default=None)
        selected = parser.parse_args(tokens[1:]).format
        if machine and selected == "text":
            raise TaskError("invalid_request")
        return "help", {}, "json" if machine else selected
    tokens[0] = {"add": "capture", "done": "complete"}.get(tokens[0], tokens[0])
    # Positional convenience is deliberately narrow. The complete existing CLI
    # syntax stays available, including --title=-value for leading dashes.
    if tokens[0] in ("capture", "search") and len(tokens) > 1 and not tokens[1].startswith("-"):
        tokens.insert(1, "--title" if tokens[0] == "capture" else "--query")
    if tokens[0] in _WRITES and not any(
        token == "--request-id" or token.startswith("--request-id=") for token in tokens
    ):
        tokens.extend(("--request-id", str(uuid4())))
    parser = _SilentParser(prog="/personal-tasks")
    setup_tasks_cli(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(["tasks", *tokens])
    operation, payload = command_request(args)
    if machine and args.output_format == "text":
        raise TaskError("invalid_request")
    return operation, payload, "json" if machine else args.output_format


def _bounded_identifier(value: object, maximum: int) -> bool:
    """Opaque routing/principal text, never a filename or authentication token."""
    return (
        type(value) is str
        and 0 < len(value) <= maximum
        and bool(value.strip())
        and not any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value)
    )


def _supported_origin(
    platform: object, source: object, session_id: object, session_key: object
) -> bool:
    if type(platform) is not str or type(session_id) is not str:
        return False
    if _SESSION.fullmatch(session_id) is None:
        return False
    if platform == "cli":
        # Legacy direct callback; not the normal gateway-backed CLI/TUI path.
        return source is None and type(session_key) is str and session_key == session_id
    if platform != "local" or source is None or not _bounded_identifier(session_key, 1024):
        return False
    try:
        source_platform = getattr(source, "platform", None)
        if isinstance(source_platform, Enum):
            source_platform = source_platform.value
        if type(source_platform) is not str or source_platform != platform:
            return False
        if getattr(source, "chat_type", None) != "dm":
            return False
        for field in ("is_bot", "delivered_via_upstream_relay", "profile_route_rejected"):
            if getattr(source, field, None) is not False:
                return False
        for field in (
            "thread_id",
            "parent_chat_id",
            "scope_id",
            "guild_id",
            "detached_route",
            "prospective_thread_id",
        ):
            if getattr(source, field, None) not in (None, ""):
                return False
        chat_id = getattr(source, "chat_id", None)
        return _bounded_identifier(chat_id, 256) and _bounded_identifier(
            getattr(source, "user_id", None), 256
        )
    except Exception:
        return False


def run_conversation_tasks(
    raw_args: str,
    *,
    read_config: Callable[[str, object], object],
    bound_home: Path,
    platform: str = "",
    source: object = None,
    session_id: str = "",
    session_key: str = "",
    default_format: str = "json",
) -> str:
    """Reply once without model calls, transcript injection, or external effects.

    Registration must also require mode=local_tasks and local_conversation=True.
    A callback retained after config/profile changes is revalidated here. The
    normal CLI/TUI/Desktop path is a host-authorized native LOCAL session; the
    classic direct CLI fallback passes source=None and equal session ID/key.
    Public source fields are not credentials. Source.profile is not an owner
    claim: the host-selected current profile must equal registration's home.
    """
    request_id = None
    operation, payload = "", {}
    # Only this public presentation prefix is inspected before admission. Do
    # not parse, echo or act on the private command until origin/profile gates.
    machine = (
        type(raw_args) is str
        and re.match(r"^[ \t]{0,32}--json(?:[ \t\r\n]|$)", raw_args[:64]) is not None
    )
    output_format = "json" if machine else default_format
    try:
        # Reject origin before parsing private arguments or consulting config.
        if not _supported_origin(platform, source, session_id, session_key):
            raise TaskError("unsupported_origin")
        # Host configuration reads may recreate a removed profile.
        if not bound_home.is_dir() or current_profile_home() != bound_home:
            raise TaskError("profile_context_changed")
        mode = read_config("mode", "read_only")
        enabled = read_config("local_conversation", False)
        if (
            mode not in ("read_only", "local_tasks")
            or type(enabled) is not bool
            or (enabled and mode != "local_tasks")
        ):
            raise TaskError("invalid_configuration")
        if mode != "local_tasks" or not enabled:
            raise TaskError("local_conversation_disabled")
        operation, payload, explicit_format = _parse(raw_args)
        output_format = explicit_format or default_format
        request_id = payload.get("request_id")
        if operation == "help":
            result = {"data": {"help": HELP}, "replayed": False}
        else:
            with open_task_store(bound_home) as store:
                result = store.run(operation, payload)
        output = {"status": "ok", **result, "error": None}
    except Exception as error:
        if not isinstance(error, TaskError):
            error = TaskError("local_tasks_unavailable")
        output = {
            "status": "error",
            "data": None,
            "replayed": False,
            "error": {"code": error.code, "retryable": error.retryable},
        }
    envelope = {
        "schema_version": "personal.local-conversation-tasks.v1",
        "scope": "trusted_local_conversation",
        "request_id": request_id,
        **output,
    }
    if output_format == "text":
        return render_task_result(envelope, operation=operation, payload=payload)
    return json.dumps(
        envelope,
        # Escape terminal control characters as well as non-ASCII data.
        ensure_ascii=True,
        sort_keys=True,
    )
