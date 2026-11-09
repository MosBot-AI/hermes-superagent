"""One explicitly managed editable Markdown draft; SQLite remains authoritative."""

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from uuid import uuid4

from .memory_backend import MemoryError, _identifier, _text, validate_expiry
from .memory_projection import PrivateProjection

FILENAME = "edit.md"
TEMP = ".edit.md.pending"
MAX_BYTES = 32768
NOTICE = (
    "Managed editable draft: apply/discard removes this file and staging, including your edits. "
    "For correction drafts, correcting/forgetting the target also removes them. "
    "No automatic expiry cleanup. "
    "Only content and topic are editable; this is not a backup, authority or instructions."
)
SCHEMA_V9 = {
    "memory_edits": """CREATE TABLE memory_edits (
    draft_id TEXT PRIMARY KEY NOT NULL, record_id TEXT NOT NULL, base_revision INTEGER NOT NULL,
    create_key TEXT UNIQUE NOT NULL, create_digest TEXT NOT NULL, created_at TEXT NOT NULL,
    publish_sha TEXT NOT NULL, state TEXT NOT NULL,
    slot INTEGER UNIQUE CHECK(slot IS NULL OR slot=1), action_digest TEXT, receipt TEXT,
    CHECK(base_revision>0),
    CHECK((state IN ('preparing','ready') AND slot=1 AND action_digest IS NULL AND receipt IS NULL)
       OR (state IN ('applied','discarded','invalidated') AND slot IS NULL)))"""
}
SCHEMA = {
    "memory_edits": SCHEMA_V9["memory_edits"]
    .replace(
        "record_id TEXT NOT NULL, base_revision INTEGER NOT NULL,",
        "record_id TEXT, base_revision INTEGER,",
    )
    .replace(
        "CHECK(base_revision>0),",
        "kind TEXT NOT NULL, expires_at TEXT, "
        "CHECK((kind='correction' AND record_id IS NOT NULL AND base_revision>0 "
        "AND expires_at IS NULL) "
        "OR (kind='new' AND record_id IS NULL AND base_revision IS NULL)),",
    )
}


COLUMNS = (
    "draft_id",
    "record_id",
    "base_revision",
    "create_key",
    "create_digest",
    "created_at",
    "publish_sha",
    "state",
    "slot",
    "action_digest",
    "receipt",
    "kind",
    "expires_at",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def validate(operation, payload):
    fields = {
        "edit_status": set(),
        "edit_new": {"expires_at", "request_id"},
        "edit_create": {"record_id", "expected_revision", "request_id"},
        "edit_preview": {"draft_id"},
        "edit_apply": {"draft_id", "expected_digest", "request_id"},
        "edit_discard": {"draft_id"},
    }
    if type(payload) is not dict or operation not in fields or payload.keys() != fields[operation]:
        raise MemoryError("invalid_request")
    value = dict(payload)
    for key in ("record_id", "draft_id"):
        if key in value:
            value[key] = _identifier(value[key])
    if "expected_revision" in value and (
        type(value["expected_revision"]) is not int
        or not 1 <= value["expected_revision"] < 2**63 - 1
    ):
        raise MemoryError("invalid_request")
    if "request_id" in value and (
        type(value["request_id"]) is not str
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value["request_id"])
    ):
        raise MemoryError("invalid_request")
    if "expected_digest" in value and (
        type(value["expected_digest"]) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", value["expected_digest"])
    ):
        raise MemoryError("invalid_request")
    if "expires_at" in value:
        value["expires_at"] = validate_expiry(value["expires_at"])
    return value


