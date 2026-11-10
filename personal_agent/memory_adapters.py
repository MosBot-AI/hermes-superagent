"""Admission metadata for the narrow, explicit-record backend API.

This is not a provider loader, sandbox, credential resolver or activation API.
Discovery reads installed distribution metadata without importing entry points.
Descriptors are reviewed-code declarations, not proof of durability or privacy.
"""

import re
from dataclasses import dataclass
from importlib import metadata
from typing import Any, cast

from .memory_backend import MemoryError

ENTRY_POINT_GROUP = "hermes_personal_agent.memory_backends"
_CAPABILITIES = frozenset(
    {
        "private_markdown_projection",
        "private_edit_drafts",
        "review_candidates",
        "exact_source_suppression",
        "record_expiry",
        "reviewed_expired_cleanup",
        "explicit_records",
        "durable_write",
        "cas",
        "idempotency",
        "literal_search",
        "multi_term_fts",
        "bounded_record_export",
        "bounded_recall",
        "metadata_changes",
        "durable_consumer_cursor",
        "local_metadata_checkpoint",
    }
)
_LIMITS = {
    "max_content_chars": 2048,
    "max_topic_chars": 128,
    "max_query_chars": 128,
    "max_page_records": 50,
    "max_total_records": 1000,
    "max_nonterminal_mutations": 10000,
    "max_total_mutations": 11000,
}
_DESCRIPTOR_FIELDS = {
    "adapter_id",
    "api_version",
    "schema_version",
    "adapter_version",
    "deployment",
    "capabilities",
    "unsupported",
    "query_semantics",
    "deletion",
    "export_format",
    "export_scope",
    "data_recipients",
    *_LIMITS,
}
_OPERATION_CAPABILITIES = {
    "expired_preview": {"explicit_records", "record_expiry", "reviewed_expired_cleanup"},
    "forget_expired": {
        "explicit_records",
        "record_expiry",
        "reviewed_expired_cleanup",
        "durable_write",
        "cas",
        "idempotency",
    },
    "edit_status": {"private_edit_drafts"},
    "edit_create": {"private_edit_drafts", "durable_write", "cas", "idempotency"},
    "edit_new": {"private_edit_drafts", "durable_write", "idempotency", "record_expiry"},
    "edit_preview": {"private_edit_drafts"},
    "edit_apply": {"private_edit_drafts", "durable_write", "cas", "idempotency"},
    "edit_discard": {"private_edit_drafts", "durable_write"},
    "projection_disable": {"private_markdown_projection", "durable_write"},
    "projection_status": {"private_markdown_projection"},
    "projection_refresh": {"private_markdown_projection", "durable_write"},
    "remember": {"explicit_records", "durable_write", "idempotency"},
    "correct": {"explicit_records", "durable_write", "cas", "idempotency"},
    "forget": {"explicit_records", "durable_write", "cas", "idempotency"},
    "get": {"explicit_records"},
    "list": {"explicit_records"},
    "search": {"explicit_records", "literal_search"},
    "search_terms": {"explicit_records", "multi_term_fts"},
    "recall": {"explicit_records", "literal_search", "bounded_recall"},
    "export": {"explicit_records", "bounded_record_export"},
    "changes": {"explicit_records", "metadata_changes"},
    "checkpoint_create": {
        "explicit_records",
        "local_metadata_checkpoint",
        "durable_write",
        "cas",
        "idempotency",
    },
    "checkpoint_status": {"explicit_records", "local_metadata_checkpoint"},
    "consumer_get": {"explicit_records", "durable_consumer_cursor"},
    "consumer_advance": {
        "explicit_records",
        "metadata_changes",
        "durable_consumer_cursor",
        "durable_write",
        "cas",
        "idempotency",
    },
}
for _candidate_operation in (
    "candidate_propose",
    "candidate_list",
    "candidate_get",
    "candidate_discard",
    "candidate_accept",
    "candidate_purge_expired",
):
    _OPERATION_CAPABILITIES[_candidate_operation] = {"review_candidates", "durable_write"}
_OPERATION_CAPABILITIES["candidate_suppress_source"] = {"exact_source_suppression", "durable_write"}


_RESERVED_IDS = frozenset({"local_sqlite", "builtin", "built-in", "default", "none"})


def _matches(value: object, pattern: str, maximum: int) -> bool:
    return type(value) is str and len(value) <= maximum and re.fullmatch(pattern, value) is not None


def _names(value: object) -> tuple[str, ...]:
    if (
        type(value) is not list
        or len(value) > 32
        or any(not _matches(item, r"[a-z][a-z0-9_]*", 64) for item in value)
        or len(set(value)) != len(value)
    ):
        raise MemoryError("unsupported_backend")
    return tuple(sorted(cast(list[str], value)))


@dataclass(frozen=True)
class BackendDescriptor:
    """Immutable negotiated subset. The service cannot certify backend claims."""

    adapter_id: str
    adapter_version: str
    schema_version: int
    capabilities: frozenset[str]
    unsupported: tuple[str, ...]
    limits: tuple[tuple[str, int], ...]

    def check_request(self, operation: str, payload: dict) -> None:
        required = _OPERATION_CAPABILITIES.get(operation)
        if required is None or not required <= self.capabilities:
            raise MemoryError("capability_unavailable")
        if ("expires_at" in payload or "include_expired" in payload) and (
            "record_expiry" not in self.capabilities
        ):
            raise MemoryError("capability_unavailable")
        limits = dict(self.limits)
        for field in ("content", "topic", "query"):
            if field in payload and len(payload[field]) > limits[f"max_{field}_chars"]:
                raise MemoryError("backend_limit_exceeded")
        if "limit" in payload and payload["limit"] > limits["max_page_records"]:
            raise MemoryError("backend_limit_exceeded")
        if any(
            len(query) > limits["max_query_chars"]
            for query in [*payload.get("queries", []), *payload.get("terms", [])]
        ):
            raise MemoryError("backend_limit_exceeded")


