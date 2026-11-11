"""Exact input suppression in synthetic namespaces, never semantic erasure."""

import pytest
from test_memory_candidates import accept_args, opened, propose

from personal_agent import local_memory, memory_sources
from personal_agent.memory_backend import MemoryError, MemoryService


def suppress(service, cid):
    return service.execute(
        "candidate_suppress_source", {"candidate_id": cid, "expected_revision": 1}
    )


def test_explicit_suppression_same_input_new_nonce_and_session_and_retries():
    backend, conn = opened()
    service = MemoryService(backend)
    a = propose(backend)["data"]["candidate_id"]
    b = propose(backend, key="sibling", source_turn="c" * 64)["data"]["candidate_id"]
    first = suppress(service, a)
    assert suppress(service, a) == {**first, "replayed": True}
    assert service.execute("candidate_list", {})["data"]["items"] == []
    assert (
        conn.execute("SELECT content,quote,source_digest FROM memory_candidates").fetchall()
        == [(None, None, None)] * 2
    )
    with pytest.raises(MemoryError, match="candidate_terminal"):
        service.execute("candidate_accept", accept_args(b))
    backend._session = "another session"
    with pytest.raises(MemoryError, match="candidate_source_suppressed"):
        propose(backend, key="new", source_turn="d" * 64)
    assert propose(backend, key="different", source_digest="e" * 64)["data"]["state"] == "pending"
    service.execute("remember", {"content": "explicit new choice", "request_id": "explicit"})


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_linked_mutation_suppresses_pending_but_not_already_accepted_sibling(operation):
    backend, conn = opened()
    service = MemoryService(backend)
    ids = [propose(backend, key=str(i))["data"]["candidate_id"] for i in range(3)]
    first = service.execute("candidate_accept", accept_args(ids[0]))
    second = service.execute("candidate_accept", accept_args(ids[1]))
    request = {
        "record_id": first["data"]["record"]["record_id"],
        "expected_revision": 1,
        "request_id": "mutation",
    }
    if operation == "correct":
        request["content"] = "corrected"
    service.execute(operation, request)
    assert (
        service.execute("get", {"record_id": second["data"]["record"]["record_id"]})["data"][
            "status"
        ]
        == "active"
    )
    with pytest.raises(MemoryError, match="candidate_terminal"):
        service.execute("candidate_accept", accept_args(ids[2]))
    assert service.execute("candidate_accept", accept_args(ids[0])) == {**first, "replayed": True}
    with pytest.raises(MemoryError, match="candidate_source_suppressed"):
        propose(backend, key="later", source_turn="f" * 64)
    assert conn.execute("SELECT count(*) FROM memory_source_suppressions").fetchone() == (1,)


def test_failure_rolls_back_suppression_lineage_and_mutation(monkeypatch):
    backend, conn = opened()
    service = MemoryService(backend)
    cid = propose(backend)["data"]["candidate_id"]
    accepted = service.execute("candidate_accept", accept_args(cid))
    sibling = propose(backend, key="sibling")["data"]["candidate_id"]
    old = list(conn.iterdump())
    original = memory_sources.suppress_record

    def fail(*args):
        original(*args)
        raise RuntimeError("synthetic")

    monkeypatch.setattr(memory_sources, "suppress_record", fail)
    with pytest.raises(RuntimeError):
        service.execute(
            "forget",
            {
                "record_id": accepted["data"]["record"]["record_id"],
                "expected_revision": 1,
                "request_id": "forget",
            },
        )
    assert list(conn.iterdump()) == old
    assert service.execute("candidate_get", {"candidate_id": sibling})["data"]["state"] == "pending"


