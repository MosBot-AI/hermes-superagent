"""Adapter-attributed local records in a dedicated profile-bound SQLite store.

No ingestion, model, filesystem discovery, native provider replacement or network.
Host opens/protects/closes the supplied connection. Secure delete is not physical
media erasure and cannot revoke prior exports, backups or already returned text.
"""

import hashlib
import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from . import memory_expiry, memory_fts
from .memory_backend import MemoryError, _text, validate_expiry, validate_request
from .memory_candidate_store import SCHEMA as CANDIDATE_SCHEMA
from .memory_candidate_store import execute as execute_candidate
from .memory_checkpoints import CHECKPOINT_SCHEMA, checkpoint_status, create_checkpoint
from .memory_progress import PROGRESS_SCHEMA, advance_consumer, get_changes, get_consumer

_APPLICATION_ID = 0x50414D45
_SCHEMA_VERSION = 7
_SCHEMA_V1 = {
    "namespace": "CREATE TABLE namespace (id TEXT PRIMARY KEY NOT NULL)",
    "records": """CREATE TABLE records (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id TEXT UNIQUE NOT NULL, revision INTEGER NOT NULL CHECK(revision >= 1),
        status TEXT NOT NULL CHECK(status IN ('active','forgotten')),
        content TEXT, topic TEXT, source TEXT, session_ref TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        CHECK((status = 'active' AND content IS NOT NULL AND topic IS NOT NULL
          AND source = 'explicit_local_operator' AND session_ref IS NOT NULL)
          OR (status = 'forgotten' AND content IS NULL AND topic IS NULL
          AND source IS NULL AND session_ref IS NULL)))""",
    "receipts": """CREATE TABLE receipts (
        request_id TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, receipt TEXT NOT NULL)""",
    "events": """CREATE TABLE events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id TEXT NOT NULL, revision INTEGER NOT NULL, operation TEXT NOT NULL,
        UNIQUE(record_id, revision))""",
}
# Source describes the latest editing route, not verified human intent, facts,
# immutable authorship, or per-message user consent. Only trusted adapters bind it.
_SOURCE_KINDS = ("explicit_local_operator", "activated_session_model")
_SCHEMA_V2 = {
    **_SCHEMA_V1,
    "records": _SCHEMA_V1["records"].replace(
        "source = 'explicit_local_operator'",
        "source IN ('explicit_local_operator','activated_session_model')",
    ),
}
_SCHEMA_V3 = {**_SCHEMA_V2, **PROGRESS_SCHEMA}
_SCHEMA_V4 = {**_SCHEMA_V3, **CHECKPOINT_SCHEMA}
_SCHEMA_V5 = {
    **_SCHEMA_V4,
    "records": _SCHEMA_V4["records"].replace(
        "updated_at TEXT NOT NULL,", "updated_at TEXT NOT NULL, expires_at TEXT,"
    ),
}

_SCHEMA_V6 = {**_SCHEMA_V5, **CANDIDATE_SCHEMA}
_SCHEMA = {**_SCHEMA_V6, **memory_fts.SCHEMA}

_COLUMNS = (
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
)


def _storage_error(error: sqlite3.Error) -> MemoryError:
    code = (getattr(error, "sqlite_errorcode", 0) or 0) & 255
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return MemoryError("storage_busy", retryable=True)
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return MemoryError("storage_corrupt")
    return MemoryError("storage_error")


