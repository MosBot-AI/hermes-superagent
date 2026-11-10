"""Explicit operator memory edits in trusted native LOCAL sessions only.

This does not authenticate a human or create owner authority. The host owns
session admission; every already admitted controller shares local access.
Review commands can explicitly promote model-proposed drafts, never grant authority.
No model call, native memory bridge or automatic canonical write occurs here.
"""

import argparse
import json
import re
import shlex
import threading
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from .conversation_tasks import _supported_origin
from .memory_backend import MemoryError, MemoryService, validate_request
from .memory_index import maintain
from .memory_maintenance import maintain as maintain_store
from .memory_maintenance import validate as validate_maintenance
from .memory_presentation import render_memory_result
from .memory_snapshot import snapshot
from .memory_snapshot import validate as validate_snapshot
from .memory_storage import open_memory_backend
from .task_cli import current_profile_home

HELP = (
    'remember "Text" [--topic LABEL] [--expires-at UTC] [--request-id KEY]; '
    "list [--include-expired --limit N --after ID]; "
    'search "Text" [--include-expired --limit N --after ID]; show ID; '
    'search-terms "Term" ["Other term" ...] [--include-expired --limit N --after ID]; '
    'recall "Keyword" ["Other keyword" ...] [--limit N --max-chars N]; '
    "changes [--after-sequence N --through-sequence N --limit N]; "
    "checkpoint --expected-watermark N [--request-id KEY]; checkpoint-status ID; "
    'correct ID [--text "Replacement"] [--topic LABEL] [--expires-at UTC | --clear-expiry] '
    "--expected-revision N "
    "[--request-id KEY]; forget ID --expected-revision N [--request-id KEY]; "
    "export [--limit N --after ID]. Use POSIX quotes. "
    "maintenance-preview; maintenance-prepare NAME --expected-watermark N; "
    "maintenance-commit NAME; maintenance-status NAME; maintenance-recover NAME. "
    "Current-store repack only, never historical restore. Stop old runtimes before upgrading "
    "to this lock-aware version. Prepared/interrupted maintenance blocks ordinary memory "
    "until commit/recover; recovery finishes the recorded intent, never rolls back new writes. "
    "Preserved old files retain private plaintext after later forgetting. "
    "snapshot-create NAME / snapshot-inspect NAME create/inspect a private consistent plaintext "
    "database copy. Copies retain historical private memory after forgetting; no restore/import. "
    "snapshot-list NAME --sha256 DIGEST [--limit N --after ID]; "
    "snapshot-show NAME ID --sha256 DIGEST explicitly read historical records, not current state. "
    "May show later-forgotten text and enter host history; no model tool or automatic recall. "
    "edit-status; edit-new (--keep | --expires-at UTC) [--request-id KEY]; "
    "edit-create ID --expected-revision N [--request-id KEY]; edit-preview DRAFT; "
    "edit-apply DRAFT --expected-digest SHA256 [--request-id KEY]; edit-discard DRAFT. "
    "edit.md is managed: apply/discard removes it including edits; for correction drafts, "
    "target correction/forgetting also removes it. "
    "Only content/topic editable, no expiry change; one active draft, no background cleanup. "
    "expired-preview --before UTC [--limit N]; "
    "forget-expired --before UTC [--limit N] --expected-snapshot SHA256 --request-id KEY. "
    "Review every selected record before applying; default limit 10, maximum 20. "
    "The complete ASCII JSON preview data must fit 64000 characters; reduce --limit if refused. "
    "Cutoff must not be in the future. Exact retries return historical metadata, "
    "never a new batch. "
    "Managed files cannot roll back with SQLite; tombstones remain and capacity is not reset. "
    "index-status; index-rebuild --expected-watermark N (explicit canonical FTS maintenance). "
    "Index maintenance requires an existing current-schema store; no migration or history receipt. "
    "projection-status; projection-refresh (explicitly enable/rebuild a private Markdown view); "
    "projection-disable (remove the managed view, preserve canonical records). "
    "Projection is not a backup; fixed records.md is managed, never edit or import it. "
    "Native views are readable by default; prefix --json for the original structured envelope. "
    "candidate-list [--limit N --after ID]; candidate-show ID; "
    "candidate-accept ID --expected-revision N (--keep | --expires-at UTC); "
    "candidate-discard ID --expected-revision N; candidate-purge-expired; "
    "candidate-suppress-source ID --expected-revision N. Operator-only suppression discards "
    "all pending candidates from the same full input and blocks new same-input proposals. "
    "It does not delete already accepted records or match paraphrases; no unsuppress command. "
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
    "Search-terms requires every one of 1-8 distinct case-sensitive substrings to match "
    "content or topic. It is not semantic search; 1-2-character terms use literal fallback. "
    "Checkpoints cover local record metadata only, not native conversations or backups. "
    "Expiry uses an explicit UTC YYYY-MM-DDTHH:MM:SSZ timestamp; no default is inferred. "
    "Expired records are excluded from ordinary list/search/search-terms/recall, not deleted. "
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
    commands.add_parser("maintenance-preview")
    for operation in (
        "maintenance-prepare",
        "maintenance-commit",
        "maintenance-status",
        "maintenance-recover",
    ):
        command = commands.add_parser(operation)
        command.add_argument("name")
        if operation == "maintenance-prepare":
            command.add_argument("--expected-watermark", type=int, required=True)
    for operation in ("snapshot-create", "snapshot-inspect", "snapshot-list", "snapshot-show"):
        command = commands.add_parser(operation)
        command.add_argument("name")
        if operation in {"snapshot-list", "snapshot-show"}:
            command.add_argument("--sha256", required=True)
        if operation == "snapshot-list":
            command.add_argument("--limit", type=int, default=10)
            command.add_argument("--after", default=None)
        if operation == "snapshot-show":
            command.add_argument("record_id")
    for operation in ("list", "search", "search-terms", "export"):
        reader = commands.add_parser(operation)
        if operation == "search":
            reader.add_argument("query")
        if operation == "search-terms":
            reader.add_argument("terms", nargs="+")
        if operation in ("list", "search", "search-terms"):
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
    for operation in ("candidate-accept", "candidate-discard", "candidate-suppress-source"):
        review = commands.add_parser(operation)
        review.add_argument("candidate_id")
        review.add_argument("--expected-revision", type=int, required=True)
        if operation == "candidate-accept":
            retention = review.add_mutually_exclusive_group(required=True)
            retention.add_argument("--keep", dest="expires_at", action="store_const", const=None)
            retention.add_argument("--expires-at")
    edit_new = commands.add_parser("edit-new")
    retention = edit_new.add_mutually_exclusive_group(required=True)
    retention.add_argument("--keep", dest="expires_at", action="store_const", const=None)
    retention.add_argument("--expires-at")
    edit_new.add_argument("--request-id")
    for name in ("expired-preview", "forget-expired"):
        cleanup = commands.add_parser(name)
        cleanup.add_argument("--before", required=True)
        cleanup.add_argument("--limit", type=int, default=10)
        if name == "forget-expired":
            cleanup.add_argument("--expected-snapshot", required=True)
            cleanup.add_argument("--request-id", required=True)
    commands.add_parser("index-status")
    index = commands.add_parser("index-rebuild")
    index.add_argument("--expected-watermark", type=int, required=True)
    commands.add_parser("edit-status")
    edit = commands.add_parser("edit-create")
    edit.add_argument("record_id")
    edit.add_argument("--expected-revision", type=int, required=True)
    edit.add_argument("--request-id")
    for name in ("edit-preview", "edit-apply", "edit-discard"):
        edit = commands.add_parser(name)
        edit.add_argument("draft_id")
        if name == "edit-apply":
            edit.add_argument("--expected-digest", required=True)
            edit.add_argument("--request-id")
    commands.add_parser("candidate-purge-expired")
    commands.add_parser("projection-disable")
    commands.add_parser("projection-status")
    commands.add_parser("projection-refresh")
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
        "maintenance-preview": "maintenance_preview",
        "maintenance-prepare": "maintenance_prepare",
        "maintenance-commit": "maintenance_commit",
        "maintenance-status": "maintenance_status",
        "maintenance-recover": "maintenance_recover",
        "snapshot-create": "snapshot_create",
        "snapshot-inspect": "snapshot_inspect",
        "snapshot-list": "snapshot_list",
        "snapshot-show": "snapshot_show",
        "edit-new": "edit_new",
        "expired-preview": "expired_preview",
        "forget-expired": "forget_expired",
        "index-status": "index_status",
        "index-rebuild": "index_rebuild",
        "edit-status": "edit_status",
        "edit-create": "edit_create",
        "edit-preview": "edit_preview",
        "edit-apply": "edit_apply",
        "edit-discard": "edit_discard",
        "projection-disable": "projection_disable",
        "projection-status": "projection_status",
        "projection-refresh": "projection_refresh",
        "search-terms": "search_terms",
        "candidate-list": "candidate_list",
        "candidate-show": "candidate_get",
        "candidate-accept": "candidate_accept",
        "candidate-discard": "candidate_discard",
        "candidate-suppress-source": "candidate_suppress_source",
        "candidate-purge-expired": "candidate_purge_expired",
    }.get(operation, operation)
    if (
        operation
        in (
            "remember",
            "correct",
            "forget",
            "checkpoint_create",
            "edit_create",
            "edit_new",
            "edit_apply",
        )
        and payload["request_id"] is None
    ):
        payload["request_id"] = str(uuid4())
    if operation.startswith("maintenance_"):
        return operation, validate_maintenance(operation, payload)
    if operation in {"snapshot_create", "snapshot_inspect", "snapshot_list", "snapshot_show"}:
        return operation, validate_snapshot(operation, payload)
    return operation, validate_request(operation, payload)


