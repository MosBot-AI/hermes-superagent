"""Fenced, current-source-only local SQLite repack. Never historical restore.

All participating runtimes must use the coordination lock. Stop older runtimes
before deployment. Preserved old databases contain historical plaintext; this
is not physical erasure, an authentication boundary, or a same-UID sandbox.
"""

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import time
from pathlib import Path

from .local_memory import LocalMemoryBackend
from .memory_backend import MemoryError
from .memory_coordination import memory_lock
from .memory_snapshot import MAX_BYTES, TIMEOUT_SECONDS, _connect
from .task_cli import _private_database_file, _private_storage_directory
from .tasks import TaskError

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_PHASES = {"preparing", "prepared", "switching", "completed"}
_NOTICE = (
    "Current-source same-profile repack only. Retained old plaintext includes historical "
    "memory. No restore, physical erasure, provider change or remote authentication."
)


def validate(operation, payload):
    fields = {
        "maintenance_preview": set(),
        "maintenance_prepare": {"name", "expected_watermark"},
        "maintenance_commit": {"name"},
        "maintenance_status": {"name"},
        "maintenance_recover": {"name"},
    }
    if type(operation) is not str or operation not in fields or type(payload) is not dict:
        raise MemoryError("invalid_request")
    if set(payload) != fields[operation]:
        raise MemoryError("invalid_request")
    if "name" in payload and (
        type(payload["name"]) is not str or not _NAME.fullmatch(payload["name"])
    ):
        raise MemoryError("invalid_request")
    if "expected_watermark" in payload and (
        type(payload["expected_watermark"]) is not int
        or not 0 <= payload["expected_watermark"] < 2**63
    ):
        raise MemoryError("invalid_request")
    return dict(payload)


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise MemoryError("maintenance_timeout")


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _exists(path):
    return path.exists() or path.is_symlink()


def _identity(path):
    _private_database_file(path, create=False)
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise MemoryError("unsafe_storage_file")
    if info.st_size > MAX_BYTES:
        raise MemoryError("maintenance_size_limit")
    return [info.st_dev, info.st_ino]


def _canonical(conn, deadline):
    """Hash exact schema and every table row, including receipts and suppression.

    Not a semantic translation or a migration: same schema, same stored values.
    Ordering uses all columns, never unstable physical row order.
    """
    digest = hashlib.sha256()
    schema = conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name"
    ).fetchall()
    digest.update(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode())
    for kind, name, _, _ in schema:
        if kind != "table":
            continue
        _deadline(deadline)
        quoted = '"' + name.replace('"', '""') + '"'
        columns = len(conn.execute(f"SELECT * FROM {quoted} LIMIT 0").description)
        order = ",".join(str(index + 1) for index in range(columns))
        digest.update(name.encode() + b"\0")
        for row in conn.execute(f"SELECT * FROM {quoted} ORDER BY {order}"):
            _deadline(deadline)
            values = [
                ("bytes", value.hex()) if isinstance(value, bytes) else value for value in row
            ]
            digest.update(
                json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            )
    return digest.hexdigest()


def _inspect(path, namespace, deadline):
    identity = _identity(path)
    for suffix in ("-journal", "-wal", "-shm"):
        if _exists(path.with_name(path.name + suffix)):
            raise MemoryError("maintenance_sidecar_present")
    # Raw descriptor stays open through connection closure, preserving SQLite's
    # process-wide POSIX locks. Exclusive coordination excludes controlled peers.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    conn = None
    try:
        info = os.fstat(fd)
        if [info.st_dev, info.st_ino] != identity:
            raise MemoryError("maintenance_changed")
        header = os.read(fd, 100)
        if header[:16] != b"SQLite format 3\0" or header[18:20] != b"\x01\x01":
            raise MemoryError("maintenance_format_unsupported")
        conn = _connect(path, deadline)
        conn.execute("BEGIN")
        LocalMemoryBackend._validate_readonly(conn, namespace)
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise MemoryError("maintenance_corrupt")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise MemoryError("maintenance_corrupt")
        canonical = _canonical(conn, deadline)
        watermark = conn.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0]
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while block := os.read(fd, 1024 * 1024):
            _deadline(deadline)
            total += len(block)
            if total > MAX_BYTES:
                raise MemoryError("maintenance_size_limit")
            digest.update(block)
        if _identity(path) != identity or path.stat().st_size != total:
            raise MemoryError("maintenance_changed")
        return {
            "identity": identity,
            "bytes": total,
            "sha256": digest.hexdigest(),
            "canonical": canonical,
            "watermark": watermark,
        }
    finally:
        try:
            if conn is not None:
                conn.close()
        finally:
            os.close(fd)


