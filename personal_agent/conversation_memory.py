"""Explicit operator memory edits in trusted native LOCAL sessions only.

This does not authenticate a human or create owner authority. The host owns
session admission; every already admitted controller shares local access.
Review commands can explicitly promote model-proposed drafts, never grant authority.
No model call, native memory bridge or automatic canonical write occurs here.
"""

import argparse
import json
import shlex
import threading
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from .conversation_tasks import _supported_origin
from .memory_backend import MemoryError, MemoryService, validate_request
from .memory_storage import open_memory_backend
from .task_cli import current_profile_home

HELP = (
    'remember "Text" [--topic LABEL] [--expires-at UTC] [--request-id KEY]; '
    "list [--include-expired --limit N --after ID]; "
    'search "Text" [--include-expired --limit N --after ID]; show ID; '
    'recall "Keyword" ["Other keyword" ...] [--limit N --max-chars N]; '
    "changes [--after-sequence N --through-sequence N --limit N]; "
    "checkpoint --expected-watermark N [--request-id KEY]; checkpoint-status ID; "
    'correct ID [--text "Replacement"] [--topic LABEL] [--expires-at UTC | --clear-expiry] '
    "--expected-revision N "
    "[--request-id KEY]; forget ID --expected-revision N [--request-id KEY]; "
    "export [--limit N --after ID]. Use POSIX quotes. "
    "candidate-list [--limit N --after ID]; candidate-show ID; "
    "candidate-accept ID --expected-revision N (--keep | --expires-at UTC); "
    "candidate-discard ID --expected-revision N; candidate-purge-expired. "
    "Candidates are untrusted model drafts with source quotes, not verified facts or grants. "
    "Review before accepting; --keep explicitly chooses no canonical expiry. "
    "Acceptance and canonical memory creation are one transaction; identical retries return "
    "historical metadata and never restore a subsequently forgotten record. "
    "Draft/quote payload expires after seven days and is cleared on a later successful "
    "candidate operation or explicit purge, "
    "not by a background timer. Acceptance/discard also clear candidate payload; minimal "
    "deduplication metadata remains, capped at 1000 retained candidates. "
    "Recall ranks 1-8 distinct literal keywords; defaults to 6 whole records and a 6000-character "
    "ASCII JSON items budget, not tokens. It reports omitted matches and is not semantic search. "
    "Checkpoints cover local record metadata only, not native conversations or backups. "
    "Expiry uses an explicit UTC YYYY-MM-DDTHH:MM:SSZ timestamp; no default is inferred. "
    "Expired records are excluded from ordinary list/search/recall, not deleted. "
    "Use --include-expired or show to inspect, correct --clear-expiry to restore eligibility, "
    "or forget to clear canonical payload. Expiry does not erase previous model context. "
    "Writes return metadata receipts, not remembered content. Generated request IDs are "
    "echoed; reuse the same key and payload for an uncertain result, never retry blindly. "
    "Explicit local operator records only, not verified facts or permission grants. "
    "Commands and results may enter native session history. No automatic model recall, "
    "extraction, native MEMORY/USER edits or provider replacement. Forget clears this "
    "store's payload, not already delivered results, host history, backups or exports."
)


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise MemoryError("invalid_request")

    def exit(self, status=0, message=None):
        raise MemoryError("invalid_request")

    def _print_message(self, message, file=None):
        pass