def _bound_key() -> str:
    from gateway.session_context import bound_session_key  # ty: ignore[unresolved-import]

    return bound_session_key()


class LocalMemoryCommands:
    """Serialize unload with bounded operations; already admitted work may finish."""

    def __init__(
        self,
        *,
        bound_home: Path,
        read_config: Callable[[str, object], object],
        default_format: str = "json",
    ):
        if default_format not in {"json", "text"}:
            raise ValueError("unsupported default output format")
        self._default_format = default_format
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
        payload = {}
        machine = (
            type(raw_args) is str
            and re.match(r"^[ \t]{0,32}--json(?:[ \t\r\n]|$)", raw_args[:64]) is not None
        )
        output_format = "json" if machine else self._default_format
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
                if type(raw_args) is not str or len(raw_args) > 8192:
                    raise MemoryError("invalid_request")
                command_args = raw_args.lstrip(" \t")[6:] if machine else raw_args
                operation, payload = parse_command(command_args)
                request_id = payload.get("request_id")
                if operation == "help":
                    result = {"data": {"help": HELP}, "replayed": False}
                elif operation in {
                    "snapshot_create",
                    "snapshot_inspect",
                    "snapshot_list",
                    "snapshot_show",
                }:
                    result = snapshot(self._home, operation, payload)
                elif operation.startswith("maintenance_"):
                    result = maintain_store(self._home, operation, payload)
                elif operation in {"index_status", "index_rebuild"}:
                    result = maintain(self._home, operation, payload)
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
        envelope = {
            "schema_version": "personal.local-memory.v1",
            "scope": "trusted_local_operator_records",
            "request_id": request_id,
            **output,
        }
        if output_format == "text":
            return render_memory_result(envelope, operation=operation, payload=payload)
        return json.dumps(
            envelope,
            # Review must show the proposed text and quote legibly, including
            # Chinese. JSON still escapes controls and never evaluates content.
            ensure_ascii=not (operation and operation.startswith("candidate_")),
            indent=2 if operation and operation.startswith("candidate_") else None,
            sort_keys=True,
        )
