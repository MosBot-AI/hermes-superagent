"""Atomic FTS lifecycle, bounded CJK queries and unchanged literal contracts."""

import sqlite3
from uuid import uuid4

import pytest

from personal_agent import local_memory, memory_fts
from personal_agent.memory_backend import MemoryError, MemoryService, validate_request


def opened(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA trusted_schema=OFF")
    backend = local_memory.create_backend()
    backend.open(conn, namespace_id="fts:test", session_ref="session:test")
    return backend, conn


def remember(backend, content="中文名字和 Hermes agent", key=None, **extra):
    return backend.execute(
        "remember", {"content": content, "request_id": key or str(uuid4()), **extra}
    )["data"]


def find(backend, *terms, **kwargs):
    return backend.execute("search_terms", {"terms": list(terms), **kwargs})


@pytest.mark.parametrize(
    "terms",
    [[], "中文", [""], [" "], ["x"] * 2, ["x"] * 9, ["x" * 129], [1], ["\x00"], ["\n"]],
)
def test_invalid_terms(terms):
    with pytest.raises(MemoryError, match="invalid_request"):
        validate_request("search_terms", {"terms": terms})


def test_mixed_cjk_and_terms_and_literal_compatibility():
    b, c = opened()
    rid = remember(b)["record_id"]
    remember(b, "中文 only")
    remember(b, "Hermes only")
    for terms in [("中", "Hermes"), ("中文", "agent"), ("中文名字", "Hermes"), ("中文名字和",)]:
        result = find(b, *terms)
        assert [r["record_id"] for r in result["items"]] == [rid]
        assert result["index_stale"] is False
        assert result["short_term_scan"] == any(len(t) < 3 for t in terms)
    assert find(b, "hermes")["items"] == []
    assert b.execute("search", {"query": "中文 Hermes"})["items"] == []
    assert len(b.execute("search", {"query": "中文"})["items"]) == 2
    assert len(b.execute("recall", {"queries": ["中文", "Hermes"]})["items"]) == 3
    c.close()


@pytest.mark.parametrize(
    "term", ['" OR "', "NOT", "NEAR(a)", "a*b", "a:b", "a-b", "x_y", "100%", "😺😺😺"]
)
def test_query_syntax_is_literal(term):
    b, c = opened()
    rid = remember(b, "prefix " + term + " suffix")["record_id"]
    remember(b, "different nonmatching content")
    assert [r["record_id"] for r in find(b, term)["items"]] == [rid]
    c.close()


def test_topic_and_content_terms_can_match_different_fields():
    b, c = opened()
    rid = remember(b, "likes tea", topic="中国项目")["record_id"]
    assert [r["record_id"] for r in find(b, "likes", "中国")["items"]] == [rid]
    c.close()


def test_mutation_replay_forget_and_restart_never_resurrect(tmp_path):
    path = tmp_path / "memory.db"
    b, c = opened(path)
    original = remember(b, "old unique payload", "capture")
    rid = original["record_id"]
    correction = {
        "record_id": rid,
        "expected_revision": 1,
        "content": "new private value",
        "request_id": "edit",
    }
    b.execute("correct", correction)
    assert find(b, "old")["items"] == []
    assert len(find(b, "private")["items"]) == 1
    b.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"})
    assert c.execute("SELECT content,topic FROM memory_fts").fetchall() == []
    assert c.execute("SELECT c0,c1 FROM memory_fts_content").fetchall() == []
    b.close()
    c.close()
    b, c = opened(path)
    assert b.execute("correct", correction)["replayed"] is True
    assert remember(b, "old unique payload", "capture") == original
    assert find(b, "private")["items"] == []
    assert find(b, "old")["items"] == []
    assert c.execute("SELECT count(*) FROM memory_fts").fetchone() == (0,)
    c.close()


@pytest.mark.parametrize("operation", ["remember", "correct", "forget"])
def test_index_failure_rolls_back_canonical_receipt_event(monkeypatch, operation):
    b, c = opened()
    rid = remember(b)["record_id"]
    original = list(c.iterdump())
    update = memory_fts.update_index

    def fail(conn, record_id):
        update(conn, record_id)
        raise sqlite3.OperationalError("synthetic index publication failure")

    monkeypatch.setattr(memory_fts, "update_index", fail)
    request = {"request_id": "failure"}
    if operation == "remember":
        request["content"] = "new material"
    else:
        request.update(record_id=rid, expected_revision=1)
        if operation == "correct":
            request["content"] = "new material"
    with pytest.raises(MemoryError, match="storage_error"):
        b.execute(operation, request)
    assert not c.in_transaction
    assert list(c.iterdump()) == original
    assert find(b, "Hermes")["items"][0]["revision"] == 1
    c.close()


def v6(conn):
    for sql in local_memory._SCHEMA_V6.values():
        conn.execute(sql)
    conn.execute("INSERT INTO namespace VALUES ('fts:test')")
    conn.execute(f"PRAGMA application_id={local_memory._APPLICATION_ID}")
    conn.execute("PRAGMA user_version=6")
    rid = str(uuid4())
    conn.execute(
        "INSERT INTO records(record_id,revision,status,content,topic,source,"
        "session_ref,created_at,updated_at) "
        "VALUES (?,1,'active','legacy 中文','topic','explicit_local_operator','old','old','old')",
        (rid,),
    )
    conn.commit()
    return rid


def test_v6_migration_atomic_and_readonly_never_migrates(tmp_path, monkeypatch):
    path = tmp_path / "memory.db"
    c = sqlite3.connect(path)
    rid = v6(c)
    original = list(c.iterdump())
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        local_memory.create_backend().open_readonly(c, namespace_id="fts:test", session_ref="s")
    assert list(c.iterdump()) == original
    c.execute("PRAGMA query_only=OFF")
    create = memory_fts.create_index

    def fail(conn):
        create(conn)
        raise sqlite3.OperationalError("synthetic fill failure")

    monkeypatch.setattr(memory_fts, "create_index", fail)
    with pytest.raises(MemoryError, match="storage_error"):
        local_memory.create_backend().open(c, namespace_id="fts:test", session_ref="s")
    assert list(c.iterdump()) == original
    monkeypatch.setattr(memory_fts, "create_index", create)
    b = local_memory.create_backend()
    b.open(c, namespace_id="fts:test", session_ref="s")
    assert find(b, "legacy", "中文")["items"][0]["record_id"] == rid
    assert c.execute("PRAGMA user_version").fetchone() == (12,)
    c.close()


def test_readonly_search_does_not_modify_database_and_scope_refused(tmp_path):
    path = tmp_path / "memory.db"
    b, c = opened(path)
    remember(b)
    b.close()
    c.close()
    before = path.read_bytes()
    c = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    b = local_memory.create_backend()
    with pytest.raises(MemoryError, match="namespace_mismatch"):
        b.open_readonly(c, namespace_id="another", session_ref="s")
    b.open_readonly(c, namespace_id="fts:test", session_ref="s")
    assert (
        len(MemoryService(b).execute("search_terms", {"terms": ["Hermes"]})["data"]["items"]) == 1
    )
    c.close()
    assert path.read_bytes() == before


def test_expiry_and_pagination():
    b, c = opened()
    for i in range(5):
        remember(b, "shared title", str(i))
    expired = remember(b, "shared title", "expired", expires_at="2000-01-01T00:00:00Z")
    first = find(b, "shared", limit=2)
    second = find(b, "shared", limit=2, after=first["next_cursor"])
    third = find(b, "shared", limit=2, after=second["next_cursor"])
    ids = [r["record_id"] for page in (first, second, third) for r in page["items"]]
    assert len(set(ids)) == 5
    assert third["has_more"] is False
    assert len(find(b, "shared", include_expired=True)["items"]) == 6
    assert expired["record_id"] not in ids
    c.close()


def test_secure_delete_config_cannot_be_disabled():
    b, c = opened()
    c.execute("INSERT INTO memory_fts(memory_fts,rank) VALUES ('secure-delete',0)")
    c.commit()
    with pytest.raises(MemoryError, match="unsafe_fts_configuration"):
        remember(b)
    with pytest.raises(MemoryError, match="unsafe_fts_configuration"):
        find(b, "abc")
    assert c.execute("SELECT count(*) FROM records").fetchone() == (0,)
    c.close()


def test_candidate_acceptance_index_and_canonical_share_transaction(monkeypatch):
    b, c = opened()
    b._source_kind = "activated_session_model"
    candidate = b.execute(
        "candidate_propose",
        {
            "request_id": "proposal",
            "content": "偏好中国茶",
            "topic": "",
            "quote": "中国茶",
            "quote_start": 0,
            "source_digest": "a" * 64,
            "source_turn": "b" * 64,
        },
    )["data"]
    b._source_kind = "explicit_local_operator"
    request = {
        "candidate_id": candidate["candidate_id"],
        "expected_revision": 1,
        "expires_at": None,
    }
    assert find(b, "中国茶")["items"] == []
    update = memory_fts.update_index

    def fail(conn, rid):
        update(conn, rid)
        raise sqlite3.OperationalError("index failure")

    monkeypatch.setattr(memory_fts, "update_index", fail)
    with pytest.raises(MemoryError, match="storage_error"):
        b.execute("candidate_accept", request)
    assert c.execute("SELECT count(*) FROM records").fetchone() == (0,)
    assert c.execute("SELECT count(*) FROM memory_fts").fetchone() == (0,)
    assert (
        b.execute("candidate_get", {"candidate_id": candidate["candidate_id"]})["data"]["state"]
        == "pending"
    )
    monkeypatch.setattr(memory_fts, "update_index", update)
    accepted = b.execute("candidate_accept", request)
    rid = accepted["data"]["record"]["record_id"]
    assert find(b, "中国茶")["items"][0]["record_id"] == rid
    b.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    assert b.execute("candidate_accept", request)["replayed"] is True
    assert find(b, "中国茶")["items"] == []
    c.close()


def test_descriptor_requires_explicit_fts_capability():
    b, c = opened()

    class LiteralOnly:
        def describe(self):
            value = b.describe()
            value["capabilities"].remove("multi_term_fts")
            return value

        def execute(self, operation, payload):
            raise AssertionError("unsupported capability must not reach adapter")

        def close(self):
            pass

    with pytest.raises(MemoryError, match="capability_unavailable"):
        MemoryService(LiteralOnly()).execute("search_terms", {"terms": ["abc"]})
    c.close()


def test_concurrent_read_snapshot_then_forget_fresh_read_is_empty(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    path = tmp_path / "race.db"
    writer, wc = opened(path)
    rid = remember(writer, "private snapshot payload")["record_id"]
    wc.close()
    rc = sqlite3.connect(path, timeout=5, check_same_thread=False)
    wc = sqlite3.connect(path, timeout=5, check_same_thread=False)
    reader, writer = local_memory.create_backend(), local_memory.create_backend()
    reader.open_readonly(rc, namespace_id="fts:test", session_ref="r")
    writer.open(wc, namespace_id="fts:test", session_ref="w")
    read_admitted, index_updated = Event(), Event()
    update = memory_fts.update_index

    def trace(sql):
        if sql.startswith("SELECT record_id,revision,status,content"):
            read_admitted.set()
            assert index_updated.wait(5)

    def updating(conn, record_id):
        update(conn, record_id)
        index_updated.set()

    rc.set_trace_callback(trace)
    monkeypatch.setattr(memory_fts, "update_index", updating)
    with ThreadPoolExecutor(2) as pool:
        older = pool.submit(find, reader, "private")
        assert read_admitted.wait(5)
        deletion = pool.submit(
            writer.execute,
            "forget",
            {
                "record_id": rid,
                "expected_revision": 1,
                "request_id": "forget-race",
            },
        )
        assert older.result(timeout=10)["items"][0]["record_id"] == rid
        assert deletion.result(timeout=10)["data"]["status"] == "forgotten"
    rc.set_trace_callback(None)
    assert find(reader, "private")["items"] == []
    assert wc.execute("SELECT count(*) FROM memory_fts").fetchone() == (0,)
    rc.close()
    wc.close()


@pytest.mark.parametrize("failure", ["no such module: fts5", "SQL logic error"])
def test_unsupported_fts_runtime_rolls_back_new_store(failure):
    class Unsupported(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == memory_fts.CREATE_SQL:
                raise sqlite3.OperationalError(failure)
            return super().execute(sql, *args)

    conn = sqlite3.connect(":memory:", factory=Unsupported)
    with pytest.raises(MemoryError, match="fts_unavailable"):
        local_memory.create_backend().open(conn, namespace_id="n", session_ref="s")
    assert not conn.in_transaction
    assert conn.execute("PRAGMA application_id").fetchone() == (0,)
    assert conn.execute("PRAGMA user_version").fetchone() == (0,)
    assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
    conn.close()


def test_process_exit_after_index_change_recovers_both_stores(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "crash.db"
    b, c = opened(path)
    rid = remember(b, "original recoverable memory")["record_id"]
    c.close()
    code = """
import os, sqlite3, sys
from personal_agent import local_memory, memory_fts
c = sqlite3.connect(sys.argv[1])
b = local_memory.create_backend()
b.open(c, namespace_id="fts:test", session_ref="crash")
update = memory_fts.update_index
def crash(conn, rid):
    update(conn, rid)
    os._exit(73)
memory_fts.update_index = crash
b.execute("correct", {"record_id":sys.argv[2], "expected_revision":1,
    "request_id":"crashing-edit", "content":"uncommitted replacement"})
"""
    result = subprocess.run([sys.executable, "-c", code, str(path), rid], timeout=15, check=False)
    assert result.returncode == 73
    b, c = opened(path)
    assert find(b, "original")["items"][0]["revision"] == 1
    assert find(b, "replacement")["items"] == []
    assert c.execute(
        "SELECT count(*) FROM receipts WHERE request_id='crashing-edit'"
    ).fetchone() == (0,)
    assert c.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    c.close()