def validate_backend_descriptor(raw: object) -> BackendDescriptor:
    """Fail closed on a different ABI, unknown fields or incompatible semantics.

    API v1 covers only local explicit records. It does not admit remote stores,
    snapshot restoration, automatic extraction or native lifecycle/checkpoints.
    """
    if type(raw) is not dict or raw.keys() != _DESCRIPTOR_FIELDS:
        raise MemoryError("unsupported_backend")
    value = cast(dict[str, Any], raw)
    if (
        type(value["api_version"]) is not int
        or value["api_version"] != 1
        or type(value["schema_version"]) is not int
        or not 1 <= value["schema_version"] < 2**31
        or not _matches(value["adapter_id"], r"[a-z][a-z0-9_]*", 64)
        or not _matches(value["adapter_version"], r"[A-Za-z0-9][A-Za-z0-9.+!_-]*", 128)
    ):
        raise MemoryError("unsupported_backend")
    expected = {
        "deployment": "trusted_profile_local",
        "query_semantics": "literal_case_sensitive_substring",
        "deletion": "terminal_tombstone_payload_purge_no_physical_erase_guarantee",
        "export_format": "personal.memory.record_page.v1",
        "export_scope": "current_records_and_tombstones_no_receipt_history",
    }
    if any(type(value[key]) is not str or value[key] != item for key, item in expected.items()):
        raise MemoryError("unsupported_backend")
    if type(value["data_recipients"]) is not list or value["data_recipients"]:
        raise MemoryError("unsupported_backend")
    capabilities = frozenset(_names(value["capabilities"]))
    unsupported = _names(value["unsupported"])
    if (
        "explicit_records" not in capabilities
        or not capabilities <= _CAPABILITIES
        or capabilities.intersection(unsupported)
    ):
        raise MemoryError("unsupported_backend")
    for key, ceiling in _LIMITS.items():
        if type(value[key]) is not int or not 1 <= value[key] <= ceiling:
            raise MemoryError("unsupported_backend")
    if value["max_nonterminal_mutations"] > value["max_total_mutations"]:
        raise MemoryError("unsupported_backend")
    return BackendDescriptor(
        adapter_id=value["adapter_id"],
        adapter_version=value["adapter_version"],
        schema_version=value["schema_version"],
        capabilities=capabilities,
        unsupported=unsupported,
        limits=tuple((key, value[key]) for key in _LIMITS),
    )


@dataclass(frozen=True)
class AdapterCandidate:
    """Exact review target, not a code signature, authorization or loaded backend."""

    adapter_id: str
    distribution: str
    version: str
    entry_point: str


def _candidate(adapter_id, distribution, version, entry_point) -> AdapterCandidate:
    if (
        not _matches(adapter_id, r"[a-z][a-z0-9_]*", 64)
        or not _matches(distribution, r"[A-Za-z0-9][A-Za-z0-9._-]*", 128)
        or not _matches(version, r"[A-Za-z0-9][A-Za-z0-9.+!_-]*", 128)
        or not _matches(
            entry_point,
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
            r":[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
            256,
        )
    ):
        raise MemoryError("invalid_adapter_metadata")
    if adapter_id in _RESERVED_IDS:
        raise MemoryError("reserved_adapter_id")
    return AdapterCandidate(
        adapter_id, re.sub(r"[-_.]+", "-", distribution).lower(), version, entry_point
    )


def discover_adapter_candidates() -> tuple[AdapterCandidate, ...]:
    """Read only the proposed project group's metadata, without calling load().

    The bundled adapter is selected by existing trusted code, not an entry point.
    Invalid/duplicate/reserved entries fail the entire review instead of choosing
    an arbitrary winner. Distribution/version pins are not artifact hashes.
    """
    candidates: dict[str, AdapterCandidate] = {}
    try:
        for entry in metadata.entry_points(group=ENTRY_POINT_GROUP):
            if len(candidates) >= 128:
                raise MemoryError("adapter_discovery_limit")
            if entry.group != ENTRY_POINT_GROUP or entry.dist is None:
                raise MemoryError("invalid_adapter_metadata")
            candidate = _candidate(
                entry.name, entry.dist.metadata["Name"], entry.dist.version, entry.value
            )
            if candidate.adapter_id in candidates:
                raise MemoryError("adapter_id_conflict")
            candidates[candidate.adapter_id] = candidate
    except MemoryError:
        raise
    except Exception:
        raise MemoryError("adapter_discovery_failed") from None
    return tuple(candidates[key] for key in sorted(candidates))


def select_reviewed_candidate(reviewed: AdapterCandidate) -> AdapterCandidate:
    """Re-read installed metadata and require an exact, explicit review target.

    No package is imported, installed, opened, activated or used as a fallback.
    The return value is not safe to execute without independent code/install and
    data-sharing admission. A future loader still needs an artifact/TOCTOU policy.
    """
    if type(reviewed) is not AdapterCandidate:
        raise MemoryError("invalid_adapter_metadata")
    pin = _candidate(
        reviewed.adapter_id, reviewed.distribution, reviewed.version, reviewed.entry_point
    )
    for candidate in discover_adapter_candidates():
        if candidate.adapter_id == pin.adapter_id:
            if candidate != pin:
                raise MemoryError("adapter_review_changed")
            return candidate
    raise MemoryError("adapter_not_installed")