def rows(conn):
    values = conn.execute("SELECT * FROM memory_edits LIMIT 1001").fetchall()
    if len(values) > 1000:
        raise MemoryError("edit_limit")
    result = []
    try:
        for raw in values:
            row = dict(zip(COLUMNS, raw, strict=True))
            _identifier(row["draft_id"])
            if row["kind"] == "new":
                if row["record_id"] is not None or row["base_revision"] is not None:
                    raise ValueError()
                validate(
                    "edit_new", {"expires_at": row["expires_at"], "request_id": row["create_key"]}
                )
            elif row["kind"] != "correction" or row["expires_at"] is not None:
                raise ValueError()
            else:
                _identifier(row["record_id"])
            validate_expiry(row["created_at"], error_code="edit_state_corrupt")
            if row["kind"] == "correction":
                validate(
                    "edit_create",
                    {
                        "record_id": row["record_id"],
                        "expected_revision": row["base_revision"],
                        "request_id": row["create_key"],
                    },
                )
            for key in ("create_digest", "publish_sha"):
                if not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                    raise ValueError()
            if row["state"] not in {"preparing", "ready", "applied", "discarded", "invalidated"}:
                raise ValueError()
            if (row["slot"] == 1) != (row["state"] in {"preparing", "ready"}):
                raise ValueError()
            if row["action_digest"] is not None and not re.fullmatch(
                r"[0-9a-f]{64}", row["action_digest"]
            ):
                raise ValueError()
            if row["receipt"] is not None and type(json.loads(row["receipt"])) is not dict:
                raise ValueError()
            result.append(row)
    except MemoryError, ValueError, TypeError, KeyError:
        raise MemoryError("edit_state_corrupt") from None
    return result


def active(conn):
    return next((r for r in rows(conn) if r["slot"] == 1), None)


def get(conn, draft_id):
    row = next((r for r in rows(conn) if r["draft_id"] == draft_id), None)
    if row is None:
        raise MemoryError("edit_not_found")
    return row


def metadata(row):
    return {
        key: row[key]
        for key in ("draft_id", "record_id", "base_revision", "created_at", "kind", "expires_at")
    }


def header(backend, row):
    return {
        **{k: row[k] for k in ("draft_id", "record_id", "base_revision")},
        "namespace": backend._namespace,
        **({"kind": "new", "expires_at": row["expires_at"]} if row["kind"] == "new" else {}),
    }


def render(backend, row, record):
    return (
        "# Private memory edit draft\n"
        + json.dumps(header(backend, row), ensure_ascii=True, sort_keys=True)
        + "\nTopic: "
        + json.dumps(record["topic"], ensure_ascii=False)
        + "\n\n"
        + record["content"]
    ).encode("utf-8")


def parse(backend, row, data, *, allow_empty=False):
    try:
        title, identity, topic, blank, content = data.decode("utf-8").split("\n", 4)
        # Exact canonical identity line rejects duplicate keys and fabricated metadata.
        if (
            title != "# Private memory edit draft"
            or identity != json.dumps(header(backend, row), ensure_ascii=True, sort_keys=True)
            or blank
            or not topic.startswith("Topic: ")
        ):
            raise ValueError()
        return {
            "content": _text(content, 2048, multiline=True, empty=allow_empty),
            "topic": _text(json.loads(topic[7:]), 128, empty=True),
        }
    except ValueError, TypeError, MemoryError:
        raise MemoryError("edit_format_invalid") from None


