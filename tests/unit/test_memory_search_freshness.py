"""Current-query read-only FTS coverage, not global forensic index certification."""

import sqlite3

import pytest
from test_memory_fts import find, opened, remember

from personal_agent import memory_fts
from personal_agent.memory_backend import MemoryError


@pytest.mark.parametrize("damage", ["missing", "extra", "mismatch", "postings"])
def test_stale_index_refuses_complete_query_before_pagination(damage):
    backend, conn = opened()
    remember(backend, "searchable oldest")
    remember(backend, "searchable newest")
    if damage in {"missing", "postings"}:
        row = conn.execute("SELECT id,c0,c1 FROM memory_fts_content WHERE id=1").fetchone()
        conn.execute("DELETE FROM memory_fts WHERE rowid=1")
        if damage == "postings":
            conn.execute("INSERT INTO memory_fts_content VALUES (?,?,?)", row)
            assert conn.execute("SELECT count(*) FROM memory_fts_content").fetchone() == (2,)
    elif damage == "extra":
        conn.execute("INSERT INTO memory_fts(rowid,content,topic) VALUES (999,'extra','')")
    else:
        conn.execute("UPDATE memory_fts_content SET c0='mismatch' WHERE id=1")
    conn.commit()
    before = list(conn.iterdump())
    with pytest.raises(MemoryError, match="index_stale"):
        find(backend, "searchable", limit=1)
    assert list(conn.iterdump()) == before
    assert len(backend.execute("search", {"query": "searchable"})["items"]) == 2
    assert len(backend.execute("recall", {"queries": ["searchable"]})["items"]) == 2


def test_short_terms_check_documents_and_expired_active_rows():
    backend, conn = opened()
    remember(backend, "中文短词", expires_at="2000-01-01T00:00:00Z")
    active = remember(backend, "中文当前")
    assert len(find(backend, "中")["items"]) == 1
    assert len(find(backend, "中", include_expired=True)["items"]) == 2
    conn.execute("DELETE FROM memory_fts WHERE rowid=1")
    conn.commit()
    with pytest.raises(MemoryError, match="index_stale"):
        find(backend, "中", after=active["record_id"])


def test_readonly_healthy_query_and_pages_leave_bytes_unchanged(tmp_path):
    path = tmp_path / "records.sqlite3"
    backend, conn = opened(path)
    for key in ("a", "b", "c"):
        remember(backend, "searchable 中文 " + key)
    backend.close()
    conn.close()
    before = path.read_bytes()
    from personal_agent.local_memory import create_backend

    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    backend = create_backend()
    backend.open_readonly(conn, namespace_id="fts:test", session_ref="read")
    try:
        page = find(backend, "searchable", limit=1)
        assert page["index_stale"] is False
        assert page["index_check_scope"] == "logical_documents_and_complete_current_query_coverage"
        assert len(find(backend, "searchable", after=page["next_cursor"])["items"]) == 2
    finally:
        conn.close()
    assert path.read_bytes() == before


def test_check_and_payload_share_one_read_transaction(monkeypatch):
    backend, conn = opened()
    remember(backend)
    real = memory_fts.verify_query

    def verify(connection, *args, **kwargs):
        assert connection is conn and connection.in_transaction
        return real(connection, *args, **kwargs)

    monkeypatch.setattr(memory_fts, "verify_query", verify)
    assert find(backend, "Hermes")["items"]
