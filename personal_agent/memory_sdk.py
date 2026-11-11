"""Version 1 SDK for reviewed, trusted-local explicit-record adapters.

No loader or authentication mechanism: the host supplies an already opened
backend and its binding. Python objects are not a malicious-code sandbox.
"""

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from .memory_backend import (
    MemoryBackend,
    MemoryError,
    MemoryService,
    _identifier,
    _text,
    validate_expiry,
    validate_request,
)
from .memory_mutation_status import mutation_request_identity as mutation_request_identity
from .memory_mutation_status import validate_result as validate_mutation_status
from .retained_sources import OPERATIONS as SOURCE_OPERATIONS
from .retained_sources import WRITES as SOURCE_WRITES
from .retained_sources import source_request_identity as source_request_identity
from .retained_sources import validate_result as validate_source_result

SDK_VERSION = 1
CHECKPOINT_OPERATIONS = frozenset({"checkpoint_create", "checkpoint_status"})
PROGRESS_OPERATIONS = frozenset({"changes", "consumer_get", "consumer_advance"})
OPERATIONS = (
    frozenset({"remember", "correct", "forget", "get", "list", "search", "export"})
    | PROGRESS_OPERATIONS
    | CHECKPOINT_OPERATIONS
    | SOURCE_OPERATIONS
    | {"mutation_receipt_status"}
)
_RECORD_WRITES = frozenset({"remember", "correct", "forget"})
_WRITES = _RECORD_WRITES | {"consumer_advance", "checkpoint_create"} | SOURCE_WRITES
_REJECTIONS = frozenset(
    {
        "idempotency_conflict",
        "source_scope_required",
        "source_pending",
        "source_not_staged",
        "source_identity_conflict",
        "source_suppressed",
        "source_terminal",
        "source_cursor_conflict",
        "source_limit",
        "source_consumer_limit",
        "revision_conflict",
        "record_forgotten",
        "not_found",
        "invalid_cursor",
        "record_limit",
        "mutation_limit",
        "read_only",
        "read_only_backend",
        "invalid_sequence",
        "future_watermark",
        "cursor_not_advanced",
        "consumer_limit",
        "consumer_mutation_limit",
        "consumer_scope_required",
        "checkpoint_scope_required",
        "checkpoint_not_found",
        "watermark_conflict",
        "checkpoint_limit",
        "checkpoint_state_limit",
        "checkpoint_state_inconsistent",
    }
)
_RECORD = frozenset(
    {
        "record_id",
        "revision",
        "status",
        "content",
        "topic",
        "source",
        "session_ref",
        "created_at",
        "updated_at",
        "expires_at",
        "expired",
    }
)


@dataclass(frozen=True)
class LocalBinding:
    """Host assertion of local routing, not proof of remote owner identity."""

    namespace_id: str
    session_ref: str
    source_kind: str = "explicit_local_operator"

    def __post_init__(self):
        _text(self.namespace_id, 256)
        _text(self.session_ref, 256)
        if self.source_kind not in {"explicit_local_operator", "activated_session_model"}:
            raise MemoryError("invalid_request")


def _require(condition):
    if not condition:
        raise MemoryError("invalid_result")


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _integer(value, minimum=0):
    _require(type(value) is int and minimum <= value < 2**63)


def _timestamp(value):
    _require(type(value) is str and len(value) <= 32 and value.endswith(("Z", "+00:00")))
    parsed = datetime.fromisoformat(value)
    offset = parsed.utcoffset()
    _require(offset is not None and offset.total_seconds() == 0)
    return parsed


def _record(value):
    _keys(value, _RECORD)
    _identifier(value["record_id"])
    _integer(value["revision"], 1)
    _require(value["status"] in {"active", "forgotten"})
    _require(type(value["expired"]) is bool)
    _require(_timestamp(value["created_at"]) <= _timestamp(value["updated_at"]))
    expiry = validate_expiry(value["expires_at"])
    if value["status"] == "forgotten":
        _require(
            all(
                value[key] is None
                for key in (
                    "content",
                    "topic",
                    "source",
                    "session_ref",
                    "expires_at",
                )
            )
        )
        _require(value["expired"] is False)
    else:
        _text(value["content"], 2048, multiline=True)
        _text(value["topic"], 128, empty=True)
        _text(value["session_ref"], 256)
        _require(value["source"] in {"explicit_local_operator", "activated_session_model"})
        if expiry is None:
            _require(value["expired"] is False)


