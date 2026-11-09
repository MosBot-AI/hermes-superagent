"""Fresh fenced diagnosis, canonical-only index rebuild and failure recovery."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from personal_agent import PLUGIN_ID, memory_index, memory_storage
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_edits import PrivateEdits
from personal_agent.memory_projection import PrivateProjection


def opened(home):
    path = home / "plugin-data" / PLUGIN_ID / "memory" / "records.sqlite3"
    c = sqlite3.connect(path, isolation_level=None)
    b = create_backend()
    b.open(
        c,
        namespace_id="trusted-profile:" + hashlib.sha256(str(home).encode()).hexdigest(),
        session_ref="test",
        projection=PrivateProjection(path.parent),
        edits=PrivateEdits(path.parent),
    )
    path.chmod(0o600)
    return MemoryService(b), c, path


@pytest.fixture
def store(tmp_path, monkeypatch):
    home = tmp_path / "home"
    directory = home / "plugin-data" / PLUGIN_ID / "memory"
    directory.mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(memory_storage, "current_profile_home", lambda: home)
    s, c, p = opened(home)
    yield s, c, p, home
    s.backend.close()
    c.close()


def remember(s, key="seed", content="中文 searchable text", **kw):
    return s.execute("remember", {"content": content, "topic": "topic", "request_id": key, **kw})[
        "data"
    ]["record_id"]


def check(home):
    return memory_index.maintain(home, "index_status", {})["data"]


def rebuild(home, watermark):
    return memory_index.maintain(home, "index_rebuild", {"expected_watermark": watermark})


def error(code, call):
    with pytest.raises(MemoryError) as caught:
        call()
    assert caught.value.code == code


def canonical(c):
    return {
        table: c.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("records", "events", "receipts", "memory_projection", "memory_edits")
    }


def test_status_no_change_and_expired_indexed_canonical_rebuild(store):
    s, c, p, home = store
    rid = remember(s, expires_at="2000-01-01T00:00:00Z")
    s.execute("projection_refresh", {})
    s.execute("edit_create", {"record_id": rid, "expected_revision": 1, "request_id": "draft"})
    files = {name: (p.parent / name).read_bytes() for name in ("records.md", "edit.md")}
    before = canonical(c)
    assert check(home)["index_current"]
    assert check(home)["indexed_record_count"] == 1
    first = rebuild(home, 1)
    assert first["data"]["rebuilt"] and not first["replayed"]
    assert rebuild(home, 1)["data"]["index_current"]
    assert canonical(c) == before
    assert all((p.parent / name).read_bytes() == raw for name, raw in files.items())
    assert c.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


@pytest.mark.parametrize(
    "damage,field",
    [
        ("missing", "missing_records"),
        ("extra", "extra_records"),
        ("mismatch", "mismatched_records"),
    ],
)
def test_native_integrity_alone_misses_logical_drift(store, damage, field):
    s, c, _, home = store
    remember(s)
    if damage == "missing":
        c.execute("DELETE FROM memory_fts")
    elif damage == "extra":
        c.execute("INSERT INTO memory_fts(rowid,content,topic) VALUES(999,'stale secret','topic')")
    else:
        c.execute("UPDATE memory_fts SET content='stale secret'")
    before = canonical(c)
    state = check(home)
    assert state["native_integrity"] == "ok" and state[field] == 1 and not state["index_current"]
    assert "secret" not in json.dumps(state)
    assert rebuild(home, 1)["data"]["index_current"]
    assert canonical(c) == before
    assert s.execute("search_terms", {"terms": ["searchable"]})["data"]["items"]


@pytest.mark.parametrize(
    "sql", ["DELETE FROM memory_fts_docsize", "UPDATE memory_fts_data SET block=x'00' WHERE id>10"]
)
def test_real_inverted_corruption_rebuilt_only_from_current_canonical(store, sql):
    s, c, _, home = store
    remember(s)
    c.execute(sql)
    before = canonical(c)
    state = check(home)
    assert state["native_integrity"] == "corrupt" and not state["index_current"]
    result = rebuild(home, 1)["data"]
    assert result["native_integrity"] == "ok" and result["before"]["native_integrity"] == "corrupt"
    assert canonical(c) == before


@pytest.mark.parametrize(
    "sql,code",
    [
        (
            "INSERT INTO memory_fts(memory_fts,rank) VALUES('secure-delete',0)",
            "unsafe_fts_configuration",
        ),
        ("PRAGMA user_version=999", "unsupported_schema"),
        ("UPDATE namespace SET id='foreign'", "namespace_mismatch"),
        ("UPDATE records SET content=CAST(zeroblob(100000) AS TEXT)", "storage_corrupt"),
        ("UPDATE records SET record_id='not-an-id'", "storage_corrupt"),
        ("UPDATE records SET expires_at='bad'", "storage_corrupt"),
        ("DELETE FROM events", "storage_corrupt"),
    ],
)
def test_canonical_or_safety_damage_never_repaired(store, sql, code):
    s, c, _, home = store
    remember(s)
    c.execute(sql)
    before = canonical(c)
    error(code, lambda: check(home))
    error(code, lambda: rebuild(home, 1))
    assert canonical(c) == before


def test_stale_watermark_and_old_payload_never_resurrect(store):
    s, c, _, home = store
    rid = remember(s)
    old = check(home)["current_watermark"]
    s.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    c.execute(
        "INSERT INTO memory_fts(rowid,content,topic) VALUES(1,'forgotten old payload','topic')"
    )
    error("watermark_conflict", lambda: rebuild(home, old))
    assert check(home)["extra_records"] == 1
    assert rebuild(home, 2)["data"]["indexed_record_count"] == 0
    assert s.execute("list", {})["data"]["items"] == []


@pytest.mark.parametrize("mode", ["public", "symlink", "hardlink", "wal", "missing"])
def test_unsafe_missing_files_are_not_created_or_repaired(store, mode):
    _, _, p, home = store
    if mode == "public":
        p.chmod(0o644)
    elif mode == "symlink":
        target = p.with_name("other")
        p.rename(target)
        p.symlink_to(target)
    elif mode == "hardlink":
        p.with_name("copy").hardlink_to(p)
    elif mode == "wal":
        p.with_name(p.name + "-wal").touch(mode=0o600)
    else:
        p.unlink()
    with pytest.raises(MemoryError):
        check(home)
    with pytest.raises(MemoryError):
        rebuild(home, 0)
    if mode == "missing":
        assert not p.exists()


def test_foreign_profile_and_bare_backend_do_not_gain_maintenance(store, monkeypatch):
    s, _, _, home = store
    error("index_maintenance_required", lambda: s.backend.execute("index_status", {}))
    monkeypatch.setattr(memory_storage, "current_profile_home", lambda: home.parent)
    error("profile_context_changed", lambda: check(home))


@pytest.mark.parametrize("value", [True, -1, 2**63, "1", None])
def test_invalid_watermark_before_path_access(value, tmp_path):
    error("invalid_request", lambda: rebuild(tmp_path, value))


def test_first_fts_access_is_fenced_and_status_preserves_bytes(store, monkeypatch):
    s, _, p, home = store
    remember(s)
    real = sqlite3.connect
    queries = []

    class Traced(sqlite3.Connection):
        def execute(self, sql, *args):
            queries.append(sql)
            if "memory_fts" in sql or "sqlite_master" in sql:
                assert self.in_transaction
                assert "BEGIN IMMEDIATE" in queries
            return super().execute(sql, *args)

    monkeypatch.setattr(
        memory_index.sqlite3, "connect", lambda *a, **k: real(*a, factory=Traced, **k)
    )
    before = p.read_bytes()
    assert check(home)["index_current"]
    assert p.read_bytes() == before


def test_fault_after_drop_rolls_back_index_and_all_canonical(store, monkeypatch):
    s, c, _, home = store
    remember(s)
    before = canonical(c)
    real = memory_index.memory_fts.create_index

    def fault(conn):
        real(conn)
        raise MemoryError("synthetic_fault")

    monkeypatch.setattr(memory_index.memory_fts, "create_index", fault)
    error("synthetic_fault", lambda: rebuild(home, 1))
    assert canonical(c) == before and check(home)["index_current"]


def test_unknown_native_integrity_error_not_classified_as_repairable(store, monkeypatch):
    s, _, _, home = store
    remember(s)
    real = sqlite3.connect

    class Fault(sqlite3.Connection):
        def execute(self, sql, *args):
            if "VALUES('integrity-check',1)" in sql:
                raise sqlite3.OperationalError("synthetic unknown failure")
            return super().execute(sql, *args)

    monkeypatch.setattr(
        memory_index.sqlite3, "connect", lambda *a, **k: real(*a, factory=Fault, **k)
    )
    with pytest.raises(MemoryError):
        rebuild(home, 1)


@pytest.mark.parametrize("stage", ["after_drop", "before_commit", "after_commit"])
def test_rebuild_process_crash_then_current_watermark_retry(store, stage):
    s, c, p, home = store
    remember(s)
    c.execute("DELETE FROM memory_fts")
    before = canonical(c)
    child = """
