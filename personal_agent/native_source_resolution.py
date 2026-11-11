"""Exact, ephemeral native source observations; not checkpoint receipts or authority.

The trusted caller owns the read-only SessionDB and binds the exact current
session. No request selects a file/profile/query, and no host import or write is
needed. This boundary is not isolation against malicious Python callers.
"""

import json
from dataclasses import dataclass, field

from .checkpoint_evidence import (
    MAX_IDENTITIES,
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    MAX_TOTAL_CHARS,
    DirectEvidenceCandidate,
    PreparedCheckpointEvidence,
    _uid,
    prepare_checkpoint_evidence,
)
from .memory_backend import MemoryError

MAX_SOURCE_ROWS = 256
MAX_LINEAGE_CHARS = MAX_IDENTITIES * 36 + 2
# Conservative superset of the pinned host's current/legacy summary classifiers.
# Quoting these markers can cause refusal; source classification is not authority.
SUMMARY_MARKERS = (
    "[CONTEXT COMPACTION — REFERENCE ONLY]",
    "[CONTEXT SUMMARY]:",
    "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]",
)


@dataclass(frozen=True)
class NativeSourceBinding:
    """Trusted code's binding, never constructed from candidate metadata."""

    store: object = field(repr=False)
    session_id: str = field(repr=False)


@dataclass(frozen=True)
class NativeSourceReference:
    """Private locators only, without a second copy of source text or its digest."""

    row_ids: tuple[int, ...] = field(repr=False)
    message_uids: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True)
class ResolvedCheckpointSources:
    references: tuple[NativeSourceReference, ...] = field(repr=False)
    session_id: str = field(repr=False)
    observed_revision: tuple = field(repr=False)
    scanned_row_count: int
    source_identity_count: int
    total_content_chars: int
    snapshot_pinned: bool

    def diagnostic(self):
        return {
            "schema_version": "personal.memory.source_resolution.v1",
            "source_verification": "exact_observed_match",
            "message_count": len(self.references),
            "scanned_row_count": self.scanned_row_count,
            "source_identity_count": self.source_identity_count,
            "total_content_chars": self.total_content_chars,
            "read_consistency": "pinned" if self.snapshot_pinned else "generation_validated",
            "scope": "active_current_session_observed_revision_only",
            "durable_checkpoint": False,
            "source_retention": False,
            "source_authority": False,
            "automatic_ingestion": False,
        }


def _validate_prepared(evidence):
    # Frozen dataclasses are publicly constructible: never trust their provenance.
    if (
        type(evidence) is not PreparedCheckpointEvidence
        or type(evidence.messages) is not tuple
        or not 0 < len(evidence.messages) <= MAX_MESSAGES
        or type(evidence.total_content_chars) is not int
        or type(evidence.source_identity_count) is not int
    ):
        raise MemoryError("checkpoint_evidence_invalid")
    messages = []
    for item in evidence.messages:
        if (
            type(item) is not DirectEvidenceCandidate
            or type(item.absorbed_message_uids) is not tuple
            or len(item.absorbed_message_uids) >= MAX_IDENTITIES
            or type(item.role) is not str
            or type(item.content_sha256) is not str
            or len(item.content_sha256) != 64
        ):
            raise MemoryError("checkpoint_evidence_invalid")
        messages.append(
            {
                "message_uid": item.message_uid,
                "_absorbed_message_uids": list(item.absorbed_message_uids),
                "role": item.role,
                "content": item.content,
            }
        )
    checked = prepare_checkpoint_evidence(messages)
    if checked != evidence:
        raise MemoryError("checkpoint_evidence_invalid")


def _revision(value, session_id):
    if (
        type(value) is not tuple
        or len(value) != 4
        or type(value[0]) is not tuple
        or value[0] != (session_id,)
        or any(type(n) is not int or n < 0 for n in value[1:])
    ):
        raise MemoryError("checkpoint_read_contract_unsupported")
    return value


def _rows(rows, session_id, revision):
    # get_messages bounds row count, NOT bytes allocated by the host decoder.
    # These finite content/lineage limits apply only after that public read.
    if type(rows) is not list or len(rows) > MAX_SOURCE_ROWS:
        raise MemoryError("checkpoint_source_limit")
    if len(rows) != revision[1]:
        raise MemoryError("checkpoint_source_scan_incomplete")
    messages, ids, identities = [], [], set()
    total_chars = 0
    for row in rows:
        if type(row) is not dict:
            raise MemoryError("checkpoint_read_contract_unsupported")
        row_id = row.get("id")
        if (
            type(row_id) is not int
            or row_id <= 0
            or (ids and row_id <= ids[-1])
            or row.get("session_id") != session_id
            or type(row.get("active")) is not int
            or row["active"] != 1
            or type(row.get("compacted")) is not int
            or row["compacted"] != 0
        ):
            raise MemoryError("checkpoint_source_scope_unsupported")
        raw = row.get("absorbed_message_uids")
        if raw is None:
            absorbed = []
        elif type(raw) is str and len(raw) <= MAX_LINEAGE_CHARS:
            try:
                absorbed = json.loads(raw)
            except ValueError, RecursionError:
                raise MemoryError("checkpoint_source_lineage_invalid") from None
        else:
            raise MemoryError("checkpoint_source_lineage_invalid")
        if type(absorbed) is not list or len(absorbed) >= MAX_IDENTITIES:
            raise MemoryError("checkpoint_source_lineage_invalid")
        lineage = (_uid(row.get("message_uid")), *(_uid(uid) for uid in absorbed))
        if len(set(lineage)) != len(lineage) or identities.intersection(lineage):
            raise MemoryError("checkpoint_source_identity_ambiguous")
        identities.update(lineage)
        if len(identities) > MAX_IDENTITIES:
            raise MemoryError("checkpoint_source_limit")
        content = row.get("content")
        if content is not None and type(content) is not str:
            raise MemoryError("checkpoint_content_unsupported")
        if content is not None:
            if len(content) > MAX_MESSAGE_CHARS:
                raise MemoryError("checkpoint_evidence_limit")
            total_chars += len(content)
            if total_chars > MAX_TOTAL_CHARS:
                raise MemoryError("checkpoint_evidence_limit")
            try:
                content.encode("utf-8")
            except UnicodeEncodeError:
                raise MemoryError("checkpoint_content_unsupported") from None
        eligible = (
            type(row.get("role")) is str
            and row["role"] in ("user", "assistant")
            and content is not None
            and bool(content.strip())
            and not any(marker in content for marker in SUMMARY_MARKERS)
            and not any(
                row.get(key)
                for key in (
                    "_compressed_summary",
                    "tool_calls",
                    "tool_call_id",
                    "tool_name",
                    "tool_call_uid",
                    "tool_call_uids",
                    "display_kind",
                )
            )
        )
        # Ineligible rows remain positional barriers, and their identities still
        # participate in the global ambiguity check. Never filter them away.
        messages.append(
            DirectEvidenceCandidate(lineage[0], tuple(absorbed), row.get("role"), content, "")
            if eligible
            else None
        )
        ids.append(row_id)
    if ids and ids[-1] != revision[2]:
        raise MemoryError("checkpoint_source_scan_incomplete")
    return tuple(messages), ids


