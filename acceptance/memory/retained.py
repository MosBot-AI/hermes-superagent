"""Synthetic retained-source migration/repack composition, without a native host."""

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from personal_agent import PLUGIN_ID, memory_maintenance, memory_storage
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK, source_request_identity
from personal_agent.retained_sources import SCHEMA_V12


def _require(condition, label):
    if not condition:
        raise AssertionError(label)


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _path(home):
    return home / "plugin-data" / PLUGIN_ID / "memory" / "records.sqlite3"


@contextmanager
def _opened(home):
    """Ordinary authorized SDK writable open, including schema migration."""
    connection = sqlite3.connect(_path(home), isolation_level=None)
    backend = create_backend()
    namespace = "trusted-profile:" + _hash(str(home))
    try:
        backend.open(connection, namespace_id=namespace, session_ref="synthetic-repack")
        yield LocalMemorySDK(backend, LocalBinding(namespace, "synthetic-repack")), connection
    finally:
        backend.close()
        connection.close()


def _requests():
    result = []
    for kind in ("legacy", "observed"):
        for state in ("corrected", "forgotten", "discarded", "pending"):
            key = f"synthetic-{kind}-{state}"
            content = f"Synthetic source marker {key}"
            source = {"identity": _hash(key), "fingerprint": _hash(content), "role": "user"}
            if kind == "legacy":
                source["receipt_id"] = _hash("receipt:" + key)
            else:
                source.update(kind="observed_native_snapshot", observation_id=_hash(key + ":view"))
            result.append(
                {
                    "request_id": key,
                    "consumer_id": key,
                    "expected_sequence": 0,
                    "content": content,
                    "topic": "synthetic fixture",
                    "expires_at": None,
                    "retention": "independent_snapshot",
                    "source": source,
                }
            )
    return result


def _status(sdk, request):
    value = sdk.execute("source_status", source_request_identity(request))["data"]
    value.pop("evaluated_at", None)
    return value


def _logical_tables(connection):
    """Capture every table value directly, including payload and derived FTS tables."""
    schema = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    ).fetchall()
    tables = {}
    for kind, name, _, _ in schema:
        if kind != "table":
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows = [
            [({"blob_hex": value.hex()} if isinstance(value, bytes) else value) for value in row]
            for row in connection.execute("SELECT * FROM " + quoted)
        ]
        tables[name] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
    return {"schema": [list(row) for row in schema], "tables": tables}


def _capture(sdk, connection):
    # Independent explicit field snapshot, not the maintenance implementation's digest.
    return {
        "logical_store": _logical_tables(connection),
        "statuses": [_status(sdk, request) for request in _requests()],
        "cursors": [
            sdk.execute("source_cursor", {"consumer_id": r["consumer_id"]})["data"]
            for r in _requests()
        ],
        "rows": [
            list(row)
            for row in connection.execute(
                "SELECT request_id,consumer_id,source_sequence,request_digest,source_identity,"
                "source_fingerprint,source_role,source_receipt,source_kind,source_observation,"
                "state,record_id,receipt,suppressed FROM retained_source_decisions "
                "ORDER BY request_id"
            )
        ],
        "receipts": [
            list(row)
            for row in connection.execute(
                "SELECT request_id,digest,receipt FROM receipts ORDER BY request_id"
            )
        ],
    }


def _seed(sdk, requests):
    for request in requests:
        sdk.execute("source_stage", request)
        state = request["request_id"].rsplit("-", 1)[1]
        if state == "discarded":
            sdk.execute("source_discard", source_request_identity(request))
        elif state != "pending":
            record = sdk.execute("source_accept", request)["data"]["record"]
            payload = {
                "request_id": "mutate-" + request["request_id"],
                "record_id": record["record_id"],
                "expected_revision": 1,
            }
            if state == "corrected":
                payload["content"] = "Synthetic corrected replacement"
            sdk.execute("correct" if state == "corrected" else "forget", payload)


def _legacy_layout(connection):
    # Reconstruct the historical table layout before the ordinary writable migration.
    connection.execute("ALTER TABLE retained_source_decisions RENAME TO new_decisions")
    connection.execute(SCHEMA_V12["retained_source_decisions"])
    connection.execute(
        "INSERT INTO retained_source_decisions SELECT request_id,consumer_id,source_sequence,"
        "request_digest,source_identity,source_fingerprint,source_role,source_receipt,"
        "state,record_id,receipt,suppressed FROM new_decisions"
    )
    connection.execute("DROP TABLE new_decisions")
    connection.execute("PRAGMA user_version=12")