def test_schema10_upgrade_no_backfill_and_readonly_no_migration(tmp_path):
    path = tmp_path / "memory.sqlite3"
    backend, conn = opened(path)
    cid = propose(backend)["data"]["candidate_id"]
    MemoryService(backend).execute("candidate_accept", accept_args(cid))
    conn.execute("DROP TABLE retained_source_decisions")
    for table in memory_sources.SCHEMA:
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version=10")
    conn.commit()
    old = list(conn.iterdump())
    backend.close()
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        local_memory.create_backend().open_readonly(
            conn, namespace_id="profile:test", session_ref="read"
        )
    assert list(conn.iterdump()) == old
    conn.close()
    backend, conn = opened(path)
    assert conn.execute("PRAGMA user_version").fetchone() == (13,)
    assert conn.execute("SELECT * FROM memory_source_lineage").fetchall() == []
    assert conn.execute("SELECT * FROM memory_source_suppressions").fetchall() == []
    assert MemoryService(backend).execute("candidate_accept", accept_args(cid))["replayed"]


def test_model_cannot_suppress_and_cas_failure_has_no_effect():
    backend, conn = opened()
    cid = propose(backend)["data"]["candidate_id"]
    service = MemoryService(backend)
    backend._source_kind = "activated_session_model"
    with pytest.raises(MemoryError, match="candidate_scope_required"):
        suppress(service, cid)
    backend._source_kind = "explicit_local_operator"
    with pytest.raises(MemoryError, match="revision_conflict"):
        service.execute("candidate_suppress_source", {"candidate_id": cid, "expected_revision": 2})
    assert conn.execute("SELECT * FROM memory_source_suppressions").fetchall() == []


def test_schema10_historical_snapshot_stays_inspectable_without_migration(tmp_path):
    import hashlib
    import time

    from personal_agent import memory_snapshot

    path = tmp_path / "old.sqlite3"
    backend, conn = opened(path)
    path.chmod(0o600)
    conn.execute("DROP TABLE retained_source_decisions")
    for table in memory_sources.SCHEMA:
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version=10")
    conn.commit()
    conn.close()
    original = path.read_bytes()
    result = memory_snapshot._metadata(path, "profile:test", time.monotonic() + 5)
    assert result["schema_version"] == 10
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original


@pytest.mark.parametrize("first", ["accept", "suppress"])
def test_two_connections_accept_suppress_order(tmp_path, first):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    path = tmp_path / "db"
    backend, conn = opened(path)
    a = propose(backend)["data"]["candidate_id"]
    b = propose(backend, key="b")["data"]["candidate_id"]
    conn.close()
    ready, release, secondary_ready, go, attempted = (Event() for _ in range(5))

    def primary():
        backend, conn = opened(path)

        def trace(sql):
            if sql == "COMMIT" and not ready.is_set():
                ready.set()
                assert release.wait(5)

        conn.set_trace_callback(trace)
        try:
            return (
                MemoryService(backend).execute("candidate_accept", accept_args(a))
                if first == "accept"
                else suppress(MemoryService(backend), b)
            )
        finally:
            conn.close()

    def secondary():
        backend, conn = opened(path)
        secondary_ready.set()
        assert go.wait(5)
        conn.set_trace_callback(lambda sql: attempted.set() if sql == "BEGIN IMMEDIATE" else None)
        try:
            return (
                suppress(MemoryService(backend), b)
                if first == "accept"
                else MemoryService(backend).execute("candidate_accept", accept_args(a))
            )
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        g = pool.submit(secondary)
        assert secondary_ready.wait(5)
        f = pool.submit(primary)
        try:
            assert ready.wait(5)
            go.set()
            assert attempted.wait(5)
            assert not g.done()
        finally:
            go.set()
            release.set()
        f.result(timeout=5)
        if first == "accept":
            g.result(timeout=5)
        else:
            with pytest.raises(MemoryError, match="candidate_terminal"):
                g.result(timeout=5)
    backend, conn = opened(path)
    assert conn.execute("SELECT count(*) FROM records").fetchone()[0] == int(first == "accept")
    assert conn.execute(
        "SELECT count(*) FROM memory_candidates WHERE state='pending'"
    ).fetchone() == (0,)