def _match(evidence, source, ids):
    positions = {item.message_uid: n for n, item in enumerate(source) if item is not None}
    references, previous_end = [], None
    for candidate in evidence.messages:
        start = positions.get(candidate.message_uid)
        if start is None or (previous_end is not None and start != previous_end):
            raise MemoryError("checkpoint_source_mismatch")
        wanted = (candidate.message_uid, *candidate.absorbed_message_uids)
        first = source[start]
        lineage = (first.message_uid, *first.absorbed_message_uids)
        end = start + 1
        if lineage == wanted:
            content = first.content
        else:
            # Narrow proven resume repair: adjacent plain user rows, each with
            # one identity. Assistant repair strips/joins differently; reject it.
            if candidate.role != "user" or first.absorbed_message_uids:
                raise MemoryError("checkpoint_source_mismatch")
            end = start + len(wanted)
            selected = source[start:end]
            if (
                len(selected) != len(wanted)
                or any(
                    item is None
                    or item.role != "user"
                    or item.absorbed_message_uids
                    or item.content.startswith("\x00json:")
                    for item in selected
                )
                or tuple(item.message_uid for item in selected) != wanted
            ):
                raise MemoryError("checkpoint_source_mismatch")
            content = "\n\n".join(item.content for item in selected)
        if candidate.role != first.role or candidate.content != content:
            raise MemoryError("checkpoint_source_mismatch")
        references.append(NativeSourceReference(tuple(ids[start:end]), wanted))
        previous_end = end
    return tuple(references)


def resolve_checkpoint_sources(evidence, *, binding, expected_revision=None):
    """Observe exact persisted sources once; never retry or retain a receipt.

    ``expected_revision`` optionally fences a previously observed revision. Even
    a successful result can become stale immediately after the consistency call.
    The native snapshot is a read boundary, not a compression-commit fence.
    """
    _validate_prepared(evidence)
    if (
        type(binding) is not NativeSourceBinding
        or type(binding.session_id) is not str
        or not 0 < len(binding.session_id) <= 256
    ):
        raise MemoryError("checkpoint_source_binding_invalid")
    if expected_revision is not None:
        _revision(expected_revision, binding.session_id)
    db = binding.store
    try:
        if getattr(db, "read_only", None) is not True:
            raise MemoryError("checkpoint_read_contract_unsupported")
        with db.transcript_read_snapshot() as consistent:
            if not callable(consistent) or type(consistent.pinned) is not bool:
                raise MemoryError("checkpoint_read_contract_unsupported")
            revision = _revision(
                db.conversation_revision(binding.session_id, include_ancestors=False),
                binding.session_id,
            )
            if expected_revision is not None and revision != expected_revision:
                raise MemoryError("checkpoint_source_revision_changed")
            rows = db.get_messages(
                binding.session_id,
                include_inactive=False,
                include_compacted=False,
                limit=MAX_SOURCE_ROWS + 1,
                offset=0,
                latest=False,
                include_ancestors=False,
            )
            source, ids = _rows(rows, binding.session_id, revision)
            references = _match(evidence, source, ids)
            if consistent() is not True:
                raise MemoryError("checkpoint_source_generation_changed")
            result = ResolvedCheckpointSources(
                references,
                binding.session_id,
                revision,
                len(rows),
                evidence.source_identity_count,
                evidence.total_content_chars,
                consistent.pinned,
            )
        return result
    except MemoryError as error:
        safe_codes = {
            "checkpoint_read_contract_unsupported",
            "checkpoint_source_revision_changed",
            "checkpoint_source_limit",
            "checkpoint_source_scan_incomplete",
            "checkpoint_source_scope_unsupported",
            "checkpoint_source_lineage_invalid",
            "checkpoint_source_identity_unavailable",
            "checkpoint_source_identity_ambiguous",
            "checkpoint_content_unsupported",
            "checkpoint_evidence_limit",
            "checkpoint_source_mismatch",
            "checkpoint_source_generation_changed",
        }
        code = (
            error.code
            if type(error.code) is str and error.code in safe_codes
            else ("checkpoint_source_read_failed")
        )
        raise MemoryError(code) from None
    except Exception:
        raise MemoryError("checkpoint_source_read_failed") from None
