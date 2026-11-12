"""Synthetic origin inspection: privacy, integrity, expiry and one read snapshot."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from test_memory_candidates import accept_args, propose
from test_retained_source_recovery import opened as disk_opened
from test_retained_sources import accept, opened, request

from personal_agent import memory_expiry, memory_record_origin
from personal_agent.memory_backend import MemoryError, MemoryService


def origin(sdk, rid):
    return sdk.execute("record_origin", {"record_id": rid})["data"]


@pytest.mark.parametrize("observed", [False, True])
@pytest.mark.parametrize("role", ["user", "assistant"])
def test_retained_origin_survives_edit_forget_and_historical_retry(observed, role):
    with opened() as (sdk, backend, _):
        payload = request(observed=observed)
        payload["source"]["role"] = role
        receipt = accept(sdk, payload)
        rid = receipt["record_id"]
        first = origin(sdk, rid)
        assert first["origin"] == {
            "kind": "observed_native_snapshot" if observed else "retained_native_snapshot",
            "role": role,
            "consumer_id": "native-source",
            "source_sequence": 1,
            "suppressed": False,
            "acceptance": {
                k: receipt[k] for k in ("record_id", "revision", "status", "event_sequence")
            },
        }
        backend._source_kind = "activated_session_model"
        backend.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "content": "model correction",
                "request_id": "correct",
            },
        )
        backend._source_kind = "explicit_local_operator"
        current = origin(sdk, rid)
        assert current["current_editing_route"] == "activated_session_model"
        assert current["current"]["revision"] == 2
        assert current["origin"] == {**first["origin"], "suppressed": True}
        sdk.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"})
        last = origin(sdk, rid)
        assert last["current_editing_route"] is None
        assert last["current"] == {
            "record_id": rid,
            "revision": 3,
            "status": "forgotten",
            "expires_at": None,
            "expired": False,
        }
        assert last["origin"] == current["origin"]
        assert sdk.execute("source_accept", payload)["data"]["record"] == receipt
        assert origin(sdk, rid)["origin"] == last["origin"]
        output = json.dumps(last)
        for forbidden in (
            "Synthetic original",
            "reviewed import",
            "model correction",
            "fingerprint",
            "request_id",
            "receipt_id",
            "observation_id",
            "session_ref",
            "source_turn",
        ):
            assert forbidden not in output
        assert len(output.encode()) <= memory_record_origin.MAX_OUTPUT_BYTES


def test_candidate_historical_acceptance_and_legacy_unavailable():
    with opened() as (sdk, backend, conn):
        cid = propose(backend)["data"]["candidate_id"]
        accepted = MemoryService(backend).execute("candidate_accept", accept_args(cid))
        rid = accepted["data"]["record"]["record_id"]
        first = origin(sdk, rid)
        assert first["origin"]["kind"] == "reviewed_candidate"
        assert first["origin"]["candidate_id"] == cid
        assert "role" not in first["origin"]
        sdk.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "content": "updated",
                "request_id": "correct",
            },
        )
        assert origin(sdk, rid)["origin"] == {**first["origin"], "suppressed": True}
        sdk.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"})
        assert origin(sdk, rid)["origin"]["acceptance"] == first["origin"]["acceptance"]
        assert MemoryService(backend).execute("candidate_accept", accept_args(cid))["replayed"]
        # Schema-10 migrations do not manufacture erased original lineage.
        conn.execute("DELETE FROM memory_source_suppressions")
        conn.execute("DELETE FROM memory_source_lineage")
        conn.commit()
        assert origin(sdk, rid)["origin"] == {"kind": "unavailable", "reason": "no_durable_lineage"}


def test_direct_record_never_infers_origin_from_latest_route():
    with opened() as (sdk, _, _):
        rid = sdk.execute("remember", {"request_id": "direct", "content": "private"})["data"][
            "record_id"
        ]
        assert origin(sdk, rid)["origin"]["kind"] == "unavailable"
        with pytest.raises(MemoryError, match="not_found"):
            origin(sdk, str(uuid4()))


@pytest.mark.parametrize(
    "at,expired", [("2030-01-01T00:00:00Z", False), ("2030-01-01T00:00:01Z", True)]
)
def test_exact_expiry_boundary(monkeypatch, at, expired):
    with opened() as (sdk, _, _):
        receipt = accept(sdk, request(expires_at="2030-01-01T00:00:01Z"))
        monkeypatch.setattr(memory_expiry, "utc_now", lambda: at)
        result = origin(sdk, receipt["record_id"])
        assert result["evaluated_at"] == at
        assert result["current"]["expired"] is expired
        assert result["origin"]["acceptance"]["status"] == "active"


def test_authorizer_rejects_payload_and_writes_including_unrelated_pending(monkeypatch):
    with opened() as (sdk, backend, conn):
        cid = propose(backend)["data"]["candidate_id"]
        receipt = MemoryService(backend).execute("candidate_accept", accept_args(cid))["data"][
            "record"
        ]
        propose(backend, key="unrelated", source_digest="b" * 64)

        def denied(*args, **kwargs):
            raise AssertionError("payload validator / native access must not run")

        monkeypatch.setattr("personal_agent.memory_sources.validate", denied)
        monkeypatch.setattr("personal_agent.memory_candidate_store.row_data", denied)
        before = conn.total_changes
        reads = []

        def authorize(action, table, column, *args):
            if action == sqlite3.SQLITE_READ:
                reads.append((table, column))
                if (table == "records" and column in {"content", "topic", "session_ref"}) or (
                    table == "memory_candidates"
                    and column
                    in {
                        "content",
                        "topic",
                        "quote",
                        "quote_start",
                        "source_digest",
                        "session_ref",
                        "source_turn",
                        "proposal_digest",
                    }
                ):
                    return sqlite3.SQLITE_DENY
            if action in {
                sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_ATTACH,
            }:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        assert origin(sdk, receipt["record_id"])["origin"]["kind"] == "reviewed_candidate"
        conn.set_authorizer(None)
        assert conn.total_changes == before
        assert ("memory_candidates", "receipt") in reads


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM receipts",
        "DELETE FROM events",
        "UPDATE namespace SET id='other'",
        "UPDATE records SET expires_at='bad'",
        "UPDATE records SET source=printf('%0100000d',1)",
        "UPDATE retained_source_decisions SET receipt='{}'",
        "UPDATE retained_source_decisions SET receipt=printf('%0100000d',1)",
        "UPDATE retained_source_decisions SET source_role='unknown'",
        "UPDATE retained_source_decisions SET source_sequence=2",
    ],
)
def test_corrupt_retained_metadata_fails_closed(sql):
    with opened() as (sdk, backend, conn):
        rid = accept(sdk, request())["record_id"]
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(sql)
        conn.commit()
        with pytest.raises(MemoryError, match="storage_corrupt"):
            backend.execute("record_origin", {"record_id": rid})


@pytest.mark.parametrize(
    "mutation",
    [
        "dangling",
        "discarded",
        "pending",
        "oversized",
        "duplicate",
        "wrong_receipt",
        "timestamp",
        "suppression",
    ],
)
def test_candidate_corruption_rejected_without_payload_reads(mutation):
    with opened() as (sdk, backend, conn):
        cid = propose(backend)["data"]["candidate_id"]
        accepted = MemoryService(backend).execute("candidate_accept", accept_args(cid))["data"]
        rid = accepted["record"]["record_id"]
        conn.execute("PRAGMA ignore_check_constraints=ON")
        if mutation == "dangling":
            conn.execute("UPDATE memory_source_lineage SET candidate_id=?", (str(uuid4()),))
        elif mutation in {"discarded", "pending"}:
            conn.execute("UPDATE memory_candidates SET state=?", (mutation,))
        elif mutation == "oversized":
            conn.execute("UPDATE memory_candidates SET receipt=?", ("x" * 100000,))
        elif mutation == "duplicate":
            raw = json.dumps(accepted)
            conn.execute(
                "UPDATE memory_candidates SET receipt=?", ('{"state":"accepted",' + raw[1:],)
            )
        elif mutation == "wrong_receipt":
            accepted["record"]["event_sequence"] += 1
            conn.execute("UPDATE memory_candidates SET receipt=?", (json.dumps(accepted),))
        elif mutation == "timestamp":
            conn.execute("UPDATE memory_candidates SET expires_at='2030-01-01T00:00:00Z'")
        else:
            conn.execute("UPDATE memory_candidates SET revision=1")
            conn.execute("INSERT INTO memory_source_suppressions VALUES (?,?)", ("a" * 64, cid))
        conn.commit()
        with pytest.raises(MemoryError, match="storage_corrupt"):
            backend.execute("record_origin", {"record_id": rid})


def test_dual_lineage_and_missing_suppression_rejected():
    with opened() as (sdk, backend, conn):
        rid = accept(sdk, request())["record_id"]
        cid = propose(backend)["data"]["candidate_id"]
        accepted = MemoryService(backend).execute("candidate_accept", accept_args(cid))["data"]
        conn.execute("UPDATE memory_source_lineage SET record_id=?", (rid,))
        conn.commit()
        with pytest.raises(MemoryError, match="storage_corrupt"):
            backend.execute("record_origin", {"record_id": rid})
        conn.execute(
            "UPDATE memory_source_lineage SET record_id=?", (accepted["record"]["record_id"],)
        )
        conn.commit()
        sdk.execute(
            "correct",
            {"record_id": rid, "expected_revision": 1, "content": "changed", "request_id": "edit"},
        )
        conn.execute("UPDATE retained_source_decisions SET suppressed=0")
        conn.commit()
        with pytest.raises(MemoryError, match="storage_corrupt"):
            backend.execute("record_origin", {"record_id": rid})


def test_snapshot_precedes_clock_and_concurrent_correction(tmp_path, monkeypatch):
    path = tmp_path / "memory.db"
    with disk_opened(path) as (sdk, _, _):
        rid = accept(sdk, request())["record_id"]
    ready, attempted, finished = Event(), Event(), Event()

    def writer():
        with disk_opened(path) as (sdk, _, _):
            ready.set()
            assert attempted.wait(5)
            sdk.execute(
                "correct",
                {
                    "record_id": rid,
                    "expected_revision": 1,
                    "content": "later",
                    "request_id": "race",
                },
            )
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer)
        assert ready.wait(5)
        with disk_opened(path, readonly=True) as (sdk, _, _):

            def clock():
                attempted.set()
                assert not finished.wait(0.05)
                return "2030-01-01T00:00:00Z"

            monkeypatch.setattr(memory_expiry, "utc_now", clock)
            before = origin(sdk, rid)
            assert before["current"]["revision"] == 1
            assert before["origin"]["suppressed"] is False
            monkeypatch.undo()
        future.result(timeout=10)
    with disk_opened(path, readonly=True) as (sdk, _, _):
        assert origin(sdk, rid)["current"]["revision"] == 2


def test_duplicate_retained_receipt_and_dangling_record_fail_closed():
    with opened() as (sdk, backend, conn):
        rid = accept(sdk, request())["record_id"]
        raw = conn.execute("SELECT receipt FROM retained_source_decisions").fetchone()[0]
        conn.execute(
            "UPDATE retained_source_decisions SET receipt=?", ('{"revision":1,' + raw[1:],)
        )
        conn.commit()
        with pytest.raises(MemoryError, match="storage_corrupt"):
            backend.execute("record_origin", {"record_id": rid})
        conn.execute("UPDATE retained_source_decisions SET receipt=?", (raw,))
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("UPDATE retained_source_decisions SET record_id=?", (str(uuid4()),))
        conn.commit()
        with pytest.raises(MemoryError, match="storage_corrupt"):
            backend.execute("record_origin", {"record_id": rid})


def test_candidate_correction_requires_source_suppression():
    with opened() as (sdk, backend, conn):
        cid = propose(backend)["data"]["candidate_id"]
        rid = MemoryService(backend).execute("candidate_accept", accept_args(cid))["data"][
            "record"
        ]["record_id"]
        sdk.execute(
            "correct",
            {"record_id": rid, "expected_revision": 1, "content": "updated", "request_id": "edit"},
        )
        conn.execute("DELETE FROM memory_source_suppressions")
        conn.commit()
        with pytest.raises(MemoryError, match="storage_corrupt"):
            backend.execute("record_origin", {"record_id": rid})


@pytest.mark.parametrize("matching,legacy", [(False, False), (True, False), (False, True)])
def test_suppression_digest_matches_same_candidate_lineage_only_when_retained(matching, legacy):
    with opened() as (sdk, backend, conn):
        cid = propose(backend)["data"]["candidate_id"]
        accepted = MemoryService(backend).execute("candidate_accept", accept_args(cid))["data"]
        rid = accepted["record"]["record_id"]
        if legacy:
            conn.execute("DELETE FROM memory_source_lineage")
        conn.execute(
            "INSERT INTO memory_source_suppressions VALUES (?,?)",
            (("a" if matching else "f") * 64, cid),
        )
        conn.commit()
        if not matching and not legacy:
            with pytest.raises(MemoryError, match="storage_corrupt"):
                backend.execute("record_origin", {"record_id": rid})
        else:
            result = origin(sdk, rid)["origin"]
            if legacy:
                assert result == {"kind": "unavailable", "reason": "no_durable_lineage"}
            else:
                assert result["kind"] == "reviewed_candidate" and result["suppressed"] is True
