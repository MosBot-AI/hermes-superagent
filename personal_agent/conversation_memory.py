"""Explicit operator memory edits in trusted native LOCAL sessions only.

This does not authenticate a human or create owner authority. The host owns
session admission; every already admitted controller shares local access.
There is no extraction, model tool, native memory bridge or automatic recall.
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
    'remember "Text" [--topic LABEL] [--request-id KEY]; list [--limit N --after ID]; '
    'search "Text" [--limit N --after ID]; show ID; '
    'recall "Keyword" ["Other keyword" ...] [--limit N --max-chars N]; '
    'correct ID --text "Replacement" [--topic LABEL] --expected-revision N '
    "[--request-id KEY]; forget ID --expected-revision N [--request-id KEY]; "
    "export [--limit N --after ID]. Use POSIX quotes. "
    "Recall ranks 1-8 distinct literal keywords; defaults to 6 whole records and a 6000-character "
    "ASCII JSON items budget, not tokens. It reports omitted matches and is not semantic search. "
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
    remember.add_argument("--request-id")
    show = commands.add_parser("show")
    show.add_argument("record_id")
    for operation in ("list", "search", "export"):
        reader = commands.add_parser(operation)
        if operation == "search":
            reader.add_argument("query")
        reader.add_argument("--limit", type=int, default=20)
        reader.add_argument("--after", default=None)
    recall = commands.add_parser("recall")
    recall.add_argument("queries", nargs="+")
    recall.add_argument("--limit", type=int, default=6)
    recall.add_argument("--max-chars", type=int, default=6000)
    for operation in ("correct", "forget"):
        writer = commands.add_parser(operation)
        writer.add_argument("record_id")
        writer.add_argument("--expected-revision", type=int, required=True)
        writer.add_argument("--request-id")
        if operation == "correct":
            writer.add_argument("--text", dest="content", default=argparse.SUPPRESS)
            writer.add_argument("--topic", default=argparse.SUPPRESS)
    payload = vars(parser.parse_args(tokens))
    operation = payload.pop("operation")
    if operation == "show":
        operation = "get"
    if operation in ("remember", "correct", "forget") and payload["request_id"] is None:
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
            ensure_ascii=True,
            sort_keys=True,
        )
