"""Exact-pin, synthetic SessionDB reconciliation, never provider/model writes."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
import test_native_plugin
from agent.conversation_compression import _direct_messages_for_pre_compress_memory
from agent.message_metadata import record_absorbed_message
from hermes_state import SessionDB

from personal_agent.checkpoint_evidence import prepare_checkpoint_evidence
from personal_agent.memory_backend import MemoryError
from personal_agent.native_memory_provider import PersonalRecordsProvider
from personal_agent.native_source_resolution import NativeSourceBinding, resolve_checkpoint_sources

home = test_native_plugin.home


def resolve(db, evidence, session="session", **kwargs):
    return resolve_checkpoint_sources(evidence, binding=NativeSourceBinding(db, session), **kwargs)


def capture(db, session="session"):
    return prepare_checkpoint_evidence(db.get_messages_as_conversation(session))


def create(path, rows=(("user", "first source"),)):
    with SessionDB(path) as db:
        db.create_session("session", source="cli")
        for role, content in rows:
            db.append_message("session", role, content)
        return capture(db)


def test_real_durable_reopen_exact_scope_metadata_and_unchanged_storage(home, tmp_path):
    path = tmp_path / "source.db"
    evidence = create(path, (("user", "synthetic breakfast"), ("assistant", "reply")))
    before = path.read_bytes()
    with SessionDB(path, read_only=True) as db:
        result = resolve(db, evidence)
        assert result.observed_revision == db.conversation_revision("session")
        assert result.snapshot_pinned is False
        assert result.diagnostic()["source_verification"] == "exact_observed_match"
        with pytest.raises(MemoryError):
            resolve(db, evidence, "other")
        raw = db.get_messages_as_conversation("session")
        raw[0].update(
            session_id="other",
            author_id="owner",
            grant="all",
            api_content="not canonical",
            display_metadata={"text": "private"},
        )
        assert resolve(db, prepare_checkpoint_evidence(raw)) == result
    assert path.read_bytes() == before
    assert not (home / "plugin-data").exists()
    assert PersonalRecordsProvider.pre_compress_checkpoint_api_version == 1


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_real_resume_split_merge_and_unpersisted_pending_text(home, tmp_path, role):
    path = tmp_path / "source.db"
    create(path, ((role, "first source"), (role, "second source")))
    with SessionDB(path, read_only=True) as db:
        resumed, _ = db.get_resume_conversations("session")
        evidence = prepare_checkpoint_evidence(_direct_messages_for_pre_compress_memory(resumed))
        if role == "assistant":
            with pytest.raises(MemoryError, match="mismatch"):
                resolve(db, evidence)
            return
        assert resumed[0]["content"] == "first source\n\nsecond source"
        assert resolve(db, evidence).references[0].row_ids == tuple(
            row["id"] for row in db.get_messages("session")
        )
        pending = {"role": "user", "content": "pending unpersisted tail"}
        merged = copy.deepcopy(resumed[0])
        record_absorbed_message(merged, pending)
        merged["content"] += "\n\n" + pending["content"]
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, prepare_checkpoint_evidence([merged]))


def test_real_existing_uid_with_pending_tail_and_equal_text_other_identity(home, tmp_path):
    path = tmp_path / "source.db"
    evidence = create(path)
    with SessionDB(path) as writer:
        writer.create_session("other", source="cli")
        writer.append_message("other", "user", "first source")
        other = capture(writer, "other")
    with SessionDB(path, read_only=True) as db:
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, other)
        raw = db.get_messages_as_conversation("session")
        raw[0]["content"] += "\n\nunpersisted"
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, prepare_checkpoint_evidence(raw))
        assert resolve(db, evidence)


@pytest.mark.parametrize("mutation", ["rewrite", "rewind", "compact"])
def test_real_rewrite_rewind_compaction_reject_original_and_stale_revision(
    home, tmp_path, mutation
):
    path = tmp_path / "source.db"
    evidence = create(path)
    with SessionDB(path, read_only=True) as db:
        old_revision = resolve(db, evidence).observed_revision
    with SessionDB(path) as writer:
        mid = writer.get_messages("session")[0]["id"]
        if mutation == "rewrite":
            writer.set_user_message_content("session", mid, "rewritten")
        elif mutation == "rewind":
            writer.rewind_to_message("session", mid)
        else:
            writer.archive_and_compact(
                "session",
                [{"role": "assistant", "content": "summary", "_compressed_summary": True}],
            )
    with SessionDB(path, read_only=True) as db:
        with pytest.raises(MemoryError, match="revision_changed"):
            resolve(db, evidence, expected_revision=old_revision)
        with pytest.raises(MemoryError):
            resolve(db, evidence)


def test_real_revision_changes_even_after_same_uid_text_restoration(home, tmp_path):
    path = tmp_path / "source.db"
    evidence = create(path)
    with SessionDB(path, read_only=True) as db:
        revision = resolve(db, evidence).observed_revision
    with SessionDB(path) as writer:
        mid = writer.get_messages("session")[0]["id"]
        writer.set_user_message_content("session", mid, "temporary rewrite")
        writer.set_user_message_content("session", mid, "first source")
    with SessionDB(path, read_only=True) as db:
        assert resolve(db, evidence).observed_revision != revision
        with pytest.raises(MemoryError, match="revision_changed"):
            resolve(db, evidence, expected_revision=revision)


def test_real_summary_tool_barriers_and_unrelated_direct_subset(home, tmp_path):
    path = tmp_path / "source.db"
    create(path)
    with SessionDB(path) as writer:
        writer.archive_and_compact(
            "session", [{"role": "assistant", "content": "summary", "_compressed_summary": True}]
        )
        writer.append_message("session", "tool", "tool result", tool_call_id="call")
        writer.append_message("session", "user", "new direct source")
        rows = writer.get_messages_as_conversation("session")
        direct = prepare_checkpoint_evidence([rows[-1]])
        summary = {**rows[0]}
        summary.pop("_compressed_summary", None)
        forged = prepare_checkpoint_evidence([summary])
    with SessionDB(path, read_only=True) as db:
        assert resolve(db, direct).scanned_row_count == 3
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, forged)


def test_real_bounded_overflow_and_partial_projection_refused(home, tmp_path, monkeypatch):
    path = tmp_path / "source.db"
    evidence = create(path)
    with SessionDB(path) as writer:
        for n in range(256):
            writer.append_message("session", "user", f"source {n}")
    with SessionDB(path, read_only=True) as db:
        with pytest.raises(MemoryError, match="source_limit"):
            resolve(db, evidence)
        original = db.get_messages
        monkeypatch.setattr(db, "get_messages", lambda *a, **k: original(*a, **k)[:1])
        with pytest.raises(MemoryError, match="scan_incomplete"):
            resolve(db, evidence)


def test_real_readonly_generation_invalidates_on_concurrent_writer(home, tmp_path, monkeypatch):
    path = tmp_path / "source.db"
    evidence = create(path)
    with SessionDB(path, read_only=True) as db:
        original = db.transcript_read_snapshot
        observed = []

        def write():
            with SessionDB(path) as writer:
                writer.append_message("session", "assistant", "concurrent source")

        @contextmanager
        def interleaved():
            with original() as check:
                assert check.pinned is False

                def validate():
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(write).result(timeout=10)
                    valid = check()
                    observed.append(valid)
                    return valid

                validate.pinned = check.pinned
                yield validate

        monkeypatch.setattr(db, "transcript_read_snapshot", interleaved)
        with pytest.raises(MemoryError, match="generation_changed"):
            resolve(db, evidence)
        assert observed == [False]
    with SessionDB(path, read_only=True) as db:
        assert resolve(db, evidence).scanned_row_count == 2


def test_real_raw_lineage_duplicate_alias_not_hidden(home, tmp_path):
    path = tmp_path / "source.db"
    evidence = create(path)
    with SessionDB(path) as writer:
        uid = evidence.messages[0].message_uid
        writer.append_messages_batch(
            "session",
            [{"role": "user", "content": "other source", "_absorbed_message_uids": [uid]}],
        )
    with SessionDB(path, read_only=True) as db:
        with pytest.raises(MemoryError, match="identity_ambiguous"):
            resolve(db, evidence)


def test_real_single_stored_lineage_reopen_and_metadata_exclusion(home, tmp_path):
    path = tmp_path / "source.db"
    with SessionDB(path) as writer:
        writer.create_session("session", source="cli")
        writer.append_messages_batch(
            "session",
            [
                {
                    "role": "user",
                    "content": "persisted merged prose",
                    "message_uid": "1" * 32,
                    "_absorbed_message_uids": ["2" * 32, "3" * 32],
                    "api_content": "injected sidecar",
                    "display_metadata": {"private": "ignored"},
                }
            ],
        )
        evidence = capture(writer)
    before = path.read_bytes()
    with SessionDB(path, read_only=True) as db:
        raw = db.get_messages("session")[0]
        assert isinstance(raw["absorbed_message_uids"], str)
        assert "_absorbed_message_uids" not in raw
        result = resolve(db, evidence)
        assert result.references[0].message_uids == ("1" * 32, "2" * 32, "3" * 32)
        assert len(result.references[0].row_ids) == 1
    assert path.read_bytes() == before


def test_real_public_tool_decode_is_not_raw_corruption_audit(home, tmp_path):
    import sqlite3

    path = tmp_path / "source.db"
    with SessionDB(path) as writer:
        writer.create_session("session", source="cli")
        writer.append_message(
            "session",
            "assistant",
            "tool-bearing prose",
            tool_calls=[
                {"id": "call", "type": "function", "function": {"name": "fake", "arguments": "{}"}}
            ],
        )
        raw = writer.get_messages_as_conversation("session")
        raw[0].pop("tool_calls", None)
        evidence = prepare_checkpoint_evidence(raw)
    # Corrupt only a synthetic fixture to expose the public decoder's boundary.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE messages SET tool_calls = ?", ("malformed JSON",))
    with SessionDB(path, read_only=True) as db:
        projected = db.get_messages("session")[0]
        assert projected["tool_calls"] == []
        assert projected["tool_call_uids"]
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, evidence)


@pytest.mark.parametrize("kind", ["current", "legacy", "merged"])
def test_real_unflagged_native_summary_markers_are_ineligible(home, tmp_path, kind):
    from agent.context_compressor import SUMMARY_PREFIX, is_compaction_summary_message

    content = {
        "current": SUMMARY_PREFIX + "\nsynthetic summary",
        "legacy": "[CONTEXT SUMMARY]: synthetic old summary",
        "merged": "earlier user text\n[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]\n"
        + SUMMARY_PREFIX
        + "\nsynthetic summary",
    }[kind]
    path = tmp_path / "source.db"
    evidence = create(path, (("user", content),))
    with SessionDB(path, read_only=True) as db:
        raw = db.get_messages("session")[0]
        assert not raw.get("_compressed_summary")
        assert is_compaction_summary_message(raw)
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, evidence)


def test_real_reserved_json_prefix_is_exact_only_not_split_merge(home, tmp_path):
    path = tmp_path / "source.db"
    evidence = create(path, (("user", "\x00json:literal text"), ("user", "next source")))
    with SessionDB(path, read_only=True) as db:
        assert resolve(db, evidence).scanned_row_count == 2
        resumed, _ = db.get_resume_conversations("session")
        assert len(resumed) == 2  # Native repair refuses this split shape.
        forged = copy.deepcopy(resumed[0])
        record_absorbed_message(forged, resumed[1])
        forged["content"] += "\n\n" + resumed[1]["content"]
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, prepare_checkpoint_evidence([forged]))
