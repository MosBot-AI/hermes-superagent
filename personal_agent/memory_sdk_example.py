"""Independent synthetic adapter example; NOT a production memory provider.

Only use an explicitly owned temporary directory and synthetic records. This
single-JSON-row SQLite implementation demonstrates the local explicit-record v1
protocol without importing LocalMemoryBackend. It is not a loader, migration
format, secure storage implementation, or canonical replacement certification.
"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .memory_adapters import validate_backend_descriptor
from .memory_backend import MemoryError, validate_request


class SyntheticMemoryAdapter:
    """Durable illustrative store with a fixed filename and synthetic scope."""

    def __init__(self, directory: Path):
        # The caller owns this test directory; never accept a model-provided path.
        self._connection = sqlite3.connect(Path(directory) / "synthetic-memory.sqlite3")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA secure_delete=ON")
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS synthetic_state "
                "(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)"
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO synthetic_state VALUES (1, ?)",
                (json.dumps({"records": [], "receipts": {}, "sequence": 0}),),
            )
        self._closed = False

    def describe(self) -> dict:
        return {
            "adapter_id": "synthetic_example",
            "adapter_version": "0.1.0",
            "api_version": 1,
            "schema_version": 1,
            "deployment": "trusted_profile_local",
            "capabilities": [
                "explicit_records",
                "durable_write",
                "cas",
                "idempotency",
                "literal_search",
                "bounded_record_export",
            ],
            "unsupported": ["checkpoint", "import_snapshot", "native_lifecycle"],
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

    def close(self) -> None:
        self._connection.close()
        self._closed = True

    def execute(self, operation: str, payload: dict) -> dict:
        if self._closed:
            raise MemoryError("not_open")
        request = validate_request(operation, payload)
        validate_backend_descriptor(self.describe()).check_request(operation, request)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            state = json.loads(
                self._connection.execute("SELECT body FROM synthetic_state WHERE id=1").fetchone()[
                    0
                ]
            )
            if operation in {"remember", "correct", "forget"}:
                result = self._mutate(state, operation, request)
                self._connection.execute(
                    "UPDATE synthetic_state SET body=? WHERE id=1", (json.dumps(state),)
                )
            else:
                result = self._read(state, operation, request)
            self._connection.commit()
            return result
        except BaseException as error:
            self._connection.rollback()
            if isinstance(error, sqlite3.Error):
                raise MemoryError("storage_unavailable") from None
            raise

    @staticmethod
    def _find(state, record_id):
        for record in state["records"]:
            if record["record_id"] == record_id:
                return record
        raise MemoryError("not_found")

    def _mutate(self, state, operation, request):
        digest = hashlib.sha256(
            json.dumps([operation, request], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        previous = state["receipts"].get(request["request_id"])
        if previous is not None:
            if previous["digest"] != digest:
                raise MemoryError("idempotency_conflict")
            return {"data": previous["receipt"], "replayed": True}
        nonterminal = sum(
            entry["receipt"]["operation"] != "forget" for entry in state["receipts"].values()
        )
        if len(state["receipts"]) >= 11000 or (operation != "forget" and nonterminal >= 10000):
            raise MemoryError("mutation_limit")
        now = datetime.now(UTC).isoformat()
        if operation == "remember":
            if len(state["records"]) >= 1000:
                raise MemoryError("record_limit")
            record = {
                "record_id": str(uuid4()),
                "revision": 1,
                "status": "active",
                "content": request["content"],
                "topic": request["topic"],
                "source": "explicit_local_operator",
                "session_ref": "synthetic-session",
                "created_at": now,
                "updated_at": now,
                "expires_at": None,
                "expired": False,
            }
            state["records"].append(record)
        else:
            record = self._find(state, request["record_id"])
            if record["status"] == "forgotten":
                raise MemoryError("record_forgotten")
            if record["revision"] != request["expected_revision"]:
                raise MemoryError("revision_conflict")
            record["revision"] += 1
            record["updated_at"] = now
            if operation == "forget":
                record["status"] = "forgotten"
                for key in ("content", "topic", "source", "session_ref"):
                    record[key] = None
            else:
                for key in ("content", "topic"):
                    if key in request:
                        record[key] = request[key]
        state["sequence"] += 1
        receipt = {key: record[key] for key in ("record_id", "revision", "status")}
        receipt.update(
            operation=operation, request_id=request["request_id"], event_sequence=state["sequence"]
        )
        state["receipts"][request["request_id"]] = {"digest": digest, "receipt": receipt}
        return {"data": receipt, "replayed": False}

    def _read(self, state, operation, request):
        if operation == "get":
            return self._find(state, request["record_id"])
        records = list(reversed(state["records"]))
        if request["after"] is not None:
            ids = [record["record_id"] for record in records]
            if request["after"] not in ids:
                raise MemoryError("invalid_cursor")
            records = records[ids.index(request["after"]) + 1 :]
        if operation != "export":
            records = [record for record in records if record["status"] == "active"]
        if operation == "search":
            records = [
                record
                for record in records
                if request["query"] in record["content"] or request["query"] in record["topic"]
            ]
        items = records[: request["limit"]]
        more = len(records) > len(items)
        result = {
            "items": items,
            "has_more": more,
            "next_cursor": items[-1]["record_id"] if more else None,
            "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if operation == "export":
            result.update(
                schema_version="personal.memory.record_page.v1",
                namespace_id="synthetic-example",
                watermark=state["sequence"],
                scope="current_records_and_tombstones_live_page",
                restorable=False,
            )
        return result