class LocalMemoryBackend:
    """Unopened adapter; transaction ownership prevents false durable receipts."""

    def __init__(self):
        self._connection = None
        self._namespace = None
        self._session = None
        self._source_kind = None
        self._read_only = False

    def describe(self) -> dict:
        result = {
            "adapter_id": "local_sqlite",
            "api_version": 1,
            "schema_version": _SCHEMA_VERSION,
            "adapter_version": "0.1.0",
            "deployment": "trusted_profile_local",
            "capabilities": [
                "review_candidates",
                "record_expiry",
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
            ],
            "unsupported": [
                "vector",
                "markdown_projection",
                "automatic_ingestion",
                "native_lifecycle",
                "checkpoint",
                "import_snapshot",
            ],
            "max_content_chars": 2048,
            "max_topic_chars": 128,
            "max_query_chars": 128,
            "max_page_records": 50,
            "max_total_records": 1000,
            "max_nonterminal_mutations": 10000,
            "max_total_mutations": 11000,
            "query_semantics": "literal_case_sensitive_substring",
            "deletion": "terminal_tombstone_payload_purge_no_physical_erase_guarantee",
            "export_format": "personal.memory.record_page.v1",
            "export_scope": "current_records_and_tombstones_no_receipt_history",
            "data_recipients": [],
        }

        if self._read_only:
            result["capabilities"] = [
                name
                for name in result["capabilities"]
                if name not in {"durable_write", "cas", "idempotency", "review_candidates"}
            ]
        return result

    def open(
        self,
        connection: sqlite3.Connection,
        *,
        namespace_id: str,
        session_ref: str,
        source_kind: str = "explicit_local_operator",
    ) -> None:
        """Bind trusted route metadata, never supplied by a mutation payload."""
        if self._connection is not None:
            raise MemoryError("already_open")
        if not isinstance(source_kind, str) or source_kind not in _SOURCE_KINDS:
            raise MemoryError("invalid_request")
        namespace_id = _text(namespace_id, 256)
        session_ref = _text(session_ref, 256)
        if connection.in_transaction:
            raise MemoryError("connection_in_transaction")
        began = False
        try:
            # Read ownership in one snapshot: another first opener may commit
            # between metadata queries. Refuse foreign files before journal changes.
            connection.execute("BEGIN")
            began = True
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            rows = connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            ).fetchall()
            if not (app_id == 0 and version == 0 and not rows):
                if app_id != _APPLICATION_ID:
                    raise MemoryError("foreign_database")
                if not self._valid_schema(version, rows):
                    raise MemoryError("unsupported_schema")
                if connection.execute("SELECT id FROM namespace").fetchall() != [(namespace_id,)]:
                    raise MemoryError("namespace_mismatch")
            connection.execute("COMMIT")
            began = False
            mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode not in {"delete", "memory"}:
                raise MemoryError("unsupported_journal")
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            began = True
            # Recheck under writer lock to serialize simultaneous first opens.
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            rows = connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            ).fetchall()
            if app_id == 0 and version == 0 and not rows:
                for sql in _SCHEMA_V6.values():
                    connection.execute(sql)
                memory_fts.create_index(connection)
                connection.execute("INSERT INTO namespace VALUES (?)", (namespace_id,))
                connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            elif app_id != _APPLICATION_ID:
                raise MemoryError("foreign_database")
            elif not self._valid_schema(version, rows):
                raise MemoryError("unsupported_schema")
            if connection.execute("SELECT id FROM namespace").fetchall() != [(namespace_id,)]:
                raise MemoryError("namespace_mismatch")
            if version == 1:
                self._upgrade_v1(connection)
            if version in (1, 2):
                for sql in PROGRESS_SCHEMA.values():
                    connection.execute(sql)
            if version in (1, 2, 3):
                for sql in CHECKPOINT_SCHEMA.values():
                    connection.execute(sql)
            if version in (1, 2, 3, 4):
                connection.execute("ALTER TABLE records ADD COLUMN expires_at TEXT")
                connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            if version in (1, 2, 3, 4, 5):
                for sql in CANDIDATE_SCHEMA.values():
                    connection.execute(sql)
                connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            if connection.execute("SELECT count(*) FROM records").fetchone()[0] > 1000:
                raise MemoryError("record_limit")
            if version in (1, 2, 3, 4, 5, 6):
                memory_fts.create_index(connection)
                connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            memory_fts.validate_index_config(connection)
            connection.execute("COMMIT")
        except BaseException as error:
            if began:
                self._rollback(connection)
            if isinstance(error, sqlite3.Error):
                raise _storage_error(error) from None
            raise
        self._connection, self._namespace, self._session = connection, namespace_id, session_ref
        self._source_kind = source_kind

    @staticmethod
    def _valid_schema(version, rows):
        expected = {
            1: _SCHEMA_V1,
            2: _SCHEMA_V2,
            3: _SCHEMA_V3,
            4: _SCHEMA_V4,
            5: _SCHEMA_V5,
            6: _SCHEMA_V6,
            7: _SCHEMA,
        }.get(version)
        return expected is not None and dict(rows) == expected and len(rows) == len(expected)

    @staticmethod
    def _upgrade_v1(connection):
        # Caller holds the writer lock and has revalidated schema and namespace.
        # Rebuild only records; receipt text/digests and event ordering stay intact.
        sequence = connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='records'"
        ).fetchone()
        connection.execute("ALTER TABLE records RENAME TO records_v1")
        connection.execute(_SCHEMA_V2["records"])
        connection.execute("INSERT INTO records SELECT * FROM records_v1")
        connection.execute("DROP TABLE records_v1")
        if sequence is not None:
            connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name='records'", sequence)
        connection.execute("PRAGMA user_version=2")

    @staticmethod
    def _rollback(connection):
        try:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def open_readonly(
        self, connection: sqlite3.Connection, *, namespace_id: str, session_ref: str
    ) -> None:
        """Bind an existing current-schema store without creation, migration or writes."""
        if self._connection is not None:
            raise MemoryError("already_open")
        namespace_id = _text(namespace_id, 256)
        session_ref = _text(session_ref, 256)
        if connection.in_transaction:
            raise MemoryError("connection_in_transaction")
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            self._validate_readonly(connection, namespace_id)
            connection.execute("COMMIT")
        except BaseException as error:
            self._rollback(connection)
            if isinstance(error, sqlite3.Error):
                raise _storage_error(error) from None
            raise
        self._connection, self._namespace, self._session = connection, namespace_id, session_ref
        self._read_only = True

    @staticmethod
    def _validate_readonly(connection, namespace_id):
        """Caller owns a read transaction; establish its snapshot before mode admission."""
        if connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID:
            raise MemoryError("foreign_database")
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise MemoryError("memory_reader_format_unsupported")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
        ).fetchall()
        if version != _SCHEMA_VERSION or not LocalMemoryBackend._valid_schema(version, rows):
            raise MemoryError("readonly_schema_unavailable")
        if connection.execute("SELECT id FROM namespace").fetchall() != [(namespace_id,)]:
            raise MemoryError("namespace_mismatch")
        memory_fts.validate_index_config(connection)
        if connection.execute("SELECT count(*) FROM records").fetchone()[0] > 1000:
            raise MemoryError("record_limit")

    def close(self) -> None:
        """Detach, without closing the host-owned connection."""
        self._connection = self._namespace = self._session = self._source_kind = None
        self._read_only = False

    def execute(self, operation: str, payload: dict) -> dict:
        request = validate_request(operation, payload)
        if self._read_only and operation.startswith("candidate_"):
            raise MemoryError("read_only_backend")
        if self._read_only and operation in {
            "remember",
            "correct",
            "forget",
            "consumer_advance",
            "checkpoint_create",
        }:
            raise MemoryError("read_only_backend")
        conn = self._connection
        if conn is None:
            raise MemoryError("not_open")
        if conn.in_transaction:
            raise MemoryError("connection_in_transaction")
        began = False
        try:
            conn.execute(
                "BEGIN IMMEDIATE"
                if operation.startswith("candidate_")
                or operation
                in {"remember", "correct", "forget", "consumer_advance", "checkpoint_create"}
                else "BEGIN"
            )
            began = True
            if self._read_only:
                self._validate_readonly(conn, self._namespace)
            # BEGIN is deferred for reads. Establish the SQLite snapshot before
            # sampling time so lock waits cannot admit an already expired row.
            conn.execute("SELECT id FROM namespace").fetchone()
            memory_fts.validate_index_config(conn)
            now = datetime.fromisoformat(memory_expiry.utc_now())
            if operation.startswith("candidate_"):
                result = execute_candidate(self, conn, operation, request, now)
            elif operation in {"remember", "correct", "forget"}:
                result = self._mutate(conn, operation, request, now)
            elif operation == "changes":
                result = get_changes(conn, request)
            elif operation == "consumer_get":
                result = get_consumer(conn, request["consumer_id"])
            elif operation == "consumer_advance":
                if self._source_kind != "explicit_local_operator":
                    raise MemoryError("consumer_scope_required")
                result = advance_consumer(conn, request)
            elif operation == "checkpoint_create":
                if self._source_kind != "explicit_local_operator":
                    raise MemoryError("checkpoint_scope_required")
                result = create_checkpoint(conn, request)
            elif operation == "checkpoint_status":
                result = checkpoint_status(conn, request["checkpoint_id"])
            elif operation == "get":
                result = self._get(conn, request["record_id"], now)
            elif operation == "recall":
                result = self._recall(conn, request, now)
            elif operation == "export":
                result = {
                    "schema_version": "personal.memory.record_page.v1",
                    "namespace_id": self._namespace,
                    "watermark": conn.execute(
                        "SELECT coalesce(max(sequence),0) FROM events"
                    ).fetchone()[0],
                    **self._page(conn, request, now, include_forgotten=True),
                    "scope": "current_records_and_tombstones_live_page",
                    "restorable": False,
                }
            else:
                result = self._page(conn, request, now)
            conn.execute("COMMIT")
            return result
        except BaseException as error:
            if began:
                self._rollback(conn)
            if isinstance(error, sqlite3.Error):
                raise _storage_error(error) from None
            raise

    @staticmethod
    def _record(row, now):
        record = dict(zip(_COLUMNS, row, strict=True))
        expiry = validate_expiry(record["expires_at"], error_code="storage_corrupt")
        if record["status"] == "forgotten" and expiry is not None:
            raise MemoryError("storage_corrupt")
        record["expired"] = expiry is not None and datetime.fromisoformat(expiry) <= now
        return record

    @staticmethod
    def _validate_expiries(conn):
        # Validate before SQL filtering: malformed dates must not hide private rows
        # behind a lexicographic comparison or a LIMIT boundary.
        rows = conn.execute("SELECT status,expires_at FROM records LIMIT 1001").fetchall()
        if len(rows) > 1000:
            raise MemoryError("record_limit")
        for status, expiry in rows:
            validate_expiry(expiry, error_code="storage_corrupt")
            if status == "forgotten" and expiry is not None:
                raise MemoryError("storage_corrupt")

    def _get(self, conn, record_id, now):
        row = conn.execute(
            f"SELECT {','.join(_COLUMNS)} FROM records WHERE record_id=?", (record_id,)
        ).fetchone()
        if row is None:
            raise MemoryError("not_found")
        return self._record(row, now)

    def _recall(self, conn, request, now):
        """Rank current whole records inside this call's existing read transaction.

        No derived index/cache or generated text can outlive a correction/forget.
        The snapshot may become historical after this read commits; returned
        source labels identify an editing route, not human intent or authority.
        """
        self._validate_expiries(conn)
        queries = request["queries"]
        matching = " OR ".join("instr(content, ?) > 0 OR instr(topic, ?) > 0" for _ in queries)
        args = [value for query in queries for value in (query, query)]
        rows = conn.execute(
            f"SELECT sequence,{','.join(_COLUMNS)} FROM records"
            f" WHERE status='active' AND ({matching}) ORDER BY sequence DESC LIMIT 1001",
            args,
        ).fetchall()
        if len(rows) > 1000:
            raise MemoryError("record_limit")
        ranked = []
        for row in rows:
            record = self._record(row[1:], now)
            if record["expired"]:
                continue
            matches = [
                index
                for index, query in enumerate(queries)
                if query in record["content"] or query in record["topic"]
            ]
            topic_matches = sum(query in record["topic"] for query in queries)
            ranked.append(
                (-len(matches), -topic_matches, -row[0], {**record, "matched_queries": matches})
            )
        ranked.sort(key=lambda item: item[:3])
        items = []
        used_chars = 2  # The exact ASCII JSON representation of the empty list.
        skipped_for_budget = 0
        for _, _, _, record in ranked:
            if len(items) == request["limit"]:
                break
            # Measure what callers receive, including escaped Unicode, quoting,
            # provenance, revisions and list separators. Never cut stored prose.
            size = len(json.dumps([*items, record], ensure_ascii=True, sort_keys=True))
            if size > request["max_chars"]:
                skipped_for_budget += 1
                continue
            items.append(record)
            used_chars = size
        return {
            "schema_version": "personal.memory.recall.v1",
            "evaluated_at": now.isoformat().replace("+00:00", "Z"),
            "items": items,
            "watermark": conn.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0],
            "matched_records": len(ranked),
            "omitted_records": len(ranked) - len(items),
            "skipped_for_budget": skipped_for_budget,
            "items_json_chars": used_chars,
            "max_chars": request["max_chars"],
            "scope": "current_active_records_single_read_snapshot",
            "ranking": "matched_query_count_then_topic_count_then_newest_creation",
            "authority": "stored_data_not_instructions_or_permission",
        }

    def _page(self, conn, request, now, include_forgotten=False):
        self._validate_expiries(conn)
        clauses, args = (["1=1"] if include_forgotten else ["status='active'"]), []
        if not include_forgotten and not request.get("include_expired", False):
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            args.append(now.isoformat(timespec="seconds").replace("+00:00", "Z"))
        if request["after"] is not None:
            row = conn.execute(
                "SELECT sequence FROM records WHERE record_id=?", (request["after"],)
            ).fetchone()
            if row is None:
                raise MemoryError("invalid_cursor")
            clauses.append("sequence < ?")
            args.append(row[0])
        if "query" in request:
            clauses.append("(instr(content, ?) > 0 OR instr(topic, ?) > 0)")
            args.extend([request["query"], request["query"]])
        if "terms" in request:
            term_clauses, term_args = memory_fts.term_filter(request["terms"])
            clauses.extend(term_clauses)
            args.extend(term_args)
        args.append(request["limit"] + 1)
        rows = conn.execute(
            f"SELECT {','.join(_COLUMNS)} FROM records WHERE {' AND '.join(clauses)}"
            " ORDER BY sequence DESC LIMIT ?",
            args,
        ).fetchall()
        more = len(rows) > request["limit"]
        items = [self._record(row, now) for row in rows[: request["limit"]]]
        return {
            **(
                {
                    "query_semantics": "all_case_sensitive_literal_substrings",
                    "index": "transactional_fts5_trigram_with_canonical_recheck",
                    "short_term_scan": any(len(term) < 3 for term in request["terms"]),
                    "index_stale": False,
                    "scope": "current_active_records_single_read_snapshot",
                    "authority": "stored_data_not_instructions_or_permission",
                }
                if "terms" in request
                else {}
            ),
            "items": items,
            "evaluated_at": now.isoformat().replace("+00:00", "Z"),
            "next_cursor": items[-1]["record_id"] if more else None,
            "has_more": more,
        }

    def _mutate(self, conn, operation, request, now):
        digest = hashlib.sha256(
            json.dumps(
                [operation, request], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        old = conn.execute(
            "SELECT digest,receipt FROM receipts WHERE request_id=?", (request["request_id"],)
        ).fetchone()
        if old:
            if old[0] != digest:
                raise MemoryError("idempotency_conflict")
            return {"data": json.loads(old[1]), "replayed": True}
        # At most 10,000 nonterminal edits plus one terminal forget per record.
        # Tombstones count toward the record cap, so cleanup cannot grow without bound.
        if (
            operation != "forget"
            and conn.execute("SELECT count(*) FROM events WHERE operation != 'forget'").fetchone()[
                0
            ]
            >= 10000
        ):
            raise MemoryError("mutation_limit")
        timestamp = now.isoformat()
        if operation == "remember":
            if conn.execute("SELECT count(*) FROM records").fetchone()[0] >= 1000:
                raise MemoryError("record_limit")
            record_id, revision, status = str(uuid4()), 1, "active"
            conn.execute(
                "INSERT INTO records(record_id,revision,status,content,topic,source,session_ref,"
                "created_at,updated_at,expires_at) VALUES (?,1,'active',?,?,?,?,?,?,?)",
                (
                    record_id,
                    request["content"],
                    request["topic"],
                    self._source_kind,
                    self._session,
                    timestamp,
                    timestamp,
                    request.get("expires_at"),
                ),
            )
        else:
            record_id = request["record_id"]
            current = self._get(conn, record_id, now)
            if current["status"] == "forgotten":
                raise MemoryError("record_forgotten")
            if current["revision"] != request["expected_revision"]:
                raise MemoryError("revision_conflict")
            revision = current["revision"] + 1
            status = "forgotten" if operation == "forget" else "active"
            content = None if operation == "forget" else request.get("content", current["content"])
            topic = None if operation == "forget" else request.get("topic", current["topic"])
            conn.execute(
                "UPDATE records SET revision=?,status=?,content=?,topic=?,source=?,session_ref=?,"
                "updated_at=?,expires_at=? WHERE record_id=? AND revision=?",
                (
                    revision,
                    status,
                    content,
                    topic,
                    None if operation == "forget" else self._source_kind,
                    None if operation == "forget" else self._session,
                    timestamp,
                    None
                    if operation == "forget"
                    else request.get("expires_at", current["expires_at"]),
                    record_id,
                    request["expected_revision"],
                ),
            )
        memory_fts.update_index(conn, record_id)
        cursor = conn.execute(
            "INSERT INTO events(record_id,revision,operation) VALUES (?,?,?)",
            (record_id, revision, operation),
        )
        receipt = {
            "record_id": record_id,
            "revision": revision,
            "status": status,
            "operation": operation,
            "request_id": request["request_id"],
            "event_sequence": cursor.lastrowid,
        }
        conn.execute(
            "INSERT INTO receipts VALUES (?,?,?)",
            (request["request_id"], digest, json.dumps(receipt, sort_keys=True)),
        )
        return {"data": receipt, "replayed": False}

    def changes(self, **request):
        return self.execute("changes", request)

    def checkpoint(self, *args, **kwargs):
        raise MemoryError("unsupported")

    def import_snapshot(self, *args, **kwargs):
        raise MemoryError("unsupported")


def create_backend() -> LocalMemoryBackend:
    """Return an unopened bundled adapter; no discovery/import of third-party code."""
    return LocalMemoryBackend()
