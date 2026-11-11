"""Real LOCAL command/source reads on the exact pinned host; synthetic data only."""

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import pytest
import test_local_memory_commands as memory_commands
from hermes_state import SessionDB

native = memory_commands.native
host = memory_commands.host
command = memory_commands.command
assert_error = memory_commands.assert_error


def seed(host, rows=(("user", "原始来源"), ("assistant", "助手回复"))):
    path = host.home / "state.db"
    with SessionDB(path) as db:
        db.create_session(host.ref.session_id, source="cli")
        for role, content in rows:
            db.append_message(host.ref.session_id, role, content)
        result = db.get_messages(host.ref.session_id)
    return path, result


def data(host, text):
    result = command(host, text)
    assert result["status"] == "ok", result
    return result["data"]


def revision(path, sid):
    with SessionDB(path, read_only=True) as db:
        return db.conversation_revision(sid)


def test_actual_list_show_never_appends_commands_or_creates_memory(host):
    content = "中文\nsecond line\t\x1b[31mnot executable"
    path, rows = seed(host, (("user", content), ("assistant", "assistant evidence")))
    before = revision(path, host.ref.session_id)
    listing = data(host, "source-list")
    assert listing["scope"] == "active_current_session_original_rows"
    assert listing["read_consistency"] in {"pinned", "generation_validated"}
    assert listing["eligible_count"] == listing["scanned_row_count"] == 2
    assert listing["excluded_count"] == 0
    assert listing["next_after"] is None
    assert not any(
        listing[k] for k in ("durable_checkpoint", "source_receipt", "automatic_ingestion")
    )
    assert "content" not in listing["items"][0]
    for row, item in zip(rows, listing["items"], strict=True):
        assert item["message_uid"] == row["message_uid"]
        assert item["role"] == row["role"]
        assert item["content_chars"] == len(row["content"])
        assert item["content_bytes"] == len(row["content"].encode())
        assert item["content_sha256"] == hashlib.sha256(row["content"].encode()).hexdigest()
        shown = data(
            host, f"source-show {item['message_uid']} --expected-snapshot {listing['snapshot']}"
        )
        assert shown["item"]["content"] == row["content"]
        assert shown["item"]["role"] == row["role"]
        assert shown["item"]["absorbed_message_uids"] == []
    assert revision(path, host.ref.session_id) == before
    assert not (host.home / "plugin-data").exists()


def test_pagination_reuses_exact_snapshot_and_mutation_refuses_old_selection(host):
    path, rows = seed(host, tuple(("user", f"source {i}") for i in range(4)))
    first = data(host, "source-list --limit 2")
    assert first["next_after"] == rows[1]["message_uid"]
    second = data(
        host,
        f"source-list --limit 2 --after {first['next_after']} "
        f"--expected-snapshot {first['snapshot']}",
    )
    assert second["snapshot"] == first["snapshot"]
    assert [x["message_uid"] for x in second["items"]] == [x["message_uid"] for x in rows[2:]]
    assert second["next_after"] is None
    with SessionDB(path) as writer:
        writer.append_message(host.ref.session_id, "user", "new unrelated source")
    assert_error(
        command(
            host, f"source-show {rows[0]['message_uid']} --expected-snapshot {first['snapshot']}"
        ),
        "source_snapshot_changed",
    )
    assert_error(
        command(host, f"source-list --expected-snapshot {first['snapshot']}"),
        "source_snapshot_changed",
    )


def test_current_session_only_and_ineligible_rows_are_not_sources(host):
    path, rows = seed(host)
    with SessionDB(path) as db:
        db.create_session("ancestor", source="cli")
        db.append_message("ancestor", "user", "private ancestor")
        db.append_message(host.ref.session_id, "assistant", "[CONTEXT SUMMARY]: old text")
        db.append_message(host.ref.session_id, "tool", "tool evidence", tool_name="synthetic")
        db.append_message(
            host.ref.session_id, "assistant", "display evidence", display_kind="notice"
        )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE sessions SET parent_session_id=? WHERE id=?", ("ancestor", host.ref.session_id)
        )
    listing = data(host, "source-list")
    assert [x["message_uid"] for x in listing["items"]] == [x["message_uid"] for x in rows]
    assert listing["scanned_row_count"] == 5
    assert listing["excluded_count"] == 3
    assert "ancestor" not in str(listing)