class LocalMemorySDK:
    """Validated API-v1 facade; close releases backend, never owns host connection.

    Unexpected exceptions or malformed write replies are outcome_unknown.
    Known rejection codes are trusted adapter promises of no committed change.
    A lying adapter cannot be detected or contained here. No retry is performed.
    Reconcile by the same request ID in the same trusted store.
    """

    def __init__(self, backend: MemoryBackend, binding: LocalBinding):
        if type(binding) is not LocalBinding:
            raise MemoryError("invalid_request")
        self._binding = binding
        self._service = MemoryService(backend)
        self._closed = False
        # A bounded, validated read prevents accidental cross-namespace binding.
        # The trusted opener must keep this backend bound for the SDK lifetime;
        # this check is not remote authentication or containment of lying code.
        try:
            self.execute("export", {"limit": 1})
        except Exception:
            self._closed = True
            raise MemoryError("unsupported_backend") from None

    @property
    def binding(self):
        return self._binding

    def execute(self, operation: str, payload: dict) -> dict:
        if self._closed:
            raise MemoryError("closed")
        if type(operation) is not str or operation not in OPERATIONS:
            raise MemoryError("unsupported_operation")
        request = validate_request(operation, payload)
        self._service.descriptor.check_request(operation, request)
        if (
            operation in {"consumer_advance", "checkpoint_create"}
            and self.binding.source_kind != "explicit_local_operator"
        ):
            raise MemoryError(
                "checkpoint_scope_required"
                if operation == "checkpoint_create"
                else "consumer_scope_required"
            )
        if operation in SOURCE_WRITES and self.binding.source_kind != "explicit_local_operator":
            raise MemoryError("source_scope_required")
        try:
            result = self._service.execute(operation, deepcopy(request))
        except MemoryError as error:
            # Reviewed adapters promise these rejections occur without commit.
            # Unknown errors are not evidence of rollback and stay uncertain.
            if error.code in _REJECTIONS and (
                operation not in {"mutation_receipt_status", "source_status", "source_cursor"}
                or error.code == "idempotency_conflict"
            ):
                raise MemoryError(error.code) from None
            raise MemoryError(
                "outcome_unknown" if operation in _WRITES else "backend_failure"
            ) from None
        except Exception:
            raise MemoryError(
                "outcome_unknown" if operation in _WRITES else "backend_failure"
            ) from None
        try:
            self._validate_result(operation, request, result)
            return deepcopy(result)
        except Exception:
            raise MemoryError(
                "outcome_unknown" if operation in _WRITES else "invalid_result"
            ) from None

    def _validate_record(self, record):
        _record(record)
        limits = dict(self._service.descriptor.limits)
        if record["status"] == "active":
            _require(len(record["content"]) <= limits["max_content_chars"])
            _require(len(record["topic"]) <= limits["max_topic_chars"])

    def _validate_result(self, operation, request, result):
        _keys(result, {"data", "replayed"})
        _require(type(result["replayed"]) is bool)
        data = result["data"]
        if operation in SOURCE_OPERATIONS:
            if operation not in SOURCE_WRITES:
                _require(result["replayed"] is False)
            validate_source_result(operation, request, data)
            return
        if operation == "mutation_receipt_status":
            _require(result["replayed"] is False)
            validate_mutation_status(data, request)
            return
        if operation in CHECKPOINT_OPERATIONS:
            self._validate_checkpoint(operation, request, result)
            return
        if operation in PROGRESS_OPERATIONS:
            self._validate_progress(operation, request, result)
            return
        if operation in _RECORD_WRITES:
            _keys(
                data,
                {"record_id", "revision", "status", "operation", "request_id", "event_sequence"},
            )
            _identifier(data["record_id"])
            _integer(data["revision"], 1)
            _integer(data["event_sequence"], 1)
            _require(data["operation"] == operation and data["request_id"] == request["request_id"])
            _require(data["status"] == ("forgotten" if operation == "forget" else "active"))
            if operation == "remember":
                _require(data["revision"] == 1)
            else:
                _require(data["record_id"] == request["record_id"])
                _require(data["revision"] == request["expected_revision"] + 1)
            return
        _require(result["replayed"] is False)
        if operation == "get":
            self._validate_record(data)
            _require(data["record_id"] == request["record_id"])
            return
        fields = {"items", "evaluated_at", "next_cursor", "has_more"}
        if operation == "export":
            fields |= {"schema_version", "namespace_id", "watermark", "scope", "restorable"}
        _keys(data, fields)
        evaluated = _timestamp(data["evaluated_at"])
        _require(type(data["items"]) is list and len(data["items"]) <= request["limit"])
        _require(type(data["has_more"]) is bool)
        ids = []
        for record in data["items"]:
            self._validate_record(record)
            ids.append(record["record_id"])
            expiry = record["expires_at"]
            _require(
                record["expired"]
                == (expiry is not None and datetime.fromisoformat(expiry) <= evaluated)
            )
            if operation != "export":
                _require(record["status"] == "active")
                _require(request.get("include_expired", False) or not record["expired"])
            if operation == "search":
                _require(
                    request["query"] in record["content"] or request["query"] in record["topic"]
                )
        _require(len(ids) == len(set(ids)) and request["after"] not in ids)
        _require(data["next_cursor"] == (ids[-1] if data["has_more"] and ids else None))
        _require(not data["has_more"] or len(ids) == request["limit"])
        if operation == "export":
            _require(data["namespace_id"] == self.binding.namespace_id)
            _require(data["schema_version"] == "personal.memory.record_page.v1")
            _require(data["scope"] == "current_records_and_tombstones_live_page")
            _require(data["restorable"] is False)
            _integer(data["watermark"])

    def _validate_progress(self, operation, request, result):
        data = result["data"]
        if operation != "consumer_advance":
            _require(result["replayed"] is False)
        if operation == "changes":
            _keys(
                data,
                {
                    "schema_version",
                    "items",
                    "through_sequence",
                    "current_watermark",
                    "next_sequence",
                    "has_more",
                    "retention_floor",
                    "scope",
                },
            )
            _require(data["schema_version"] == "personal.memory.changes.v1")
            _require(data["scope"] == "committed_record_event_metadata_no_historical_payload")
            for key in (
                "through_sequence",
                "current_watermark",
                "next_sequence",
                "retention_floor",
            ):
                _integer(data[key])
            _require(data["retention_floor"] == 0)
            after, through = request["after_sequence"], data["through_sequence"]
            _require(after <= through <= data["current_watermark"])
            _require(
                through
                == (
                    request["through_sequence"]
                    if request["through_sequence"] is not None
                    else data["current_watermark"]
                )
            )
            _require(type(data["items"]) is list and len(data["items"]) <= request["limit"])
            _require(type(data["has_more"]) is bool)
            previous = after
            records = {}
            for item in data["items"]:
                _keys(item, {"sequence", "record_id", "revision", "operation"})
                _integer(item["sequence"], 1)
                _integer(item["revision"], 1)
                _identifier(item["record_id"])
                _require(item["operation"] in _RECORD_WRITES)
                _require(
                    item["revision"] == 1
                    if item["operation"] == "remember"
                    else item["revision"] >= 2
                )
                prior = records.get(item["record_id"])
                if prior is not None:
                    _require(prior["operation"] != "forget")
                    _require(item["revision"] > prior["revision"])
                records[item["record_id"]] = item
                _require(previous < item["sequence"] <= through)
                previous = item["sequence"]
            _require(data["next_sequence"] == previous)
            if data["has_more"]:
                _require(len(data["items"]) == request["limit"] and previous < through)
            else:
                _require(previous == through)
            return
        fields = {"consumer_id", "revision", "through_sequence", "registered", "scope"}
        if operation == "consumer_advance":
            fields |= {"request_id"}
        _keys(data, fields)
        _require(data["consumer_id"] == request["consumer_id"])
        _require(data["scope"] == "caller_reported_local_record_progress_not_native_checkpoint")
        _integer(data["revision"])
        _integer(data["through_sequence"])
        _require(type(data["registered"]) is bool)
        _require(data["registered"] == (data["revision"] > 0))
        _require(data["registered"] or data["through_sequence"] == 0)
        if operation == "consumer_advance":
            _require(data["registered"] is True)
            _require(data["revision"] == request["expected_revision"] + 1)
            _require(data["through_sequence"] == request["through_sequence"])
            _require(data["request_id"] == request["request_id"])

    def _validate_checkpoint_receipt(self, receipt):
        _keys(
            receipt,
            {
                "schema_version",
                "checkpoint_id",
                "request_id",
                "through_sequence",
                "event_count",
                "record_count",
                "active_count",
                "forgotten_count",
                "metadata_sha256",
                "scope",
                "restorable",
                "native_checkpoint",
            },
        )
        _require(receipt["schema_version"] == "personal.memory.metadata_checkpoint.v1")
        _require(type(receipt["checkpoint_id"]) is str and len(receipt["checkpoint_id"]) == 36)
        _identifier(receipt["checkpoint_id"])
        _require(type(receipt["request_id"]) is str)
        # Reuse the bounded request-key grammar without accepting arbitrary text.
        validate_request(
            "checkpoint_create",
            {
                "request_id": receipt["request_id"],
                "expected_watermark": 0,
            },
        )
        digest = receipt["metadata_sha256"]
        _require(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None)
        _require(receipt["scope"] == "local_record_metadata_not_native_conversation")
        _require(receipt["restorable"] is False and receipt["native_checkpoint"] is False)
        for key in (
            "through_sequence",
            "event_count",
            "record_count",
            "active_count",
            "forgotten_count",
        ):
            _integer(receipt[key])
        limits = dict(self._service.descriptor.limits)
        records, events = receipt["record_count"], receipt["event_count"]
        forgotten = receipt["forgotten_count"]
        _require(records == receipt["active_count"] + forgotten)
        _require(records <= limits["max_total_records"])
        _require(events <= limits["max_total_mutations"])
        _require(events - forgotten <= limits["max_nonterminal_mutations"])
        _require(events >= records + forgotten)
        _require((events == 0) == (records == 0))
        _require((events == 0) == (receipt["through_sequence"] == 0))
        # Sequence gaps are allowed; the watermark is not an event count.
        _require(events <= receipt["through_sequence"])

    def _validate_checkpoint(self, operation, request, result):
        data = result["data"]
        if operation == "checkpoint_create":
            self._validate_checkpoint_receipt(data)
            _require(data["request_id"] == request["request_id"])
            _require(data["through_sequence"] == request["expected_watermark"])
            return
        _require(result["replayed"] is False)
        _keys(data, {"checkpoint", "is_current", "current_watermark", "scope"})
        receipt = data["checkpoint"]
        self._validate_checkpoint_receipt(receipt)
        _require(receipt["checkpoint_id"] == request["checkpoint_id"])
        _require(type(data["is_current"]) is bool)
        _integer(data["current_watermark"])
        _require(
            data["scope"] == "metadata_comparison_at_this_read_snapshot_not_restore_or_authority"
        )
        _require(receipt["through_sequence"] <= data["current_watermark"])
        # Equal watermarks need not mean equal metadata (e.g. same-watermark tampering).
        _require(not data["is_current"] or receipt["through_sequence"] == data["current_watermark"])

    def context(self, query: str, *, limit: int = 6, max_chars: int = 6000) -> dict:
        """One fresh search snapshot, whole records only; not instructions/authority."""
        if type(max_chars) is not int or not 1024 <= max_chars <= 12000:
            raise MemoryError("invalid_request")
        page = self.execute("search", {"query": query, "limit": limit})["data"]
        items = []
        for record in page["items"]:
            candidate = [*items, record]
            if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) <= max_chars:
                items = candidate
        return {
            "schema_version": "personal.memory.context.v1",
            "items": items,
            "items_json_chars": len(json.dumps(items, ensure_ascii=False, separators=(",", ":"))),
            "max_chars": max_chars,
            "evaluated_at": page["evaluated_at"],
            "omitted_from_page": len(page["items"]) - len(items),
            "has_more": page["has_more"],
            "authority": "stored_data_not_instructions_or_permission",
        }

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._service.backend.close()
            except Exception:
                raise MemoryError("backend_failure") from None