def _prepare(home):
    home.mkdir(mode=0o700)
    _path(home).parent.mkdir(parents=True, mode=0o700)
    with _opened(home) as (sdk, connection):
        _seed(sdk, _requests()[:4])
        _legacy_layout(connection)
        legacy = connection.execute(
            "SELECT request_digest,source_receipt,receipt FROM retained_source_decisions "
            "ORDER BY request_id"
        ).fetchall()
    _path(home).chmod(0o600)
    with _opened(home) as (sdk, connection):
        _require(connection.execute("PRAGMA user_version").fetchone() == (13,), "migration missing")
        _require(
            connection.execute(
                "SELECT request_digest,source_receipt,receipt FROM retained_source_decisions "
                "ORDER BY request_id"
            ).fetchall()
            == legacy,
            "legacy receipt migration changed",
        )
        _seed(sdk, _requests()[4:])
        return _capture(sdk, connection)


def _refuses(sdk, request, code):
    try:
        sdk.execute("source_stage", request)
    except MemoryError as error:
        _require(error.code == code, "unexpected admission refusal")
    else:
        raise AssertionError("unsafe source admission succeeded")


def _verify(home, expected):
    with _opened(home) as (sdk, connection):
        _require(_capture(sdk, connection) == expected, "retained metadata changed after repack")
        for request, status in zip(_requests(), expected["statuses"], strict=True):
            decision = status["decision"]
            _require(
                sdk.execute("source_stage", request) == {"data": decision, "replayed": True},
                "exact stage replay changed",
            )
            state = request["request_id"].rsplit("-", 1)[1]
            if state != "pending":
                operation = "source_discard" if state == "discarded" else "source_accept"
                payload = source_request_identity(request) if state == "discarded" else request
                _require(
                    sdk.execute(operation, payload) == {"data": decision, "replayed": True},
                    "historical terminal receipt changed",
                )
            fresh = deepcopy(request)
            fresh["request_id"] += "-fresh"
            fresh["expected_sequence"] = 0 if state == "pending" else 1
            _refuses(
                sdk, fresh, "source_pending" if state == "pending" else "source_identity_conflict"
            )
            if state != "pending":
                fresh["source"]["identity"] = _hash(fresh["request_id"])
                fresh["consumer_id"] += "-other"
                fresh["expected_sequence"] = 0
                _refuses(sdk, fresh, "source_suppressed")
        _require(_capture(sdk, connection) == expected, "replay or refused admission changed state")


def _maintain(home, operation, **payload):
    with patch.object(memory_storage, "current_profile_home", lambda: home):
        return memory_maintenance.maintain(home, "maintenance_" + operation, payload)["data"]


def _deny_network(*_args, **_kwargs):
    raise AssertionError("Synthetic retained acceptance forbids network connections")


def _child(home, operation, expected=None):
    socket.create_connection = _deny_network
    socket.socket.connect = _deny_network
    socket.socket.connect_ex = _deny_network
    if operation == "verify":
        _verify(home, expected)
        return
    rename = os.rename

    def interrupted(source, destination):
        rename(source, destination)
        if destination.name.endswith(".old.sqlite3"):
            os._exit(73)

    with patch.object(memory_maintenance.os, "rename", interrupted):
        _maintain(home, "commit", name="retained")


def _process(home, operation, expected=None):
    root = str(Path(__file__).resolve().parents[2])
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONPATH": root,
    }
    return subprocess.run(
        [sys.executable, "-m", "acceptance.memory.retained", str(home), operation],
        input=json.dumps(expected),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def run_retained_repack_acceptance(workdir):
    """Raise on invariant failure; return bounded, payload-free synthetic evidence."""
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    for interrupted in (False, True):
        home = workdir / ("interrupted" if interrupted else "normal")
        expected = _prepare(home)
        watermark = _maintain(home, "preview")["watermark"]
        _maintain(home, "prepare", name="retained", expected_watermark=watermark)
        if interrupted:
            _require(_process(home, "interrupt").returncode == 73, "cutover interruption missing")
            _require(
                _maintain(home, "status", name="retained")["pending"], "pending recovery missing"
            )
            result = _maintain(home, "recover", name="retained")
        else:
            result = _maintain(home, "commit", name="retained")
        _require(result["phase"] == "completed", "repack incomplete")
        process = _process(home, "verify", expected)
        _require(process.returncode == 0, "fresh-process retained-source verification failed")
    return {
        "passed": True,
        "profiles": 2,
        "decisions_per_profile": 8,
        "schema_migration": "12_to_13_before_repack",
        "fresh_process_reopens": 2,
        "interrupted_cutovers": 1,
        "checks": [
            "all_logical_table_values",
            "explicit_metadata_and_receipts",
            "exact_replay",
            "pending_slot_exclusion",
            "identity_and_fingerprint_suppression",
        ],
    }


if __name__ == "__main__":
    _child(Path(sys.argv[1]), sys.argv[2], json.load(sys.stdin))
