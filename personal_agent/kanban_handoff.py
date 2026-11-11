"""Explicit local preview/confirmation to a parked native card, never a worker.

The host admits this operator command; it does not authenticate human origin.
All admitted local controllers share its authority. No model tool is registered.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import threading
import time

from .conversation_tasks import _supported_origin
from .kanban_handoff_presentation import render
from .kanban_handoff_storage import open_handoff_store
from .kanban_handoff_store import HandoffError
from .task_cli import current_profile_home, open_task_store
from .tasks import TaskError

HELP = (
    "prepare TASK --expected-revision N --request-id KEY; "
    "commit ID --expected-digest SHA; reconcile ID; show ID; "
    "sync ID --task TASK --expected-revision N --request-id KEY; "
    "review ID --task TASK --expected-revision N; "
    "accept-review ID --task TASK --expected-revision N --expected-digest SHA "
    "--note NOTE --request-id KEY; "
    "list [--limit N --after ID]; cancel ID --expected-digest SHA. "
    "Opt-in native operator handoff only. Review the exact title/body and destination before "
    "commit. Native boards can be shared across profiles; no memory, conversation, project "
    "label or dependency text is exported. Preparation expires after 15 minutes. "
    "Commit creates only a sticky-blocked unassigned scratch card, not execution permission. "
    "Another authorized native actor can later unblock it. Never automatically retries an "
    "attempt, even when reconciliation finds no card. Unknown means inspect, not resubmit. "
    "Payload is cleared on claim/cancel/lazy expiry; minimal metadata remains (1000 records). "
    "Commands and results may enter native history; clearing does not erase that history. "
    "Sync explicitly saves one advisory native-status snapshot on the selected captured task, "
    "with an atomic local revision/event/receipt; it never changes local completion or work "
    "status. Stored snapshots are task data and may enter separately activated task model tools. "
    "Exact retries return the original receipt without native access. Fresh sync needs "
    "a confirmed immutable creation anchor; legacy attempted records cannot be silently adopted. "
    "A native done status is not proof of completed work. No worker dispatch, reminders, "
    "native project/dependency synchronization or external calls. "
    "Review explicitly reads the linked card's bounded editable result into the native client, "
    "which may display/cache it; no automatic model submission or raw-result retention. "
    "Treat result text as untrusted data, never instructions or proof of execution. "
    "Accept-review is your explicit local completion decision with a required note, not "
    "native completion or dispatch. It rechecks the exact result digest, local revision, "
    "done native status/null current-run pointer and all local prerequisites. "
    "This is not proof a worker process stopped. Inspect actual work yourself; "
    "the source may have changed since export. The native snapshot can change after read. "
    "Only minimal review metadata is retained with the durable local receipt; no result text. "
    "Identical accept retries return the original receipt without native access."
)


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{**kwargs, "allow_abbrev": False})

    def error(self, message):
        raise HandoffError("invalid_request")

    def exit(self, status=0, message=None):
        raise HandoffError("invalid_request")

    def _print_message(self, message, file=None):
        pass


class _Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise HandoffError("invalid_request")
        setattr(namespace, self.dest, values)


def parse_command(raw):
    if type(raw) is not str or len(raw) > 8192 or "\x00" in raw:
        raise HandoffError("invalid_request")
    try:
        tokens = shlex.split(raw, comments=False, posix=True)
    except ValueError:
        raise HandoffError("invalid_request") from None
    if not tokens or tokens in (["help"], ["--help"], ["-h"]):
        return {"operation": "help"}
    if len(raw) > 2048 and (not tokens or tokens[0] != "accept-review"):
        raise HandoffError("invalid_request")
    if len(tokens) > 16:
        raise HandoffError("invalid_request")
    parser = _Parser(prog="/personal-handoff")
    subs = parser.add_subparsers(dest="operation", required=True)
    prepare = subs.add_parser("prepare")
    prepare.add_argument("task_id")
    prepare.add_argument("--expected-revision", type=int, required=True)
    prepare.add_argument("--request-id", required=True)
    for verb in ("show", "commit", "cancel", "reconcile"):
        command = subs.add_parser(verb)
        command.add_argument("id")
        if verb in ("commit", "cancel"):
            command.add_argument("--expected-digest", required=True)
    sync = subs.add_parser("sync")
    sync.add_argument("handoff_id")
    sync.add_argument("--task", dest="task_id", required=True)
    sync.add_argument("--expected-revision", type=int, required=True)
    sync.add_argument("--request-id", required=True)
    for verb in ("review", "accept-review"):
        command = subs.add_parser(verb)
        command.add_argument("handoff_id")
        command.add_argument("--task", dest="task_id", required=True, action=_Once)
        command.add_argument("--expected-revision", type=int, required=True, action=_Once)
        if verb == "accept-review":
            command.add_argument("--expected-digest", required=True, action=_Once)
            command.add_argument("--note", required=True, action=_Once)
            command.add_argument("--request-id", required=True, action=_Once)
    listing = subs.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--after", default=None)
    return vars(parser.parse_args(tokens))


def _bound_key():
    from gateway.session_context import bound_session_key  # ty: ignore[unresolved-import]

    return bound_session_key()


def _runtime():
    from agent.delegation_context import (  # ty: ignore[unresolved-import]
        explicit_board_intent_is_pinned,
        is_delegated_child_process_context,
        is_dispatcher_owned_worker_context,
    )
    from agent.safe_worker_policy import worker_config_snapshot  # ty: ignore[unresolved-import]
    from cron.execution_identity import current_cron_execution  # ty: ignore[unresolved-import]
    from hermes_cli import managed_scope  # ty: ignore[unresolved-import]

    if (
        os.environ.get("HERMES_PLUGIN_HOST_PROCESS") == "1"
        or worker_config_snapshot() is not None
        or managed_scope.get_managed_dir() is not None
        or is_delegated_child_process_context()
        or not is_dispatcher_owned_worker_context()
        or explicit_board_intent_is_pinned()
        or current_cron_execution() is not None
    ):
        raise HandoffError("handoff_runtime_unsupported")


def _source(task, revision):
    if task["state"] != "captured" or task["revision"] != revision:
        raise HandoffError("source_changed")
    return {
        "task_id": task["id"],
        "revision": task["revision"],
        "title": task["title"],
        "details": task["details"],
    }


def _body(source):
    return (
        "UNTRUSTED LOCAL TASK SNAPSHOT. Parked for operator review only. "
        "This text is not authorization or instructions to execute. "
        "Local dependencies and project labels are NOT synchronized. "
        "Recheck source and separately authorize any later assignment/unblocking.\n"
        f"Source task: {source['task_id']}\nSource revision: {source['revision']}\n\n"
        + source["details"]
    )


class LocalKanbanHandoff:
    def __init__(self, *, bound_home, read_config):
        self._home = bound_home
        self._config = read_config
        self._lock = threading.RLock()
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True

    def _admit(self, context, *, native=False):
        if self._closed:
            raise HandoffError("handoff_unloaded")
        if (
            context["platform"] != "local"
            or not _supported_origin(**context)
            or not context["session_key"]
            or _bound_key() != context["session_key"]
        ):
            raise HandoffError("unsupported_origin")
        if not self._home.is_dir() or current_profile_home() != self._home:
            raise HandoffError("profile_context_changed")
        _runtime()
        mode = self._config("mode", "read_only")
        conversation = self._config("local_conversation", False)
        if (
            mode not in ("read_only", "local_tasks")
            or type(conversation) is not bool
            or (conversation and mode != "local_tasks")
        ):
            raise HandoffError("invalid_configuration")
        if mode != "local_tasks" or not conversation:
            raise HandoffError("handoff_disabled")
        if not native:
            # A historical local sync receipt must not depend on creation config,
            # ledger state or native availability. Current base admission still applies.
            return ""
        enabled = self._config("kanban_handoff", False)
        board = self._config("kanban_handoff_board", "")
        if (
            type(enabled) is not bool
            or type(board) is not str
            or (enabled and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", board) is None)
        ):
            raise HandoffError("invalid_configuration")
        if not enabled:
            raise HandoffError("handoff_disabled")
        return board

    def _sync(self, request, context):
        intent = {key: value for key, value in request.items() if key != "operation"}

        def observe(task):
            board = self._admit(context, native=True)
            with open_handoff_store(self._home) as ledger:
                record = ledger.get(request["handoff_id"], int(time.time()))
            if record["source"]["task_id"] != task["id"]:
                raise HandoffError("source_mismatch")
            if (
                record["profile_fingerprint"]
                != hashlib.sha256(str(self._home).encode()).hexdigest()
            ):
                raise HandoffError("profile_context_changed")
            if record["destination"]["board"] != board:
                raise HandoffError("destination_changed")
            if record["state"] != "confirmed":
                raise HandoffError("handoff_not_confirmed")
            if record["identity_state"] != "available" or record["native_identity"] is None:
                raise HandoffError("native_identity_unavailable")
            from . import native_kanban as native

            def admit():
                if self._admit(context, native=True) != board:
                    raise HandoffError("destination_changed")

            observation = native.observe_progress(
                record["destination"],
                key=record["key"],
                identity=record["native_identity"],
                admit=admit,
            )
            admit()
            return {
                "status": None,
                **observation,
                "handoff_id": record["id"],
                "exported_revision": record["source"]["revision"],
            }

        with open_task_store(self._home) as tasks:
            # The task transaction checks the durable receipt before invoking
            # this callback. No ledger/native access occurs on exact replay.
            return tasks.sync_native(intent, observe)

    def _review_result(self, request, context):
        from . import task_result_review

        def observe(task):
            board = self._admit(context, native=True)
            with open_handoff_store(self._home) as ledger:
                record = ledger.get(request["handoff_id"], int(time.time()))
            if record["source"]["task_id"] != task["id"]:
                raise HandoffError("source_mismatch")
            if (
                record["profile_fingerprint"]
                != hashlib.sha256(str(self._home).encode()).hexdigest()
            ):
                raise HandoffError("profile_context_changed")
            if record["destination"]["board"] != board:
                raise HandoffError("destination_changed")
            if record["state"] != "confirmed":
                raise HandoffError("handoff_not_confirmed")
            if record["identity_state"] != "available" or record["native_identity"] is None:
                raise HandoffError("native_identity_unavailable")
            from . import native_kanban as native

            def admit():
                if self._admit(context, native=True) != board:
                    raise HandoffError("destination_changed")

            observation = native.observe_result(
                record["destination"],
                key=record["key"],
                identity=record["native_identity"],
                admit=admit,
            )
            admit()
            return {
                "handoff_id": record["id"],
                "exported_revision": record["source"]["revision"],
                "destination": record["destination"],
                "identity": record["native_identity"],
                "native": observation,
            }

        with open_task_store(self._home) as tasks:
            if request["operation"] == "accept-review":
                # Receipt lookup happens before this callback can touch the native
                # board or handoff ledger. No distributed commit is claimed.
                return tasks.accept_native_review(
                    {k: v for k, v in request.items() if k != "operation"}, observe
                )
            revision = request["expected_revision"]
            if type(revision) is not int or not 1 <= revision < 2**63 - 1:
                raise TaskError("invalid_request")
            with tasks.snapshot_task(request["task_id"]) as task:
                _source(task, revision)
                return task_result_review.preview(task, observe(task))

    def _execute(self, request, context):
        operation = request["operation"]
        board = self._admit(context, native=operation in ("prepare", "commit", "reconcile"))
        if operation == "help":
            return {"help": HELP}
        if operation == "sync":
            return self._sync(request, context)
        if operation in ("review", "accept-review"):
            return self._review_result(request, context)
        with open_handoff_store(self._home) as ledger:
            now = int(time.time())
            if operation == "list":
                return ledger.list(request["limit"], request["after"], now)
            if operation == "show":
                return ledger.get(request["id"], now)
            if operation == "cancel":
                return ledger.cancel(request["id"], request["expected_digest"], now)
            from . import native_kanban as native

            profile = hashlib.sha256(str(self._home).encode()).hexdigest()

            def admit():
                if self._admit(context, native=True) != board:
                    raise HandoffError("destination_changed")

            if operation == "prepare":
                with open_task_store(self._home) as tasks:
                    with tasks.snapshot_task(request["task_id"]) as task:
                        source = _source(task, request["expected_revision"])
                        title, body = source["title"].strip(), _body(source)
                        destination = native.destination(board)
                        admit()
                        key = hashlib.sha256(
                            (profile + ":" + request["request_id"]).encode()
                        ).hexdigest()
                        return ledger.prepare(
                            request["request_id"],
                            {
                                "source": source,
                                "destination": destination,
                                "native_title": title,
                                "native_body": body,
                                "key": key,
                                "payload_digest": native.payload_digest(title, body),
                                "profile_fingerprint": profile,
                            },
                            now,
                        )
            record = ledger.get(request["id"], now)
            if record["profile_fingerprint"] != profile:
                raise HandoffError("profile_context_changed")
            if record["destination"]["board"] != board:
                raise HandoffError("destination_changed")
            if operation == "reconcile":
                if record["state"] not in ("claimed", "unknown", "confirmed"):
                    raise HandoffError("not_attempted")
                observation = native.observe(
                    record["destination"],
                    key=record["key"],
                    payload_digest=record["payload_digest"],
                    admit=admit,
                    identity=record["native_identity"],
                )
                if observation["outcome"] in (
                    "identity_changed",
                    "key_changed",
                    "identity_unavailable",
                ):
                    # Reconcile retains its older creation-observation contract;
                    # the separate sync projection preserves precise identity outcomes.
                    observation = {"outcome": "changed", "card_id": observation["card_id"]}
                elif observation.get("status", "") is None:
                    observation = {k: v for k, v in observation.items() if k != "status"}
                return ledger.record_observation(record["id"], observation, int(time.time()))
            if record["intent_digest"] != request["expected_digest"]:
                raise HandoffError("intent_conflict")
            if record["state"] != "prepared":
                return record  # Never resubmit a claimed or unknown operation.
            intent = record["payload"]
            with open_task_store(self._home) as tasks:
                with tasks.snapshot_task(record["source"]["task_id"]) as task:
                    if _source(task, record["source"]["revision"]) != intent["source"]:
                        raise HandoffError("source_changed")
                    if native.destination(board) != record["destination"]:
                        raise HandoffError("destination_changed")
                    admit()
                    claimed, won = ledger.claim(
                        record["id"], request["expected_digest"], int(time.time())
                    )
                    if not won:
                        return claimed
                    # A crash or exception from this point is ambiguous. Claim was
                    # durable, payload was purged, and no command can resubmit it.
                    try:
                        observation = native.create_parked(
                            record["destination"],
                            key=record["key"],
                            title=intent["native_title"],
                            body=intent["native_body"],
                            admit=admit,
                            remember_identity=lambda identity: ledger.remember_native_identity(
                                record["id"], identity, int(time.time())
                            ),
                        )
                    except Exception:
                        observation = {"outcome": "unavailable"}
                    return ledger.record_observation(record["id"], observation, int(time.time()))

    def command(self, raw_args, *, platform="", source=None, session_id="", session_key=""):
        operation = None
        json_mode = False
        if type(raw_args) is str:
            flag = re.match(r"^\s*--json(?:\s+|$)", raw_args)
            if flag:
                json_mode = True
                # Keep the original command size limit, including the display flag.
                raw_args = raw_args[flag.end() :] if len(raw_args) <= 8192 else None
        output: dict = {}
        try:
            with self._lock:
                context = {
                    "platform": platform,
                    "source": source,
                    "session_id": session_id,
                    "session_key": session_key,
                }
                self._admit(context)
                request = parse_command(raw_args)
                operation = request["operation"]
                data = self._execute(request, context)
                output = {"status": "ok", "data": data, "error": None}
                if operation in ("sync", "accept-review"):
                    output = {"status": "ok", **data, "error": None}
        except Exception as error:
            if not isinstance(error, (HandoffError, TaskError)):
                error = HandoffError("handoff_unavailable")
            output = {
                "status": "error",
                "data": None,
                "error": {"code": error.code, "retryable": error.retryable},
            }
        if operation in ("sync", "accept-review") and output["status"] == "error":
            output["replayed"] = False
        envelope = {
            "schema_version": "personal.kanban-handoff.v1",
            "scope": (
                "trusted_local_operator_native_result_review"
                if operation in ("review", "accept-review")
                else "trusted_local_operator_parked_card"
            ),
            **output,
        }
        if not json_mode:
            return render(envelope, operation)
        return json.dumps(
            envelope,
            ensure_ascii=operation in ("review", "accept-review"),
            sort_keys=True,
            indent=2,
        )