@pytest.mark.parametrize("committed", [False, True])
def test_process_crash_suppression_commit_boundary(tmp_path, committed):
    import os
    import subprocess
    import sys

    path = tmp_path / "db"
    backend, conn = opened(path)
    cid = propose(backend)["data"]["candidate_id"]
    conn.close()
    script = """import os,sys,sqlite3
from personal_agent.local_memory import create_backend
c=sqlite3.connect(sys.argv[1]);b=create_backend();b.open(c,namespace_id='profile:test',session_ref='crash')
if sys.argv[3]=='False':
 c.set_trace_callback(lambda sql: os._exit(79) if sql=='COMMIT' else None)
b.execute('candidate_suppress_source',{'candidate_id':sys.argv[2],'expected_revision':1})
os._exit(79)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), cid, str(committed)],
        env={**os.environ, "PYTHONPATH": os.getcwd()},
        timeout=10,
    )
    assert result.returncode == 79
    backend, conn = opened(path)
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert conn.execute("SELECT count(*) FROM memory_source_suppressions").fetchone()[0] == int(
        committed
    )
    assert MemoryService(backend).execute("candidate_get", {"candidate_id": cid})["data"][
        "state"
    ] == ("discarded" if committed else "pending")


def test_full_candidate_and_suppression_capacity_does_not_block_forget():
    from uuid import uuid4

    backend, conn = opened()
    service = MemoryService(backend)
    cid = propose(backend)["data"]["candidate_id"]
    template = list(conn.execute("SELECT * FROM memory_candidates").fetchone())
    accepted = service.execute("candidate_accept", accept_args(cid))
    for i in range(999):
        row = template.copy()
        row[0], row[1], row[3], row[10] = str(uuid4()), f"seed-{i}", f"{i:064x}", f"{i:064x}"
        conn.execute("INSERT INTO memory_candidates VALUES (" + ",".join("?" * 16) + ")", row)
        memory_sources.suppress(conn, row[10], row[0])
    conn.commit()
    assert conn.execute("SELECT count(*) FROM memory_source_suppressions").fetchone() == (999,)
    service.execute(
        "forget",
        {
            "record_id": accepted["data"]["record"]["record_id"],
            "expected_revision": 1,
            "request_id": "forget-full",
        },
    )
    assert conn.execute("SELECT count(*) FROM memory_source_suppressions").fetchone() == (1000,)
    with pytest.raises(MemoryError, match="candidate_limit"):
        propose(backend, key="overflow", source_digest="f" * 64)


def test_reviewed_expired_cleanup_also_suppresses_linked_input(monkeypatch):
    from personal_agent import memory_expiry

    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-11-10T00:00:00Z")
    backend, conn = opened()
    service = MemoryService(backend)
    cid = propose(backend)["data"]["candidate_id"]
    service.execute("candidate_accept", accept_args(cid, expires_at="2026-11-09T00:00:00Z"))
    sibling = propose(backend, key="sibling")["data"]["candidate_id"]
    preview = service.execute("expired_preview", {"before": "2026-11-10T00:00:00Z"})["data"]
    request = {
        "before": preview["before"],
        "limit": preview["limit"],
        "expected_snapshot": preview["snapshot"],
        "request_id": "cleanup",
    }
    result = service.execute("forget_expired", request)
    assert service.execute("forget_expired", request) == {**result, "replayed": True}
    assert (
        service.execute("candidate_get", {"candidate_id": sibling})["data"]["state"] == "discarded"
    )
    assert conn.execute("SELECT count(*) FROM memory_source_suppressions").fetchone() == (1,)


@pytest.mark.parametrize("table", list(memory_sources.SCHEMA))
def test_corrupt_new_fingerprint_refused(table):
    backend, conn = opened()
    cid = propose(backend)["data"]["candidate_id"]
    service = MemoryService(backend)
    if table == "memory_source_lineage":
        service.execute("candidate_accept", accept_args(cid))
    else:
        suppress(service, cid)
    conn.execute(f"UPDATE {table} SET source_digest=?", ("z" * 64,))
    conn.commit()
    with pytest.raises(MemoryError, match="storage_corrupt"):
        service.execute("list", {})


def test_operator_help_advertises_exact_scope_without_opening_storage():
    from personal_agent.conversation_memory import HELP, parse_command

    assert parse_command("help") == ("help", {})
    assert "candidate-suppress-source ID --expected-revision N" in HELP
    assert "same full input" in HELP
    assert "does not delete already accepted records or match paraphrases" in HELP
    assert "Operator-only suppression" in HELP