class PrivateEdits(PrivateProjection):
    """Registered fixed paths are editable, including editor atomic replacements.

    Registration, not content/inode identity, owns their lifecycle. Same-UID
    hostile replacement is outside this boundary. Unregistered files are unknown.
    """

    @staticmethod
    def _read(fd, name):
        try:
            source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise MemoryError("unsafe_edit_file") from None
        try:
            info = os.fstat(source)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise MemoryError("unsafe_edit_file")
            if info.st_size > MAX_BYTES:
                raise MemoryError("edit_size_limit")
            data = bytearray()
            while len(data) <= MAX_BYTES:
                part = os.read(source, min(4096, MAX_BYTES + 1 - len(data)))
                if not part:
                    return bytes(data)
                data.extend(part)
            raise MemoryError("edit_size_limit")
        finally:
            os.close(source)

    def read_files(self, registered):
        fd = self._directory()
        try:
            data, temp = self._read(fd, FILENAME), self._read(fd, TEMP)
            if not registered and (data is not None or temp is not None):
                raise MemoryError("edit_file_conflict")
            if any(v is not None and len(v) > MAX_BYTES for v in (data, temp)):
                raise MemoryError("edit_size_limit")
            return data, temp
        except OSError:
            raise MemoryError("edit_io_error") from None
        finally:
            os.close(fd)

    def presence(self, registered):
        """Metadata only; oversized edits must not hide the recovery identifier."""
        fd = self._directory()
        try:
            found = []
            for name in (FILENAME, TEMP):
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    found.append(False)
                    continue
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) & 0o077
                ):
                    raise MemoryError("unsafe_edit_file")
                if not registered:
                    raise MemoryError("edit_file_conflict")
                found.append(True)
            return found
        except OSError:
            raise MemoryError("edit_io_error") from None
        finally:
            os.close(fd)

    def remove(self, registered):
        # Cleanup validates ownership/type, not payload size or syntax. A large
        # operator paste must remain discardable/forgettable without reading it.
        fd = self._directory()
        try:
            present = []
            for name in (FILENAME, TEMP):
                try:
                    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                except FileNotFoundError:
                    continue
                except OSError:
                    raise MemoryError("unsafe_edit_file") from None
                try:
                    info = os.fstat(source)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_uid != os.getuid()
                        or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) & 0o077
                    ):
                        raise MemoryError("unsafe_edit_file")
                    if not registered:
                        raise MemoryError("edit_file_conflict")
                    present.append(name)
                finally:
                    os.close(source)
            for name in present:
                os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        except OSError:
            raise MemoryError("edit_io_error") from None
        finally:
            os.close(fd)

    def publish_draft(self, data):
        existing, _ = self.read_files(True)
        if existing is not None:
            raise MemoryError("edit_file_conflict")
        self.remove(True)
        fd = self._directory()
        try:
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
            # No cooperating writer can create/replace these paths while fenced.
            if self._read(fd, FILENAME) is not None:
                raise MemoryError("edit_file_conflict")
            os.replace(TEMP, FILENAME, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        except OSError:
            raise MemoryError("edit_io_error") from None
        finally:
            os.close(fd)


def require_files(backend):
    if backend._edits is None:
        raise MemoryError("edit_storage_required")
    return backend._edits


def invalidate(backend, conn, record_id):
    row = active(conn)
    if row is not None and row["record_id"] == record_id:
        require_files(backend).remove(True)
        conn.execute(
            "UPDATE memory_edits SET state='invalidated',slot=NULL WHERE draft_id=?",
            (row["draft_id"],),
        )


def current_record(backend, conn, row, now):
    if row["kind"] == "new":
        return {"content": "", "topic": "", "expires_at": row["expires_at"]}
    record = backend._get(conn, row["record_id"], now)
    if record["status"] != "active":
        raise MemoryError("record_forgotten")
    if record["revision"] != row["base_revision"]:
        raise MemoryError("revision_conflict")
    return record


def create(backend, conn, request):
    from .memory_expiry import utc_now

    files = require_files(backend)
    identity = digest(request)
    try:
        conn.execute("BEGIN IMMEDIATE")
        values = rows(conn)
        row = next((r for r in values if r["create_key"] == request["request_id"]), None)
        replayed = row is not None
        if row is not None:
            if row["create_digest"] != identity:
                raise MemoryError("idempotency_conflict")
            if row["state"] != "preparing":
                conn.execute("COMMIT")
                return {
                    "data": {
                        **metadata(row),
                        "filename": FILENAME,
                        "state": row["state"],
                        "notice": NOTICE,
                    },
                    "replayed": True,
                }
        else:
            if active(conn) is not None:
                raise MemoryError("edit_active")
            if len(values) >= 1000:
                raise MemoryError("edit_limit")
            files.read_files(False)
            row = {
                "draft_id": str(uuid4()),
                "record_id": request.get("record_id"),
                "base_revision": request.get("expected_revision"),
                "kind": "correction" if "record_id" in request else "new",
                "expires_at": request.get("expires_at"),
                "create_key": request["request_id"],
                "create_digest": identity,
                "created_at": utc_now(),
                "publish_sha": "",
                "state": "preparing",
                "slot": 1,
                "action_digest": None,
                "receipt": None,
            }
            record = current_record(backend, conn, row, datetime.fromisoformat(row["created_at"]))
            row["publish_sha"] = hashlib.sha256(render(backend, row, record)).hexdigest()
            conn.execute(
                "INSERT INTO memory_edits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(row[k] for k in COLUMNS),
            )
        conn.execute("COMMIT")
        conn.execute("BEGIN IMMEDIATE")
        row = get(conn, row["draft_id"])
        if row["state"] != "preparing":
            raise MemoryError("edit_changed", retryable=True)
        record = current_record(backend, conn, row, datetime.fromisoformat(utc_now()))
        existing, _ = files.read_files(True)
        if existing is None:
            data = render(backend, row, record)
            if hashlib.sha256(data).hexdigest() != row["publish_sha"]:
                raise MemoryError("edit_changed", retryable=True)
            files.publish_draft(data)
        else:
            # A rename may have survived metadata rollback. Preserve any valid
            # operator edits; never overwrite this already published final file.
            parse(backend, row, existing, allow_empty=row["kind"] == "new")
        conn.execute("UPDATE memory_edits SET state='ready' WHERE draft_id=?", (row["draft_id"],))
        conn.execute("COMMIT")
        row["state"] = "ready"
        return {
            "data": {
                **metadata(row),
                "filename": FILENAME,
                "state": row["state"],
                "notice": NOTICE,
            },
            "replayed": replayed,
        }
    except BaseException:
        backend._rollback(conn)
        raise


def execute(backend, conn, operation, request, now):
    files = require_files(backend)
    if operation == "edit_status":
        row = active(conn)
        file_error = None
        try:
            present, staging = files.presence(row is not None)
        except MemoryError as error:
            present = staging = None
            file_error = error.code
        return {
            "data": {
                "active": {**metadata(row), "state": row["state"]} if row else None,
                "filename": FILENAME,
                "file_present": present,
                "staging_present": staging,
                "file_check_error": file_error,
                "notice": NOTICE,
            },
            "replayed": False,
        }
    row = get(conn, request["draft_id"])
    action = digest([operation, request])
    if row["slot"] is None:
        if row["action_digest"] == action and row["receipt"]:
            return {"data": json.loads(row["receipt"]), "replayed": True}
        raise MemoryError("edit_terminal")
    if operation == "edit_discard":
        files.remove(True)
        receipt = {**metadata(row), "state": "discarded", "canonical_records_unchanged": True}
    else:
        record = current_record(backend, conn, row, now)
        data, _ = files.read_files(True)
        if data is None:
            raise MemoryError("edit_file_missing")
        sha = hashlib.sha256(data).hexdigest()
        proposed = parse(backend, row, data)
        if operation == "edit_preview":
            return {
                "data": {
                    **metadata(row),
                    "state": row["state"],
                    "sha256": sha,
                    "before": None
                    if row["kind"] == "new"
                    else {k: record[k] for k in ("content", "topic")},
                    "operation": "remember" if row["kind"] == "new" else "correct",
                    "proposed": proposed,
                    "unchanged_expiry": record["expires_at"],
                    "notice": NOTICE,
                },
                "replayed": False,
            }
        if sha != request["expected_digest"]:
            raise MemoryError("edit_digest_conflict")
        # A new draft is a new intention, not a retry of another remember.
        # Successful retries have already returned through the terminal branch.
        if (
            row["kind"] == "new"
            and conn.execute(
                "SELECT 1 FROM receipts WHERE request_id=?", (request["request_id"],)
            ).fetchone()
        ):
            raise MemoryError("idempotency_conflict")
        result = backend._mutate(
            conn,
            "remember" if row["kind"] == "new" else "correct",
            {
                **proposed,
                **(
                    {"expires_at": row["expires_at"]}
                    if row["kind"] == "new"
                    else {
                        "record_id": row["record_id"],
                        "expected_revision": row["base_revision"],
                    }
                ),
                "request_id": request["request_id"],
            },
            now,
        )
        if row["kind"] == "new":
            files.remove(True)
        receipt = {**metadata(row), "state": "applied", "record": result["data"]}
    conn.execute(
        "UPDATE memory_edits SET state=?,slot=NULL,action_digest=?,receipt=? WHERE draft_id=?",
        (receipt["state"], action, json.dumps(receipt, sort_keys=True), row["draft_id"]),
    )
    return {"data": receipt, "replayed": False}
