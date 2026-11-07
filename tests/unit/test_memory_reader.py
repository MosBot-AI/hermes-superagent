"""Read-only native recall must not create, upgrade or repair local storage."""

import os
import sqlite3

import pytest
from test_memory_commands import private_store as private_store
from test_memory_progress import error

from personal_agent import memory_storage


def files(home):
    return {
        str(path.relative_to(home)): path.read_bytes() for path in home.rglob("*") if path.is_file()
    }


def test_missing_reader_store_does_not_create_any_file(private_store):
    home, _ = private_store

    def read():
        with memory_storage.open_existing_memory_reader(home, "session"):
            raise AssertionError("Must not open a missing store")

    error("memory_store_missing", read)
    assert list(home.iterdir()) == []


def test_reader_is_read_only_and_sees_fresh_commits(private_store):
    home, path = private_store
    with memory_storage.open_memory_backend(home, "operator") as writer:
        rid = writer.execute("remember", {"content": "早餐豆浆", "request_id": "r"})["data"][
            "record_id"
        ]
    before = files(home)
    with memory_storage.open_existing_memory_reader(home, "native") as reader:
        assert reader.execute("recall", {"queries": ["早餐"]})["items"][0]["record_id"] == rid
        error(
            "read_only_backend",
            lambda: reader.execute(
                "forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"}
            ),
        )
    assert files(home) == before
    with memory_storage.open_memory_backend(home, "operator") as writer:
        writer.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"})
    after = files(home)
    with memory_storage.open_existing_memory_reader(home, "native") as reader:
        assert reader.execute("recall", {"queries": ["早餐"]})["items"] == []
    assert files(home) == after
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "kind", ["symlink", "hardlink", "world_read", "journal", "wal", "shm", "wal_header", "legacy"]
)
def test_reader_refuses_unsafe_or_unready_store_without_repair(private_store, tmp_path, kind):
    home, path = private_store
    with memory_storage.open_memory_backend(home, "operator"):
        pass
    if kind == "symlink":
        original = path.read_bytes()
        path.unlink()
        target = tmp_path / "target.db"
        target.write_bytes(original)
        target.chmod(0o600)
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(path, tmp_path / "hardlink.db")
    elif kind == "world_read":
        path.chmod(0o644)
    elif kind in {"journal", "wal", "shm"}:
        path.with_name(path.name + "-" + kind).write_bytes(b"synthetic")
    elif kind == "wal_header":
        raw = bytearray(path.read_bytes())
        raw[18:20] = b"\x02\x02"
        path.write_bytes(raw)
    else:
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TABLE record_checkpoints")
            conn.execute("PRAGMA user_version=3")
    before = files(home)

    def read():
        with memory_storage.open_existing_memory_reader(home, "native"):
            raise AssertionError("Must reject")

    with pytest.raises(memory_storage.MemoryError):
        read()
    assert files(home) == before


def test_external_wal_transition_race_is_refused_before_record_reads(private_store, monkeypatch):
    home, path = private_store
    with memory_storage.open_memory_backend(home, "operator") as writer:
        writer.execute("remember", {"content": "private", "request_id": "r"})
    connect = sqlite3.connect
    changed = []

    def switch_before_open(*args, **kwargs):
        if not changed:
            changed.append(True)
            concurrent = connect(path)
            concurrent.execute("PRAGMA journal_mode=WAL")
            concurrent.close()
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", switch_before_open)

    def read():
        with memory_storage.open_existing_memory_reader(home, "native"):
            raise AssertionError("Must not admit raced WAL state")

    error("memory_reader_format_unsupported", read)
    # mode=ro is canonical-read-only, not a VFS guarantee: SQLite may have
    # created sidecars before journal-mode refusal. Never delete/repair them.
    with connect(path) as verify:
        assert verify.execute("SELECT content FROM records").fetchall() == [("private",)]


def test_reader_rechecks_journal_mode_in_each_operation_snapshot(private_store):
    home, path = private_store
    with memory_storage.open_memory_backend(home, "operator") as writer:
        writer.execute("remember", {"content": "private", "request_id": "r"})
    with memory_storage.open_existing_memory_reader(home, "native") as reader:
        concurrent = sqlite3.connect(path)
        assert concurrent.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        concurrent.close()
        error(
            "memory_reader_format_unsupported",
            lambda: reader.execute("recall", {"queries": ["private"]}),
        )