def parse_command(raw_args: str) -> tuple[str, dict]:
    if type(raw_args) is not str or len(raw_args) > 8192 or "\x00" in raw_args:
        raise MemoryError("invalid_request")
    try:
        tokens = shlex.split(raw_args, comments=False, posix=True)
    except ValueError:
        raise MemoryError("invalid_request") from None
    if len(tokens) > 40:
        raise MemoryError("invalid_request")
    if not tokens or tokens in (["help"], ["--help"], ["-h"]):
        return "help", {}
    parser = _Parser(prog="/personal-memory")
    commands = parser.add_subparsers(dest="operation", required=True)
    remember = commands.add_parser("remember")
    remember.add_argument("content")
    remember.add_argument("--topic", default="")
    remember.add_argument("--expires-at", default=argparse.SUPPRESS)
    remember.add_argument("--request-id")
    show = commands.add_parser("show")
    show.add_argument("record_id")
    for operation in ("list", "search", "export"):
        reader = commands.add_parser(operation)
        if operation == "search":
            reader.add_argument("query")
        if operation in ("list", "search"):
            reader.add_argument("--include-expired", action="store_true", default=argparse.SUPPRESS)
        reader.add_argument("--limit", type=int, default=20)
        reader.add_argument("--after", default=None)
    recall = commands.add_parser("recall")
    recall.add_argument("queries", nargs="+")
    recall.add_argument("--limit", type=int, default=6)
    recall.add_argument("--max-chars", type=int, default=6000)
    changes = commands.add_parser("changes")
    changes.add_argument("--after-sequence", type=int, default=0)
    changes.add_argument("--through-sequence", type=int, default=None)
    changes.add_argument("--limit", type=int, default=20)
    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("--expected-watermark", type=int, required=True)
    checkpoint.add_argument("--request-id")
    checkpoint_status = commands.add_parser("checkpoint-status")
    checkpoint_status.add_argument("checkpoint_id")
    candidates = commands.add_parser("candidate-list")
    candidates.add_argument("--limit", type=int, default=20)
    candidates.add_argument("--after", default=None)
    candidate_show = commands.add_parser("candidate-show")
    candidate_show.add_argument("candidate_id")
    for operation in ("candidate-accept", "candidate-discard"):
        review = commands.add_parser(operation)
        review.add_argument("candidate_id")
        review.add_argument("--expected-revision", type=int, required=True)
        if operation == "candidate-accept":
            retention = review.add_mutually_exclusive_group(required=True)
            retention.add_argument("--keep", dest="expires_at", action="store_const", const=None)
            retention.add_argument("--expires-at")
    commands.add_parser("candidate-purge-expired")
    for operation in ("correct", "forget"):
        writer = commands.add_parser(operation)
        writer.add_argument("record_id")
        writer.add_argument("--expected-revision", type=int, required=True)
        writer.add_argument("--request-id")
        if operation == "correct":
            writer.add_argument("--text", dest="content", default=argparse.SUPPRESS)
            writer.add_argument("--topic", default=argparse.SUPPRESS)
            expiry = writer.add_mutually_exclusive_group()
            expiry.add_argument("--expires-at", default=argparse.SUPPRESS)
            expiry.add_argument(
                "--clear-expiry",
                dest="expires_at",
                action="store_const",
                const=None,
                default=argparse.SUPPRESS,
            )
    payload = vars(parser.parse_args(tokens))
    operation = payload.pop("operation")
    if operation == "show":
        operation = "get"
    operation = {"checkpoint": "checkpoint_create", "checkpoint-status": "checkpoint_status"}.get(
        operation, operation
    )
    operation = {
        "candidate-list": "candidate_list",
        "candidate-show": "candidate_get",
        "candidate-accept": "candidate_accept",
        "candidate-discard": "candidate_discard",
        "candidate-purge-expired": "candidate_purge_expired",
    }.get(operation, operation)
    if (
        operation in ("remember", "correct", "forget", "checkpoint_create")
        and payload["request_id"] is None
    ):
        payload["request_id"] = str(uuid4())
    return operation, validate_request(operation, payload)


def _bound_key() -> str:
    from gateway.session_context import bound_session_key  # ty: ignore[unresolved-import]

    return bound_session_key()


class LocalMemoryCommands:
    """Serialize unload with bounded operations; already admitted work may finish."""

    def __init__(self, *, bound_home: Path, read_config: Callable[[str, object], object]):
        self._home = bound_home
        self._config = read_config
        self._lock = threading.RLock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def command(
        self,
        raw_args: str,
        *,
        platform: str = "",
        source: object = None,
        session_id: str = "",
        session_key: str = "",
    ) -> str:
        request_id = None
        operation = None
        try:
            with self._lock:
                if self._closed:
                    raise MemoryError("local_memory_unloaded")
                if (
                    platform != "local"
                    or not _supported_origin(platform, source, session_id, session_key)
                    or not session_key
                    or _bound_key() != session_key
                ):
                    raise MemoryError("unsupported_origin")
                if not self._home.is_dir() or current_profile_home() != self._home:
                    raise MemoryError("profile_context_changed")
                mode = self._config("mode", "read_only")
                conversation = self._config("local_conversation", False)
                memory = self._config("local_memory", False)
                if (
                    mode not in ("read_only", "local_tasks")
                    or type(conversation) is not bool
                    or type(memory) is not bool
                    or (conversation and mode != "local_tasks")
                    or (memory and not conversation)
                ):
                    raise MemoryError("invalid_configuration")
                if mode != "local_tasks" or not conversation or not memory:
                    raise MemoryError("local_memory_disabled")
                operation, payload = parse_command(raw_args)
                request_id = payload.get("request_id")
                if operation == "help":
                    result = {"data": {"help": HELP}, "replayed": False}
                else:
                    with open_memory_backend(self._home, session_id) as backend:
                        result = MemoryService(backend).execute(operation, payload)
                output = {"status": "ok", **result, "error": None}
        except Exception as error:
            if not isinstance(error, MemoryError):
                error = MemoryError("local_memory_unavailable")
            output = {
                "status": "error",
                "data": None,
                "replayed": False,
                "error": {"code": error.code, "retryable": error.retryable},
            }
        return json.dumps(
            {
                "schema_version": "personal.local-memory.v1",
                "scope": "trusted_local_operator_records",
                "request_id": request_id,
                **output,
            },
            # Review must show the proposed text and quote legibly, including
            # Chinese. JSON still escapes controls and never evaluates content.
            ensure_ascii=not (operation and operation.startswith("candidate_")),
            indent=2 if operation and operation.startswith("candidate_") else None,
            sort_keys=True,
        )
