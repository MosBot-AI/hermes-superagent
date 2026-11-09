"""Atomic review candidates in synthetic stores; no host, model or network."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent import local_memory, memory_expiry
from personal_agent.memory_backend import MemoryError, MemoryService, validate_request


def opened(path=":memory:", source="explicit_local_operator"):
    connection = sqlite3.connect(path, timeout=5)
    backend = local_memory.create_backend()
    backend.open(
        connection, namespace_id="profile:test", session_ref="session:test", source_kind=source
    )
    return backend, connection


def proposal(key="p", **changes):
    return {
        "request_id": key,
        "content": "偏好中文",
        "topic": "",
        "quote": "中文",
        "quote_start": 0,
        "source_digest": "a" * 64,
        "source_turn": "b" * 64,
        **changes,
    }


def propose(backend, **changes):
    backend._source_kind = "activated_session_model"
    result = MemoryService(backend).execute("candidate_propose", proposal(**changes))
    backend._source_kind = "explicit_local_operator"
    return result


def accept_args(cid, **changes):
    return {"candidate_id": cid, "expected_revision": 1, "expires_at": None, **changes}


def test_accept_atomic_replay_after_forget_and_purge_payload():
    backend, conn = opened()
    candidate = propose(backend)["data"]
    service = MemoryService(backend)
    cid = candidate["candidate_id"]
    assert service.execute("recall", {"queries": ["中文"]})["data"]["items"] == []
    accepted = service.execute("candidate_accept", accept_args(cid))
    rid = accepted["data"]["record"]["record_id"]
    assert service.execute("get", {"record_id": rid})["data"]["source"] == "explicit_local_operator"
    service.execute(
        "correct",
        {"record_id": rid, "expected_revision": 1, "request_id": "correct", "content": "changed"},
    )
    service.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"})
    assert service.execute("candidate_accept", accept_args(cid)) == {**accepted, "replayed": True}
    assert service.execute("get", {"record_id": rid})["data"]["status"] == "forgotten"
    with pytest.raises(MemoryError, match="idempotency_conflict"):
        service.execute("candidate_accept", accept_args(cid, expires_at="2030-01-01T00:00:00Z"))
    row = conn.execute(
        "SELECT content,topic,quote,quote_start,source_digest,session_ref FROM memory_candidates"
    ).fetchone()
    assert row == (None,) * 6
    assert "content" not in service.execute("candidate_get", {"candidate_id": cid})["data"]
    assert propose(backend)["data"]["state"] == "accepted"
    assert conn.execute("SELECT count(*) FROM records").fetchone()[0] == 1


def test_crash_after_canonical_mutation_rolls_back_both(monkeypatch):
    backend, conn = opened()
    cid = propose(backend)["data"]["candidate_id"]
    original = backend._mutate

    def interrupted(*args):
        original(*args)
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(backend, "_mutate", interrupted)
    with pytest.raises(RuntimeError):
        backend.execute("candidate_accept", accept_args(cid))
    assert conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0
    assert backend.execute("candidate_get", {"candidate_id": cid})["data"]["state"] == "pending"
    monkeypatch.setattr(backend, "_mutate", original)
    assert backend.execute("candidate_accept", accept_args(cid))["data"]["state"] == "accepted"


def test_concurrent_accept_exactly_one_canonical_record(tmp_path):
    path = tmp_path / "memory.db"
    backend, conn = opened(path)
    cid = propose(backend)["data"]["candidate_id"]
    conn.close()
    barrier = Barrier(2)

    def run(_):
        worker, connection = opened(path)
        barrier.wait()
        result = worker.execute("candidate_accept", accept_args(cid))
        connection.close()
        return result

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert results[0]["data"] == results[1]["data"]
    backend, conn = opened(path)
    assert conn.execute("SELECT count(*) FROM records").fetchone()[0] == 1


def test_expiry_discard_terminal_caps_and_metadata(monkeypatch):
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2030-01-01T00:00:00Z")
    backend, conn = opened()
    first = propose(backend)["data"]
    assert first["expires_at"] == "2030-01-08T00:00:00Z"
    assert "quote" not in backend.execute("candidate_list", {})["data"]["items"][0]
    discarded = backend.execute(
        "candidate_discard", {"candidate_id": first["candidate_id"], "expected_revision": 1}
    )
    assert backend.execute(
        "candidate_discard", {"candidate_id": first["candidate_id"], "expected_revision": 1}
    ) == {**discarded, "replayed": True}
    propose(backend, key="p2")
    propose(backend, key="p3")
    with pytest.raises(MemoryError, match="candidate_turn_limit"):
        propose(backend, key="p4")
    backend._source_kind = "explicit_local_operator"
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2030-01-08T00:00:00Z")
    assert backend.execute("candidate_purge_expired", {})["data"] == {"purged": 2}
    assert backend.execute("candidate_list", {})["data"]["items"] == []
    assert (
        conn.execute("SELECT count(*) FROM memory_candidates WHERE content IS NOT NULL").fetchone()[
            0
        ]
        == 0
    )
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2029-01-01T00:00:00Z")
    assert propose(backend, key="p2")["data"]["state"] == "expired"


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_migration_preserves_all_existing_tables_and_receipts(version):
    conn = sqlite3.connect(":memory:")
    schema = getattr(local_memory, f"_SCHEMA_V{version}")
    for sql in schema.values():
        conn.execute(sql)
    conn.execute("INSERT INTO namespace VALUES ('profile:test')")
    conn.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version={version}")
    rid = str(uuid4())
    conn.execute(
        "INSERT INTO records(record_id,revision,status,created_at,updated_at) "
        "VALUES (?,2,'forgotten','old','old')",
        (rid,),
    )
    active_id = str(uuid4())
    conn.execute(
        "INSERT INTO records(record_id,revision,status,content,topic,source,"
        "session_ref,created_at,updated_at) "
        "VALUES (?,1,'active','preserve payload','topic','explicit_local_operator',"
        "'old-session','old','old')",
        (active_id,),
    )
    if version == 5:
        conn.execute(
            "UPDATE records SET expires_at='2035-01-01T00:00:00Z' WHERE record_id=?", (active_id,)
        )
    conn.execute(
        "INSERT INTO events(record_id,revision,operation) VALUES (?,1,'remember')", (active_id,)
    )
    conn.execute("INSERT INTO receipts VALUES ('old-key','old-digest','{\"exact\": true}')")
    conn.execute("INSERT INTO events(record_id,revision,operation) VALUES (?,2,'forget')", (rid,))
    conn.commit()
    original = {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in schema}
    backend = local_memory.create_backend()
    backend.open(conn, namespace_id="profile:test", session_ref="test")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
    for name, rows in original.items():
        actual = conn.execute(f"SELECT * FROM {name}").fetchall()
        if name == "records" and version < 5:
            actual = [row[:-1] for row in actual]
        assert actual == rows


def test_migration_failure_rolls_back(monkeypatch):
    conn = sqlite3.connect(":memory:")
    for sql in local_memory._SCHEMA_V5.values():
        conn.execute(sql)
    conn.execute("INSERT INTO namespace VALUES ('profile:test')")
    conn.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    conn.execute("PRAGMA user_version=5")
    conn.commit()
    monkeypatch.setattr(local_memory, "CANDIDATE_SCHEMA", {"broken": "INVALID SQL"})
    with pytest.raises(MemoryError):
        local_memory.create_backend().open(conn, namespace_id="profile:test", session_ref="test")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='memory_candidates'").fetchall()


def test_role_readonly_validation_and_proposal_conflict():
    backend, conn = opened()
    with pytest.raises(MemoryError, match="candidate_scope_required"):
        backend.execute("candidate_propose", proposal())
    cid = propose(backend)["data"]["candidate_id"]
    assert propose(backend)["replayed"]
    with pytest.raises(MemoryError, match="idempotency_conflict"):
        propose(backend, content="different")
    with pytest.raises(MemoryError, match="candidate_scope_required"):
        backend.execute("candidate_get", {"candidate_id": cid})
    backend._read_only = True
    assert "review_candidates" not in backend.describe()["capabilities"]
    with pytest.raises(MemoryError, match="capability_unavailable"):
        MemoryService(backend).execute("candidate_list", {})
    with pytest.raises(MemoryError, match="read_only_backend"):
        backend.execute("candidate_list", {})
    for bad in ({"quote_start": True}, {"quote": ""}, {"source_turn": "bad"}):
        with pytest.raises(MemoryError):
            validate_request("candidate_propose", proposal(**bad))
    with pytest.raises(MemoryError):
        validate_request("candidate_accept", {"candidate_id": cid, "expected_revision": 1})


def test_readonly_v5_refuses_without_migration_then_writer_upgrades(tmp_path):
    conn = sqlite3.connect(tmp_path / "v5.db")
    for sql in local_memory._SCHEMA_V5.values():
        conn.execute(sql)
    conn.execute("INSERT INTO namespace VALUES ('profile:test')")
    conn.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    conn.execute("PRAGMA user_version=5")
    conn.commit()
    before = list(conn.iterdump())
    reader = local_memory.create_backend()
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        reader.open_readonly(conn, namespace_id="profile:test", session_ref="test")
    assert list(conn.iterdump()) == before
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    # Reader enables query_only on this handle; a real permitted writer uses a new connection.
    conn.execute("PRAGMA query_only=OFF")
    writer = local_memory.create_backend()
    writer.open(conn, namespace_id="profile:test", session_ref="test")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 9


def test_candidate_capacity_includes_terminal_and_pagination():
    backend, conn = opened()
    original = propose(backend)["data"]
    row = list(conn.execute("SELECT * FROM memory_candidates").fetchone())
    for i in range(999):
        row[0], row[1], row[3] = str(uuid4()), f"fixture-{i}", f"{i:064x}"
        conn.execute("INSERT INTO memory_candidates VALUES (" + ",".join("?" * 16) + ")", row)
    conn.commit()
    page = backend.execute("candidate_list", {"limit": 20})["data"]
    assert len(page["items"]) == 20 and page["omitted_records"] == 980
    next_page = backend.execute("candidate_list", {"limit": 20, "after": page["next_cursor"]})[
        "data"
    ]
    assert not {item["candidate_id"] for item in page["items"]} & {
        item["candidate_id"] for item in next_page["items"]
    }
    backend.execute(
        "candidate_discard", {"candidate_id": original["candidate_id"], "expected_revision": 1}
    )
    with pytest.raises(MemoryError, match="candidate_limit"):
        propose(backend, key="overflow", source_turn="f" * 64)
    assert conn.execute("SELECT count(*) FROM memory_candidates").fetchone()[0] == 1000


def test_corrupt_receipt_and_candidate_payload_fail_closed():
    backend, conn = opened()
    cid = propose(backend)["data"]["candidate_id"]
    conn.execute("UPDATE memory_candidates SET source_digest='corrupt'")
    conn.commit()
    with pytest.raises(MemoryError, match="storage_corrupt"):
        backend.execute("candidate_get", {"candidate_id": cid})
    conn.execute("UPDATE memory_candidates SET source_digest=?", ("a" * 64,))
    conn.commit()
    backend.execute("candidate_accept", accept_args(cid))
    conn.execute("UPDATE memory_candidates SET receipt='{}'")
    conn.commit()
    with pytest.raises(MemoryError, match="storage_corrupt"):
        backend.execute("candidate_accept", accept_args(cid))


def test_expiry_time_sampled_after_writer_lock(tmp_path, monkeypatch):
    from threading import Event

    path = tmp_path / "locked.db"
    backend, conn = opened(path)
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2030-01-01T00:00:00Z")
    cid = propose(backend)["data"]["candidate_id"]
    ready, go = Event(), Event()
    sampled = []
    clock = ["2030-01-07T23:59:59Z"]

    def time_now():
        sampled.append(clock[0])
        return clock[0]

    monkeypatch.setattr(memory_expiry, "utc_now", time_now)

    def read():
        worker, connection = opened(path)
        ready.set()
        go.wait(5)
        result = worker.execute("candidate_get", {"candidate_id": cid})
        connection.close()
        return result

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(read)
        assert ready.wait(5)
        conn.execute("BEGIN IMMEDIATE")
        go.set()
        clock[0] = "2030-01-08T00:00:00Z"
        conn.execute("COMMIT")
        result = future.result(5)
    assert sampled == ["2030-01-08T00:00:00Z"]
    assert result["data"]["state"] == "expired" and "quote" not in result["data"]
