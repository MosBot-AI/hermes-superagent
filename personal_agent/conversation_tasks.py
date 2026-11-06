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
from .tasks import TaskError

MAX_RAW_ARGUMENTS = 32768
MAX_TOKENS = 256
_SESSION = re.compile(r"[A-Za-z0-9._-]{1,128}")
_WRITES = frozenset(("capture", "update", "complete", "cancel"))
HELP = (
    'Use POSIX quotes: add "Title" [--details "Text"] [--project "Project"] '
    "[--due-date YYYY-MM-DD]; list [--state all] [--project LABEL | --unassigned]; "
    'search "Text"; show TASK_ID; projects; agenda --on YYYY-MM-DD. '
    "Readers support --limit and --after where applicable. "
    "update TASK_ID --expected-revision N [--title TITLE] [--details TEXT] "
    "[--project LABEL | --clear-project] [--due-date YYYY-MM-DD | --clear-due]; "
    'done TASK_ID --expected-revision N --note "Reason"; '
    'cancel TASK_ID --expected-revision N --note "Reason". '
    "add is an alias for capture; done is an alias for complete. "
    "Projects are task label groups, not native Project entities. "
    "Writes accept --request-id KEY. "
    "If omitted a fresh key is returned. For an uncertain outcome, reuse that exact "
    "key and identical command manually; a fresh key may duplicate capture. "
    "No automatic retries. Dates are explicit, not inferred. Local storage only."
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


def _parse(raw_args: str) -> tuple[str, dict]:
    if type(raw_args) is not str or len(raw_args) > MAX_RAW_ARGUMENTS or "\x00" in raw_args:
        raise TaskError("invalid_request")
    try:
        tokens = shlex.split(raw_args, comments=False, posix=True)
    except ValueError:
        raise TaskError("invalid_request") from None
    if len(tokens) > MAX_TOKENS:
        raise TaskError("invalid_request")
    if not tokens or tokens in (["help"], ["--help"], ["-h"]):
        return "help", {}
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
    return command_request(parser.parse_args(["tasks", *tokens]))


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
        operation, payload = _parse(raw_args)
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
    return json.dumps(
        {
            "schema_version": "personal.local-conversation-tasks.v1",
            "scope": "trusted_local_conversation",
            "request_id": request_id,
            **output,
        },
        # Escape terminal control characters as well as non-ASCII data.
        ensure_ascii=True,
        sort_keys=True,
    )
