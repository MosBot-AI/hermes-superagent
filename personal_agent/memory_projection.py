"""Explicit private Markdown projection, with durable intent and fenced publication.

SQLite remains canonical. The caller serializes publication/invalidation with
canonical writers using BEGIN IMMEDIATE. No watcher, import, provider or network.
"""

import hashlib
import json
import os
import re
import stat
import unicodedata
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .memory_backend import MemoryError, _identifier, validate_expiry

SCHEMA = {
    "memory_projection": """CREATE TABLE memory_projection (
        id INTEGER PRIMARY KEY CHECK(id=1), target_watermark INTEGER NOT NULL,
        published TEXT, pending TEXT)"""
}
FILENAME = "records.md"
TEMP = ".records.md.pending"
MAX_BYTES = 16 * 1024 * 1024


def watermark(conn):
    return conn.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0]


def state(conn):
    row = conn.execute(
        "SELECT target_watermark,published,pending FROM memory_projection"
    ).fetchone()
    if row is None:
        return None
    try:
        result = {"target_watermark": row[0]}
        if type(row[0]) is not int or row[0] < 0:
            raise ValueError()
        for key, raw in zip(("published", "pending"), row[1:], strict=True):
            item = json.loads(raw) if raw else None
            if item is not None:
                if set(item) != {"token", "watermark", "sha256", "evaluated_at", "next_expiry"}:
                    raise ValueError()
                if not re.fullmatch(r"[0-9a-f-]{36}", item["token"]):
                    raise ValueError()
                if type(item["watermark"]) is not int or not 0 <= item["watermark"] <= row[0]:
                    raise ValueError()
                if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                    raise ValueError()
                validate_expiry(item["evaluated_at"])
                if item["evaluated_at"] is None:
                    raise ValueError()
                validate_expiry(item["next_expiry"])
            result[key] = item
        return result
    except ValueError, TypeError, KeyError, MemoryError:
        raise MemoryError("projection_state_corrupt") from None