def _write_json(path, data):
    """Atomic replacement of OUR fixed private metadata, followed by dir fsync."""
    if _exists(path):
        _identity(path)
    # Interrupted private temporary files are never adopted by later operations.
    fd, filename = tempfile.mkstemp(prefix=".maintenance-write-", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync(path.parent)
    except BaseException:
        # A process crash intentionally bypasses this best-effort cleanup.
        if _exists(temporary):
            temporary.unlink()
        raise


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MemoryError("maintenance_journal_invalid")
        result[key] = value
    return result


def _read_json(path):
    _identity(path)
    if path.stat().st_size > 16384:
        raise MemoryError("maintenance_journal_invalid")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8") as stream:
        data = json.load(stream, object_pairs_hook=_unique_pairs)
    return data


def _validate_journal(data, name, namespace):
    if (
        type(data) is not dict
        or set(data)
        != {"version", "name", "namespace", "phase", "source", "stage_identity", "stage"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or data["name"] != name
        or data["namespace"] != namespace
        or data["phase"] not in _PHASES
    ):
        raise MemoryError("maintenance_journal_invalid")
    for metadata in (data["source"], data["stage"]):
        if metadata is None and data["phase"] == "preparing":
            continue
        if type(metadata) is not dict or set(metadata) != {
            "identity",
            "bytes",
            "sha256",
            "canonical",
            "watermark",
        }:
            raise MemoryError("maintenance_journal_invalid")
        if (
            type(metadata["identity"]) is not list
            or len(metadata["identity"]) != 2
            or any(type(n) is not int or n < 0 for n in metadata["identity"])
            or type(metadata["bytes"]) is not int
            or not 0 < metadata["bytes"] <= MAX_BYTES
            or type(metadata["watermark"]) is not int
            or not 0 <= metadata["watermark"] < 2**63
            or any(
                type(metadata[k]) is not str or not re.fullmatch("[0-9a-f]{64}", metadata[k])
                for k in ("sha256", "canonical")
            )
        ):
            raise MemoryError("maintenance_journal_invalid")
    if (
        type(data["stage_identity"]) is not list
        or len(data["stage_identity"]) != 2
        or any(type(n) is not int or n < 0 for n in data["stage_identity"])
    ):
        raise MemoryError("maintenance_journal_invalid")
    if data["source"] is None or (
        data["stage"] is not None
        and (
            data["stage"]["canonical"] != data["source"]["canonical"]
            or data["stage"]["watermark"] != data["source"]["watermark"]
            or data["stage"]["identity"] != data["stage_identity"]
        )
    ):
        raise MemoryError("maintenance_journal_invalid")
    return data


def _match(path, expected, namespace, deadline):
    if not _exists(path) or _inspect(path, namespace, deadline) != expected:
        raise MemoryError("maintenance_changed")


def _prepare_stage(source, stage, journal, marker, namespace, deadline):
    _match(source, journal["source"], namespace, deadline)
    if _identity(stage) != journal["stage_identity"]:
        raise MemoryError("maintenance_changed")
    # Only this journal-owned stage is disposable. An interrupted backup/VACUUM
    # can leave a rollback journal: validate private files, then discard this
    # non-authoritative generation and reconstruct from the unchanged live one.
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = stage.with_name(stage.name + suffix)
        if _exists(sidecar):
            _identity(sidecar)
            sidecar.unlink()
    fd = os.open(stage, os.O_WRONLY | os.O_NOFOLLOW)
    try:
        os.ftruncate(fd, 0)
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync(stage.parent)
    target = sqlite3.connect(stage, isolation_level=None)
    conn = None
    try:
        target.execute("PRAGMA trusted_schema=OFF")
        target.execute("PRAGMA journal_mode=DELETE")
        target.execute("PRAGMA synchronous=FULL")
        target.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        conn = _connect(source, deadline)
        conn.execute("BEGIN")
        LocalMemoryBackend._validate_readonly(conn, namespace)

        def progress(status, remaining, total):
            _deadline(deadline)
            if total * conn.execute("PRAGMA page_size").fetchone()[0] > MAX_BYTES:
                raise MemoryError("maintenance_size_limit")

        conn.backup(target, pages=128, progress=progress, sleep=0.01)
        target.execute("VACUUM")
    finally:
        try:
            if conn is not None:
                conn.close()
        finally:
            target.close()
    metadata = _inspect(stage, namespace, deadline)
    if metadata["canonical"] != journal["source"]["canonical"]:
        raise MemoryError("maintenance_changed")
    fd = os.open(stage, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync(stage.parent)
    journal = {**journal, "phase": "prepared", "stage": metadata}
    _write_json(marker, journal)
    return journal


def _finish(source, stage, old, marker, completed, journal, namespace, deadline):
    if journal["phase"] in {"prepared", "switching"}:
        if journal["phase"] == "prepared" and (_exists(old) or not _exists(source)):
            raise MemoryError("maintenance_changed")
        # Exact inode+byte+canonical identities; no selection by newest timestamp.
        if _exists(source) and not _exists(old):
            _match(source, journal["source"], namespace, deadline)
            _match(stage, journal["stage"], namespace, deadline)
            journal = {**journal, "phase": "switching"}
            _write_json(marker, journal)
            os.rename(source, old)
            # Persist the retained name before persisting removal of live name.
            _sync(old.parent)
            _sync(source.parent)
        elif _exists(old):
            _match(old, journal["source"], namespace, deadline)
        else:
            raise MemoryError("maintenance_changed")
        if not _exists(source):
            _match(stage, journal["stage"], namespace, deadline)
            os.rename(stage, source)
            # Persist new live name before persisting removal of staged name.
            _sync(source.parent)
            _sync(stage.parent)
        elif _exists(stage):
            raise MemoryError("maintenance_changed")
        _match(source, journal["stage"], namespace, deadline)
        journal = {**journal, "phase": "completed"}
        _write_json(marker, journal)
    _match(source, journal["stage"], namespace, deadline)
    _match(old, journal["source"], namespace, deadline)
    if _exists(stage):
        raise MemoryError("maintenance_changed")
    if _exists(completed):
        if _read_json(completed) != journal:
            raise MemoryError("maintenance_changed")
    else:
        _write_json(completed, journal)
    marker.unlink()
    _sync(marker.parent)
    return journal


def _result(journal, *, pending):
    return {
        "data": {
            "name": journal["name"],
            "phase": journal["phase"],
            "pending": pending,
            "watermark": journal["source"]["watermark"],
            "source_bytes": journal["source"]["bytes"],
            "stage_bytes": journal["stage"]["bytes"] if journal["stage"] else None,
            "notice": _NOTICE,
        },
        "replayed": False,
    }


def maintain(bound_home: Path, operation: str, payload: dict) -> dict:
    """Explicit local operator only; caller must perform mode/config admission."""
    request = validate(operation, payload)
    mutation = operation in {"maintenance_prepare", "maintenance_commit", "maintenance_recover"}
    pending = False
    try:
        with memory_lock(bound_home, exclusive=True) as directory:
            namespace = "trusted-profile:" + hashlib.sha256(str(bound_home).encode()).hexdigest()
            source = directory / "records.sqlite3"
            marker = directory / ".maintenance.json"
            pending = _exists(marker)
            deadline = time.monotonic() + TIMEOUT_SECONDS
            if operation == "maintenance_preview":
                if pending:
                    raise MemoryError("maintenance_pending")
                metadata = _inspect(source, namespace, deadline)
                return {
                    "data": {
                        "watermark": metadata["watermark"],
                        "bytes": metadata["bytes"],
                        "notice": _NOTICE,
                    },
                    "replayed": False,
                }
            name = request["name"]
            area = directory / "maintenance"
            _private_storage_directory(area)
            if operation == "maintenance_prepare":
                area.mkdir(mode=0o700, exist_ok=True)
            if not area.is_dir():
                raise MemoryError("maintenance_not_found")
            if stat.S_IMODE(area.stat().st_mode) & 0o077:
                raise MemoryError("unsafe_storage_path")
            stage, old = area / (name + ".stage.sqlite3"), area / (name + ".old.sqlite3")
            completed = area / (name + ".json")
            if pending:
                journal = _validate_journal(_read_json(marker), name, namespace)
                if operation == "maintenance_prepare":
                    raise MemoryError("maintenance_pending")
            elif _exists(completed):
                journal = _validate_journal(_read_json(completed), name, namespace)
                if journal["phase"] != "completed":
                    raise MemoryError("maintenance_journal_invalid")
                if operation == "maintenance_prepare":
                    raise MemoryError("maintenance_exists")
                # New ordinary writes may now exist. Never compare/rollback them.
                return _result(journal, pending=False)
            elif operation == "maintenance_prepare":
                if _exists(stage) or _exists(old):
                    raise MemoryError("maintenance_exists")
                metadata = _inspect(source, namespace, deadline)
                if metadata["watermark"] != request["expected_watermark"]:
                    raise MemoryError("revision_conflict")
                fd = os.open(stage, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                _sync(area)
                journal = {
                    "version": 1,
                    "name": name,
                    "namespace": namespace,
                    "phase": "preparing",
                    "source": metadata,
                    "stage_identity": _identity(stage),
                    "stage": None,
                }
                pending = True
                _write_json(marker, journal)
            else:
                raise MemoryError("maintenance_not_found")
            if operation == "maintenance_status":
                return _result(journal, pending=True)
            if journal["phase"] == "preparing":
                journal = _prepare_stage(source, stage, journal, marker, namespace, deadline)
            if operation == "maintenance_prepare":
                return _result(journal, pending=True)
            journal = _finish(source, stage, old, marker, completed, journal, namespace, deadline)
            return _result(journal, pending=False)
    except MemoryError:
        raise
    except TaskError as error:
        raise MemoryError(error.code) from None
    except Exception:
        raise MemoryError(
            "maintenance_outcome_unknown" if mutation and pending else "maintenance_unavailable"
        ) from None
