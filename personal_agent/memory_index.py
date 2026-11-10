"""Explicit fresh-connection FTS diagnosis and canonical-only derived recovery.

Not an adapter operation: this is operator maintenance of the bundled private
SQLite store. No migration, canonical mutation, historical receipt or file view.
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta

from . import memory_fts
from .local_memory import (
    _APPLICATION_ID,
    _COLUMNS,
    _SCHEMA,
    _SCHEMA_VERSION,
    LocalMemoryBackend,
    _storage_error,
)
from .memory_backend import MemoryError, _identifier, _text, validate_expiry
from .memory_checkpoints import _state
from .memory_coordination import memory_lock
from .memory_storage import existing_memory_path


def validate(operation, payload):
    fields = {"index_status": set(), "index_rebuild": {"expected_watermark"}}
    if type(payload) is not dict or operation not in fields or payload.keys() != fields[operation]:
        raise MemoryError("invalid_request")
    if operation == "index_rebuild" and (
        type(payload["expected_watermark"]) is not int
        or not 0 <= payload["expected_watermark"] < 2**63
    ):
        raise MemoryError("invalid_request")
    return dict(payload)


def _canonical(conn, namespace):
    if conn.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID:
        raise MemoryError("foreign_database")
    if conn.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
        raise MemoryError("memory_reader_format_unsupported")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    schema = conn.execute(
        "SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if version != _SCHEMA_VERSION or not LocalMemoryBackend._valid_schema(version, schema):
        raise MemoryError("unsupported_schema")
    if conn.execute("SELECT id FROM namespace").fetchall() != [(namespace,)]:
        raise MemoryError("namespace_mismatch")
    # Fixed table-specific checks never discard arbitrary errors from a global
    # integrity report. Check every ordinary table, including FTS shadow B-trees;
    # inverted-index semantics are checked separately below.
    for table in _SCHEMA:
        if table != "memory_fts":
            if conn.execute(f'PRAGMA integrity_check("{table}")').fetchall() != [("ok",)]:
                raise MemoryError("storage_corrupt")
    memory_fts.validate_index_config(conn)
    # Bound bytes before Python materializes any possibly corrupt payload.
    limits = {
        "record_id": 36,
        "status": 9,
        "content": 8192,
        "topic": 512,
        "source": 32,
        "session_ref": 1024,
        "created_at": 40,
        "updated_at": 40,
        "expires_at": 20,
    }
    for column, maximum in limits.items():
        if conn.execute(
            f"SELECT 1 FROM records WHERE length(CAST({column} AS BLOB))>? LIMIT 1",
            (maximum,),
        ).fetchone():
            raise MemoryError("storage_corrupt")
    if conn.execute(
        "SELECT 1 FROM events WHERE length(CAST(record_id AS BLOB))>36 "
        "OR length(CAST(operation AS BLOB))>8 LIMIT 1"
    ).fetchone():
        raise MemoryError("storage_corrupt")
    rows = conn.execute(f"SELECT {','.join(_COLUMNS)} FROM records LIMIT 1001").fetchall()
    if len(rows) > 1000:
        raise MemoryError("record_limit")
    try:
        for raw in rows:
            r = dict(zip(_COLUMNS, raw, strict=True))
            _identifier(r["record_id"])
            if type(r["revision"]) is not int or not 1 <= r["revision"] < 2**63:
                raise ValueError()
            for field in ("created_at", "updated_at"):
                dt = datetime.fromisoformat(r[field])
                if dt.utcoffset() != timedelta(0):
                    raise ValueError()
            validate_expiry(r["expires_at"])
            if r["status"] == "active":
                _text(r["content"], 2048, multiline=True)
                _text(r["topic"], 128, empty=True)
                _text(r["session_ref"], 256)
                if r["source"] not in {"explicit_local_operator", "activated_session_model"}:
                    raise ValueError()
            elif r["status"] != "forgotten" or any(
                r[k] is not None
                for k in ("content", "topic", "source", "session_ref", "expires_at")
            ):
                raise ValueError()
        sequences = conn.execute("SELECT sequence FROM records").fetchall()
        if any(type(v) is not int or v < 1 for (v,) in sequences):
            raise ValueError()
        state = _state(conn)
    except MemoryError, ValueError, TypeError, OverflowError:
        raise MemoryError("storage_corrupt") from None
    return {"current_watermark": state["through_sequence"], "record_count": len(rows)}


def _diagnose(conn):
    # Read stored FTS documents, not postings. Logical omissions are possible
    # even when the native FTS integrity command succeeds.
    indexed = conn.execute("SELECT count(*) FROM memory_fts_content").fetchone()[0]
    missing = conn.execute(
        "SELECT count(*) FROM records r LEFT JOIN memory_fts_content f ON f.id=r.sequence "
        "WHERE r.status='active' AND f.id IS NULL"
    ).fetchone()[0]
    extra = conn.execute(
        "SELECT count(*) FROM memory_fts_content f LEFT JOIN records r ON r.sequence=f.id "
        "WHERE r.sequence IS NULL OR r.status!='active'"
    ).fetchone()[0]
    mismatch = conn.execute(
        "SELECT count(*) FROM records r JOIN memory_fts_content f ON f.id=r.sequence "
        "WHERE r.status='active' AND (f.c0 IS NOT r.content OR f.c1 IS NOT r.topic)"
    ).fetchone()[0]
    native = "ok"
    conn.execute("SAVEPOINT index_check")
    try:
        conn.execute("INSERT INTO memory_fts(memory_fts,rank) VALUES('integrity-check',1)")
    except sqlite3.Error as error:
        if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_CORRUPT_VTAB:
            raise
        native = "corrupt"
    finally:
        conn.execute("ROLLBACK TO index_check")
        conn.execute("RELEASE index_check")
    return {
        "indexed_record_count": indexed,
        "missing_records": missing,
        "extra_records": extra,
        "mismatched_records": mismatch,
        "native_integrity": native,
        "index_current": native == "ok" and missing == extra == mismatch == 0,
    }


def _maintain(bound_home, operation, payload):
    request = validate(operation, payload)
    path = existing_memory_path(bound_home, allow_journal=True)
    namespace = "trusted-profile:" + hashlib.sha256(str(bound_home).encode()).hexdigest()
    conn = None
    try:
        # No ordinary backend.open(): that would access FTS before releasing its
        # migration transaction. This fresh handle acquires the writer fence
        # before its first schema/config/FTS access, including native integrity.
        conn = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None
        )
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("BEGIN IMMEDIATE")
        canonical = _canonical(conn, namespace)
        if (
            operation == "index_rebuild"
            and canonical["current_watermark"] != request["expected_watermark"]
        ):
            raise MemoryError("watermark_conflict")
        before = _diagnose(conn)
        if operation == "index_rebuild":
            conn.execute("DROP TABLE memory_fts")
            memory_fts.create_index(conn)
            after = _diagnose(conn)
            if not after["index_current"]:
                raise MemoryError("index_rebuild_failed")
        else:
            after = before
        conn.execute("COMMIT")
        return {
            "data": {
                **canonical,
                **after,
                "rebuilt": operation == "index_rebuild",
                "before": before if operation == "index_rebuild" else None,
                "scope": "current_canonical_fts_snapshot_not_backup_or_physical_erasure",
                "retry_semantics": "current_watermark_rebuild_not_historical_receipt",
                "sqlite_version": sqlite3.sqlite_version,
            },
            "replayed": False,
        }
    except sqlite3.Error as error:
        raise _storage_error(error) from None
    finally:
        if conn is not None:
            try:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            finally:
                conn.close()


def maintain(bound_home, operation, payload):
    validate(operation, payload)
    with memory_lock(bound_home):
        return _maintain(bound_home, operation, payload)
