"""Bounded preparation of native direct-message candidates, not a checkpoint.

Message UID syntax and hashes are locators for later source verification, never
proof that a message was durably stored, authored by the owner or authorized.
This module does no I/O and is not wired into any native callback or model tool.
"""

import hashlib
import re
from dataclasses import dataclass

from .memory_backend import MemoryError

MAX_MESSAGES = 256
MAX_MESSAGE_CHARS = 16384
MAX_TOTAL_CHARS = 65536
MAX_IDENTITIES = 1024


def _uid(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise MemoryError("checkpoint_source_identity_unavailable")
    return value


@dataclass(frozen=True)
class DirectEvidenceCandidate:
    """Immutable candidate only; the native durable source has not been resolved."""

    message_uid: str
    absorbed_message_uids: tuple[str, ...]
    role: str
    content: str
    content_sha256: str


@dataclass(frozen=True)
class PreparedCheckpointEvidence:
    messages: tuple[DirectEvidenceCandidate, ...]
    total_content_chars: int
    source_identity_count: int

    def diagnostic(self):
        """Safe metadata-only result: no content, identities, excerpts or hashes."""
        return {
            "schema_version": "personal.memory.checkpoint_preparation.v1",
            "message_count": len(self.messages),
            "source_identity_count": self.source_identity_count,
            "total_content_chars": self.total_content_chars,
            "source_verification": "not_performed",
            "durable_checkpoint": False,
            "automatic_ingestion": False,
            "scope": "bounded_unverified_candidates_not_source_coverage_or_authority",
        }


def prepare_checkpoint_evidence(messages):
    """Preserve direct prose and UID merge lineage; reject incomplete/ambiguous input.

    No silent truncation or filtering. The caller must use the actual host's
    normalizer first. Sidecars, tools, reasoning, display metadata and claimed
    author/session/grant fields are never copied. Empty evidence is refused, not
    evidence that a native transcript was successfully saved.
    """
    if type(messages) is not list or not messages:
        raise MemoryError("checkpoint_evidence_unavailable")
    if len(messages) > MAX_MESSAGES:
        raise MemoryError("checkpoint_evidence_limit")
    candidates = []
    identities = set()
    total_chars = 0
    for message in messages:
        if type(message) is not dict:
            raise MemoryError("checkpoint_evidence_invalid")
        role, content = message.get("role"), message.get("content")
        if role not in ("user", "assistant") or message.get("_compressed_summary"):
            raise MemoryError("checkpoint_source_kind_unsupported")
        if message.get("tool_calls"):
            raise MemoryError("checkpoint_source_kind_unsupported")
        if type(content) is not str or not content.strip():
            raise MemoryError("checkpoint_content_unsupported")
        if len(content) > MAX_MESSAGE_CHARS:
            raise MemoryError("checkpoint_evidence_limit")
        total_chars += len(content)
        if total_chars > MAX_TOTAL_CHARS:
            raise MemoryError("checkpoint_evidence_limit")
        try:
            encoded = content.encode("utf-8")
        except UnicodeEncodeError:
            raise MemoryError("checkpoint_content_unsupported") from None
        uid = _uid(message.get("message_uid"))
        absorbed = message.get("_absorbed_message_uids", [])
        if type(absorbed) is not list or len(absorbed) > MAX_IDENTITIES - 1:
            raise MemoryError("checkpoint_source_lineage_invalid")
        lineage = (uid, *(_uid(item) for item in absorbed))
        if len(set(lineage)) != len(lineage) or identities.intersection(lineage):
            raise MemoryError("checkpoint_source_identity_ambiguous")
        identities.update(lineage)
        if len(identities) > MAX_IDENTITIES:
            raise MemoryError("checkpoint_evidence_limit")
        candidates.append(
            DirectEvidenceCandidate(
                message_uid=uid,
                absorbed_message_uids=tuple(absorbed),
                role=role,
                content=content,
                content_sha256=hashlib.sha256(encoded).hexdigest(),
            )
        )
    return PreparedCheckpointEvidence(tuple(candidates), total_chars, len(identities))