import os,sqlite3,sys
from pathlib import Path
from personal_agent import memory_index,memory_storage
home=Path(sys.argv[1]);stage=sys.argv[2]
memory_storage.current_profile_home=lambda:home
real=sqlite3.connect
class Crash(sqlite3.Connection):
    def execute(self,sql,*args):
        if sql=='COMMIT' and stage=='before_commit':os._exit(73)
        value=super().execute(sql,*args)
        if sql=='DROP TABLE memory_fts' and stage=='after_drop':os._exit(73)
        if sql=='COMMIT' and stage=='after_commit':os._exit(73)
        return value
memory_index.sqlite3.connect=lambda *a,**k:real(*a,factory=Crash,**k)
memory_index.maintain(home,'index_rebuild',{'expected_watermark':1})
"""
    result = subprocess.run([sys.executable, "-c", child, str(home), stage], capture_output=True)
    assert result.returncode == 73, result.stderr
    # Hot rollback journals are validated, then recovered by SQLite, not deleted.
    assert rebuild(home, 1)["data"]["index_current"]
    assert canonical(c) == before
    assert not p.with_name(p.name + "-journal").exists()


def test_writer_fence_serializes_rebuild_and_forget_without_resurrection(store, monkeypatch):
    s, c, _, home = store
    rid = remember(s)
    entered, release, started = Event(), Event(), Event()
    real = memory_index.memory_fts.create_index

    def paused(conn):
        entered.set()
        assert release.wait(5)
        return real(conn)

    monkeypatch.setattr(memory_index.memory_fts, "create_index", paused)

    def forgetting():
        local, conn, _ = opened(home)
        try:
            started.set()
            return local.execute(
                "forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"}
            )
        finally:
            local.backend.close()
            conn.close()

    with ThreadPoolExecutor(2) as pool:
        index_future = pool.submit(rebuild, home, 1)
        assert entered.wait(5)
        forget_future = pool.submit(forgetting)
        # The opener itself acquires the canonical writer fence before mutation.
        assert not forget_future.done()
        release.set()
        assert index_future.result(timeout=10)["data"]["index_current"]
        forget_future.result(timeout=10)
    assert check(home)["indexed_record_count"] == 0
    assert c.execute("SELECT content FROM records").fetchall() == [(None,)]
    error("watermark_conflict", lambda: rebuild(home, 1))


def test_old_reader_config_cache_never_used_for_diagnosis(store):
    s, old, _, home = store
    rid = remember(s)
    assert old.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    local, c, _ = opened(home)
    try:
        local.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "content": "new evidence",
                "request_id": "correct",
            },
        )
    finally:
        local.backend.close()
        c.close()
    # Depending on SQLite version old.integrity_check may now falsely report
    # corruption. The real command must use its own fresh fenced handle.
    assert check(home)["index_current"]
    assert rebuild(home, 2)["data"]["index_current"]


def test_v9_database_is_not_migrated_by_maintenance(store):
    from personal_agent.memory_edits import COLUMNS, SCHEMA_V9

    _, c, _, home = store
    c.execute("ALTER TABLE memory_edits RENAME TO new_edits")
    c.execute(SCHEMA_V9["memory_edits"])
    c.execute(f"INSERT INTO memory_edits SELECT {','.join(COLUMNS[:-2])} FROM new_edits")
    c.execute("DROP TABLE new_edits")
    c.execute("PRAGMA user_version=9")
    error("unsupported_schema", lambda: check(home))
    error("unsupported_schema", lambda: rebuild(home, 0))
    assert c.execute("PRAGMA user_version").fetchone() == (9,)


@pytest.mark.parametrize("operation", ["index_status", "index_rebuild"])
def test_closed_wal_file_refused_without_repair_but_bookkeeping_is_disclosed(
    store, monkeypatch, operation
):
    s, c, path, home = store
    remember(s)
    assert c.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    s.backend.close()
    c.close()
    sidecars = [path.with_name(path.name + suffix) for suffix in ("-wal", "-shm")]
    assert not any(p.exists() for p in sidecars)
    before = path.read_bytes()
    assert before[18:20] == b"\x02\x02"
    observed = set()
    real = sqlite3.connect

    class Observed(sqlite3.Connection):
        def execute(self, sql, *args):
            value = super().execute(sql, *args)
            for sidecar in sidecars:
                if sidecar.exists():
                    assert sidecar.stat().st_mode & 0o777 == 0o600
                    observed.add(sidecar.name)
            return value

    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported WAL must not reach diagnosis or rebuild")

    monkeypatch.setattr(
        memory_index.sqlite3, "connect", lambda *a, **k: real(*a, factory=Observed, **k)
    )
    monkeypatch.setattr(memory_index, "_diagnose", forbidden)
    monkeypatch.setattr(memory_index.memory_fts, "create_index", forbidden)
    request = {} if operation == "index_status" else {"expected_watermark": 1}
    error(
        "memory_reader_format_unsupported",
        lambda: memory_index.maintain(home, operation, request),
    )
    assert observed == {p.name for p in sidecars}
    assert not any(p.exists() for p in sidecars)
    assert path.read_bytes() == before  # Includes unchanged WAL header mode.