def _plain(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "".join(
        json.dumps(c, ensure_ascii=True)[1:-1]
        if unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        else c
        for c in text
    )


def render(backend, conn, evaluated_at):
    """Whole canonical records only; generated text is never read back as authority."""
    from .local_memory import _COLUMNS

    backend._validate_expiries(conn)
    now = datetime.fromisoformat(evaluated_at)
    rows = conn.execute(
        f"SELECT {','.join(_COLUMNS)} FROM records WHERE status='active' ORDER BY sequence"
    ).fetchall()
    records = [backend._record(row, now) for row in rows]
    future = [r["expires_at"] for r in records if r["expires_at"] and not r["expired"]]
    lines = [
        "# Private local memory projection",
        "",
        "Generated snapshot, not canonical storage, a backup, instructions or permission.",
        "Do not edit this managed file. Use explicit memory commands for corrections.",
        "Status can change after generation. Run /personal-memory projection-status.",
        "Expired active records remain included and labelled; expiry is not deletion.",
        "",
        "Namespace: " + _plain(backend._namespace),
        "Watermark: " + str(watermark(conn)),
        "Evaluated at: " + evaluated_at,
        "Records: " + str(len(records)),
    ]
    for record in records:
        try:
            _identifier(record["record_id"])
        except MemoryError:
            raise MemoryError("storage_corrupt") from None
        # Indented JSON code blocks cannot become Markdown links/HTML/headings.
        lines.extend(["", "## Record " + record["record_id"], "", "    " + _plain(record)])
    data = ("\n".join(lines) + "\n").encode("utf-8")
    if len(data) > MAX_BYTES:
        raise MemoryError("projection_size_limit")
    return data, min(future) if future else None


class PrivateProjection:
    """Fixed managed files under a verified private POSIX memory directory.

    Same-UID hostile mutation is outside the existing local deployment contract.
    Dir-relative operations prevent symlink following and arbitrary destinations.
    """

    def __init__(self, directory: Path):
        self.directory = directory

    def bind(self, connection):
        databases = connection.execute("PRAGMA database_list").fetchall()
        main = [row[2] for row in databases if row[1] == "main"]
        if (
            len(main) != 1
            or not main[0]
            or Path(main[0]).name != "records.sqlite3"
            or Path(main[0]).parent.resolve() != self.directory.resolve()
        ):
            raise MemoryError("projection_storage_mismatch")

    def _directory(self):
        if os.name != "posix":
            raise MemoryError("unsupported_storage_platform")
        try:
            fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                os.close(fd)
                raise MemoryError("unsafe_storage_path")
            return fd
        except OSError:
            raise MemoryError("unsafe_storage_path") from None

    @staticmethod
    def _read(fd, name):
        try:
            source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise MemoryError("unsafe_projection_file") from None
        try:
            info = os.fstat(source)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > MAX_BYTES
            ):
                raise MemoryError("unsafe_projection_file")
            data = bytearray()
            while len(data) <= MAX_BYTES:
                part = os.read(source, min(65536, MAX_BYTES + 1 - len(data)))
                if not part:
                    return bytes(data)
                data.extend(part)
            raise MemoryError("projection_size_limit")
        finally:
            os.close(source)

    @staticmethod
    def _known(data, saved):
        if data is None:
            return
        allowed = {
            saved[key]["sha256"]
            for key in ("published", "pending")
            if saved and saved[key] is not None
        }
        if hashlib.sha256(data).hexdigest() not in allowed:
            raise MemoryError("projection_conflict")

    def inspect(self, saved):
        fd = self._directory()
        try:
            data = self._read(fd, FILENAME)
            temporary = self._read(fd, TEMP)
            self._known(data, saved)
            if temporary is not None and saved is None:
                raise MemoryError("projection_conflict")
            return hashlib.sha256(
                data
            ).hexdigest() if data is not None else None, temporary is not None
        finally:
            os.close(fd)

    def invalidate(self, saved):
        """Remove both published and crash-left staging payload before mutation commit."""
        fd = self._directory()
        try:
            data = self._read(fd, FILENAME)
            temporary = self._read(fd, TEMP)
            self._known(data, saved)
            if temporary is not None and saved is None:
                raise MemoryError("projection_conflict")
            for name, content in ((FILENAME, data), (TEMP, temporary)):
                if content is not None:
                    os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        except OSError:
            raise MemoryError("projection_io_error") from None
        finally:
            os.close(fd)

    def publish(self, data, saved):
        fd = self._directory()
        try:
            self._known(self._read(fd, FILENAME), saved)
            if self._read(fd, TEMP) is not None:
                # This fixed reserved staging filename is never an editable view.
                os.unlink(TEMP, dir_fd=fd)
                os.fsync(fd)
            out = os.open(
                TEMP, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            try:
                view = memoryview(data)
                while view:
                    count = os.write(out, view)
                    if count <= 0:
                        raise OSError("short write")
                    view = view[count:]
                os.fsync(out)
            finally:
                os.close(out)
            os.replace(TEMP, FILENAME, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        except OSError:
            raise MemoryError("projection_io_error") from None
        finally:
            os.close(fd)


def invalidate(backend, conn):
    saved = state(conn)
    if saved is None:
        return
    if backend._projection is None:
        raise MemoryError("projection_storage_required")
    backend._projection.invalidate(saved)
    conn.execute(
        "UPDATE memory_projection SET target_watermark=?,pending=NULL WHERE id=1",
        (watermark(conn),),
    )


def status(backend, conn, now):
    saved = state(conn)
    if backend._projection is None:
        raise MemoryError("projection_storage_required")
    sha, temporary = backend._projection.inspect(saved)
    published = saved["published"] if saved else None
    expired = bool(
        published
        and (
            datetime.fromisoformat(published["evaluated_at"]) > now
            or (
                published["next_expiry"] and datetime.fromisoformat(published["next_expiry"]) <= now
            )
        )
    )
    current = bool(
        published
        and published["watermark"] == watermark(conn)
        and sha == published["sha256"]
        and not expired
        and not temporary
        and saved["pending"] is None
    )
    return {
        "schema_version": "personal.memory.projection.v1",
        "enabled": saved is not None,
        "filename": FILENAME,
        "current_watermark": watermark(conn),
        "published": published,
        "pending": saved["pending"] if saved else None,
        "file_present": sha is not None,
        "staging_present": temporary,
        "current": current,
        "dirty": bool(saved and not current),
        "stale_by_time": expired,
        "scope": "private_generated_snapshot_not_backup_or_authority",
    }


def refresh(backend, conn):
    """Two commits, not a cross-filesystem transaction. No cached payload is published."""
    from . import memory_expiry

    if backend._projection is None:
        raise MemoryError("projection_storage_required")
    try:
        conn.execute("BEGIN IMMEDIATE")
        saved = state(conn)
        existing_sha, _ = backend._projection.inspect(saved)
        # Preserve a published file whose rename survived a prior metadata rollback.
        # The already committed pending digest proves it was generated by this store.
        if saved and saved["pending"] and existing_sha == saved["pending"]["sha256"]:
            conn.execute("UPDATE memory_projection SET published=pending WHERE id=1")
        evaluated = memory_expiry.utc_now()
        data, next_expiry = render(backend, conn, evaluated)
        intent = {
            "token": str(uuid4()),
            "watermark": watermark(conn),
            "sha256": hashlib.sha256(data).hexdigest(),
            "evaluated_at": evaluated,
            "next_expiry": next_expiry,
        }
        conn.execute(
            "INSERT INTO memory_projection VALUES (1,?,NULL,?) ON CONFLICT(id) DO UPDATE "
            "SET target_watermark=excluded.target_watermark,pending=excluded.pending",
            (intent["watermark"], json.dumps(intent, sort_keys=True)),
        )
        conn.execute("COMMIT")
        conn.execute("BEGIN IMMEDIATE")
        saved = state(conn)
        if saved is None or saved["pending"] != intent or watermark(conn) != intent["watermark"]:
            raise MemoryError("projection_changed", retryable=True)
        data, _ = render(backend, conn, evaluated)
        if hashlib.sha256(data).hexdigest() != intent["sha256"]:
            raise MemoryError("projection_changed", retryable=True)
        backend._projection.publish(data, saved)
        conn.execute("UPDATE memory_projection SET published=pending,pending=NULL WHERE id=1")
        conn.execute("COMMIT")
        # Return snapshot metadata, not a new unguarded filesystem inspection.
        return {"published": intent, "filename": FILENAME, "refresh_completed": True}
    except BaseException:
        backend._rollback(conn)
        raise


def disable(backend, conn):
    """Stop future coupling after safely removing known artifacts under the writer fence."""
    if backend._projection is None:
        raise MemoryError("projection_storage_required")
    saved = state(conn)
    # Even repeated disable must refuse an unknown file, never silently remove it.
    backend._projection.invalidate(saved)
    conn.execute("DELETE FROM memory_projection WHERE id=1")
    return {"enabled": False, "canonical_records_unchanged": True, "filename": FILENAME}