def test_missing_store_does_not_create_source_or_canonical_storage(host):
    path = host.home / "state.db"
    assert not path.exists()
    assert_error(command(host, "source-list"), "source_storage_unavailable")
    assert not path.exists()
    assert not (host.home / "plugin-data").exists()


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "journal"])
def test_unsafe_source_path_is_refused(host, unsafe):
    path, _ = seed(host)
    if unsafe == "symlink":
        moved = path.with_suffix(".original")
        path.rename(moved)
        path.symlink_to(moved)
    elif unsafe == "hardlink":
        os.link(path, path.with_suffix(".copy"))
    else:
        path.with_name("state.db-journal").write_bytes(b"synthetic journal")
    assert_error(command(host, "source-list"), "source_unsafe_path")
    assert not (host.home / "plugin-data").exists()


@pytest.mark.parametrize("journal_mode", ["WAL", "DELETE"])
def test_native_read_modes_preserve_database(host, journal_mode):
    path, _ = seed(host)
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()[0].upper()
            == journal_mode
        )
    before = path.read_bytes()
    listing = data(host, "source-list")
    data(
        host,
        f"source-show {listing['items'][0]['message_uid']} "
        f"--expected-snapshot {listing['snapshot']}",
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure", ["no_control", "wrong_profile", "draining"])
def test_host_admission_refuses_before_any_source_read(host, failure):
    from hermes_state_runtime import RuntimeStoreError

    if failure == "no_control":
        host.connection.actor = replace(
            host.connection.actor, capabilities=frozenset({"session:read"})
        )
    elif failure == "wrong_profile":
        host.connection.actor = replace(host.connection.actor, profile_id=str(host.home / "other"))
    else:
        host.runner._draining = True
    with pytest.raises(RuntimeStoreError):
        command(host, "source-list")
    assert not (host.home / "state.db").exists()
    assert not (host.home / "plugin-data").exists()


def test_retained_callback_configuration_and_unload_fences(host):
    callback = memory_commands.handler(host)
    memory_commands.configure(host.home, local_memory=False)
    assert_error(
        memory_commands.retained_command(host, callback, "source-list"), "local_memory_disabled"
    )
    memory_commands.configure(host.home)
    host.manager.unload()
    assert_error(
        memory_commands.retained_command(host, callback, "source-list"), "local_memory_unloaded"
    )
    assert not (host.home / "state.db").exists()


def test_real_writer_during_read_refuses_generation_change(host, monkeypatch):
    path, _ = seed(host)
    original = SessionDB.transcript_read_snapshot

    @contextmanager
    def racing_snapshot(self):
        with original(self) as consistent:

            def check():
                with SessionDB(path) as writer:
                    writer.append_message(host.ref.session_id, "user", "concurrent writer")
                return consistent()

            check.pinned = consistent.pinned
            yield check

    monkeypatch.setattr(SessionDB, "transcript_read_snapshot", racing_snapshot)
    assert_error(command(host, "source-list"), "source_generation_changed")
    assert not (host.home / "plugin-data").exists()


def test_private_journal_and_legacy_schema_are_not_repaired(host):
    path, _ = seed(host)
    journal = path.with_name("state.db-journal")
    journal.write_bytes(b"synthetic journal")
    journal.chmod(0o600)
    assert_error(command(host, "source-list"), "source_storage_unavailable")
    journal.unlink()
    path.unlink()
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
    path.chmod(0o600)
    before = path.read_bytes()
    result = command(host, "source-list")
    assert result["status"] == "error"
    assert result["error"]["code"] in {"source_read_failed", "checkpoint_read_contract_unsupported"}
    assert path.read_bytes() == before
    assert not (host.home / "plugin-data").exists()


def test_inactive_compacted_and_other_session_rows_are_not_selectable(host):
    path, rows = seed(host, (("user", "visible"), ("user", "inactive"), ("user", "compacted")))
    with SessionDB(path) as db:
        db.create_session("other-session", source="cli")
        db.append_message("other-session", "user", "foreign")
        foreign = db.get_messages("other-session")[0]
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE messages SET active=0 WHERE id=?", (rows[1]["id"],))
        conn.execute("UPDATE messages SET active=0, compacted=1 WHERE id=?", (rows[2]["id"],))
    listing = data(host, "source-list")
    assert [item["message_uid"] for item in listing["items"]] == [rows[0]["message_uid"]]
    for row in [*rows[1:], foreign]:
        assert_error(
            command(
                host, f"source-show {row['message_uid']} --expected-snapshot {listing['snapshot']}"
            ),
            "source_not_found",
        )


@pytest.mark.parametrize(
    "count,content,code",
    [
        (257, "small", "checkpoint_source_limit"),
        (1, "x" * 16385, "checkpoint_evidence_limit"),
        (5, "x" * 14000, "checkpoint_evidence_limit"),
    ],
)
def test_complete_scan_limits_fail_without_partial_results(host, count, content, code):
    seed(host, tuple(("user", content) for _ in range(count)))
    assert_error(command(host, "source-list --limit 1"), code)
    assert not (host.home / "plugin-data").exists()
