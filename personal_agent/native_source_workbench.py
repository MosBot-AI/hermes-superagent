"""Explicit current-session source review through the published native read API.

Observation digests are neither stable store identities nor native receipts. No
canonical memory, native transcript, cursor or checkpoint is written here.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .memory_backend import MemoryError
from .native_source_resolution import MAX_SOURCE_ROWS, _revision, _rows

OPERATIONS = frozenset({"source_list", "source_show"})
MAX_PAGE_SIZE = 20


def validate(operation, payload):
    if type(operation) is not str or operation not in OPERATIONS or type(payload) is not dict:
        raise MemoryError("invalid_request")
    fields = (
        {"limit", "after", "expected_snapshot"}
        if operation == "source_list"
        else {"message_uid", "expected_snapshot"}
    )
    if set(payload) != fields:
        raise MemoryError("invalid_request")
    expected = payload["expected_snapshot"]
    if expected is not None and (
        type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None
    ):
        raise MemoryError("invalid_request")
    uid = payload.get("after") if operation == "source_list" else payload["message_uid"]
    if uid is not None and (type(uid) is not str or re.fullmatch(r"[0-9a-f]{32}", uid) is None):
        raise MemoryError("invalid_request")
    if operation == "source_show" and (uid is None or expected is None):
        raise MemoryError("invalid_request")
    if operation == "source_list" and (
        type(payload["limit"]) is not int
        or not 1 <= payload["limit"] <= MAX_PAGE_SIZE
        or (uid is not None and expected is None)
    ):
        raise MemoryError("invalid_request")
    return dict(payload)


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def _private(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        raise MemoryError("source_unsafe_path")
    return info.st_dev, info.st_ino


def _binding(home):
    # Bind only this admitted profile's fixed native database. No request path,
    # session picker, filesystem search, alternate home, chmod or repair.
    if not isinstance(home, Path) or home != home.resolve() or not home.is_dir():
        raise MemoryError("source_unsafe_path")
    path = home / "state.db"
    try:
        identity = _private(path)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                _private(sidecar)
                if suffix == "-journal":
                    raise MemoryError("source_storage_unavailable")
    except FileNotFoundError:
        raise MemoryError("source_storage_unavailable") from None
    return path, identity


def _metadata(item):
    encoded = item.content.encode("utf-8")
    return {
        "message_uid": item.message_uid,
        "role": item.role,
        "content_chars": len(item.content),
        "content_bytes": len(encoded),
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
        "absorbed_uid_count": len(item.absorbed_message_uids),
    }


def inspect_sources(db, *, session_id, binding, operation, payload):
    """One complete bounded observation, using a caller-owned read-only handle.

    The native decoder can allocate each stored row before our payload bounds
    apply. A successful generation check is not a lock on future publication.
    ``binding`` is a trusted opener's transient scope marker, not user input.
    """
    payload = validate(operation, payload)
    if (
        type(session_id) is not str
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", session_id) is None
        or getattr(db, "read_only", None) is not True
        or type(binding) is not tuple
        or len(binding) != 3
        or type(binding[0]) is not str
        or any(type(n) is not int or n < 0 for n in binding[1:])
    ):
        raise MemoryError("source_read_failed")
    with db.transcript_read_snapshot() as consistent:
        if not callable(consistent) or type(consistent.pinned) is not bool:
            raise MemoryError("source_read_failed")
        session = db.get_session(session_id)
        if type(session) is not dict or session.get("id") != session_id:
            raise MemoryError("source_not_found")
        revision = _revision(
            db.conversation_revision(session_id, include_ancestors=False), session_id
        )
        if revision[1] > MAX_SOURCE_ROWS:
            raise MemoryError("checkpoint_source_limit")
        rows = db.get_messages(
            session_id,
            include_inactive=False,
            include_compacted=False,
            limit=MAX_SOURCE_ROWS + 1,
            offset=0,
            latest=False,
            include_ancestors=False,
        )
        sources, row_ids = _rows(rows, session_id, revision)
        eligible = [item for item in sources if item is not None]
        metadata = [_metadata(item) for item in eligible]
        # Include the complete validated read's row content/identity, even for
        # excluded rows, and the host revision. Only the digest leaves here.
        snapshot = _hash(
            [
                "personal.native-source-observation.v1",
                binding,
                revision,
                [
                    [
                        rid,
                        row["message_uid"],
                        row.get("role") if type(row.get("role")) is str else None,
                        row.get("content"),
                        row.get("absorbed_message_uids"),
                        source is not None,
                    ]
                    for rid, row, source in zip(row_ids, rows, sources, strict=True)
                ],
            ]
        )
        if payload["expected_snapshot"] is not None and payload["expected_snapshot"] != snapshot:
            raise MemoryError("source_snapshot_changed")
        data = {
            "snapshot": snapshot,
            "scope": "active_current_session_original_rows",
            "read_consistency": "pinned" if consistent.pinned else "generation_validated",
            "scanned_row_count": len(rows),
            "eligible_count": len(eligible),
            "excluded_count": len(rows) - len(eligible),
            "durable_checkpoint": False,
            "source_receipt": False,
            "automatic_ingestion": False,
        }
        positions = {item.message_uid: n for n, item in enumerate(eligible)}
        if operation == "source_list":
            after = payload["after"]
            if after is not None and after not in positions:
                raise MemoryError("source_not_found")
            start = positions[after] + 1 if after is not None else 0
            end = min(start + payload["limit"], len(eligible))
            data["items"] = metadata[start:end]
            data["next_after"] = eligible[end - 1].message_uid if end < len(eligible) else None
        else:
            uid = payload["message_uid"]
            if uid not in positions:
                raise MemoryError("source_not_found")
            pos = positions[uid]
            data["item"] = {
                **metadata[pos],
                "content": eligible[pos].content,
                "absorbed_message_uids": list(eligible[pos].absorbed_message_uids),
            }
        if consistent() is not True:
            raise MemoryError("source_generation_changed")
    return {"data": data, "replayed": False}


def run(home, session_id, operation, payload):
    """Supported command-only reader; never creates or migrates either store."""
    payload = validate(operation, payload)
    try:
        path, identity = _binding(home)
        from hermes_state import SessionDB  # ty: ignore[unresolved-import]

        with SessionDB(path, read_only=True) as reader:
            result = inspect_sources(
                reader,
                session_id=session_id,
                binding=(str(home), *identity),
                operation=operation,
                payload=payload,
            )
            if _binding(home) != (path, identity):
                raise MemoryError("source_generation_changed")
        return result
    except MemoryError:
        raise
    except Exception:
        raise MemoryError("source_read_failed") from None
