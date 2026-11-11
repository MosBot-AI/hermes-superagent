"""Synthetic read contracts: fail closed, bounded and metadata-only."""

import copy
import hashlib
import json
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace

import pytest

from personal_agent.checkpoint_evidence import prepare_checkpoint_evidence
from personal_agent.memory_backend import MemoryError
from personal_agent.native_source_resolution import (
    NativeSourceBinding,
    resolve_checkpoint_sources,
)


def row(n=1, **kw):
    return dict(
        id=n,
        session_id="session",
        active=1,
        compacted=0,
        role="user",
        content=f"private source {n}",
        message_uid=f"{n:032x}",
        absorbed_message_uids=None,
        **kw,
    )


def prepared(rows):
    return prepare_checkpoint_evidence(
        [
            {**r, "_absorbed_message_uids": json.loads(r.get("absorbed_message_uids") or "[]")}
            for r in rows
        ]
    )


class Store:
    read_only = True

    def __init__(self, rows):
        self.rows = rows
        self.revision = (("session",), len(rows), rows[-1]["id"] if rows else 0, 0)
        self.valid = True
        self.calls = []

    @contextmanager
    def transcript_read_snapshot(self):
        def check():
            self.calls.append("check")
            return self.valid

        check.pinned = False
        yield check

    def conversation_revision(self, session_id, **kwargs):
        self.calls.append(("revision", session_id, kwargs))
        return self.revision

    def get_messages(self, session_id, **kwargs):
        self.calls.append(("read", session_id, kwargs))
        return copy.deepcopy(self.rows[: kwargs["limit"]])


def resolve(db, evidence=None, **kwargs):
    return resolve_checkpoint_sources(
        evidence or prepared(db.rows), binding=NativeSourceBinding(db, "session"), **kwargs
    )


def test_exact_private_immutable_result_and_explicit_read_scope():
    db = Store([row()])
    result = resolve(db)
    assert result.references[0].message_uids == (f"{1:032x}",)
    assert result.references[0].row_ids == (1,)
    assert "private" not in repr(result)
    assert "session" not in repr(NativeSourceBinding(db, "session"))
    assert "private" not in repr(result.references[0])
    assert not hasattr(result.references[0], "content")
    assert resolve(db, expected_revision=result.observed_revision) == result
    with pytest.raises(FrozenInstanceError):
        result.references = ()
    diagnostic = json.dumps(result.diagnostic())
    for private in ("private source", f"{1:032x}", hashlib.sha256(b"private source 1").hexdigest()):
        assert private not in diagnostic
    assert result.diagnostic()["durable_checkpoint"] is False
    assert db.calls[1] == (
        "read",
        "session",
        dict(
            include_inactive=False,
            include_compacted=False,
            limit=257,
            offset=0,
            latest=False,
            include_ancestors=False,
        ),
    )
    assert db.calls[2] == "check"


@pytest.mark.parametrize(
    "change",
    [
        {"total_content_chars": True},
        {"total_content_chars": 0},
        {"source_identity_count": 2},
        {"messages": []},
        {"messages": ()},
    ],
)
def test_untrusted_prepared_counts_and_tuples(change):
    db = Store([row()])
    with pytest.raises(MemoryError):
        resolve(db, replace(prepared(db.rows), **change))
    assert db.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"content_sha256": "0" * 64},
        {"content_sha256": None},
        {"absorbed_message_uids": []},
        {"role": "tool"},
        {"content": "\ud800"},
        {"message_uid": "bad"},
        {"content": "x" * 16385},
        {"absorbed_message_uids": ("1" * 32,) * 1024},
    ],
)
def test_untrusted_candidate_fields(change):
    db = Store([row()])
    evidence = prepared(db.rows)
    evidence = replace(evidence, messages=(replace(evidence.messages[0], **change),))
    with pytest.raises(MemoryError):
        resolve(db, evidence)
    assert db.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"content": "rewritten"},
        {"message_uid": "a" * 32},
        {"role": "assistant"},
        {"session_id": "other"},
        {"active": 0},
        {"compacted": 1},
        {"_compressed_summary": True},
        {"tool_calls": [{"id": "tool"}]},
        {"tool_call_id": "tool"},
        {"display_kind": "steer"},
        {"absorbed_message_uids": "not json"},
        {"absorbed_message_uids": []},
        {"absorbed_message_uids": '["bad"]'},
        {"absorbed_message_uids": "[[]]"},
        {"content": "x" * 16385},
        {"id": True},
    ],
)
def test_source_projection_failures(change):
    db = Store([row()])
    evidence = prepared(db.rows)
    db.rows[0].update(change)
    with pytest.raises(MemoryError):
        resolve(db, evidence)


def test_whole_scan_aliases_duplicates_and_gaps_are_not_hidden():
    for rows in (
        [row(), {**row(2), "message_uid": f"{1:032x}"}],
        [row(), {**row(2), "absorbed_message_uids": json.dumps([f"{1:032x}"])}],
    ):
        with pytest.raises(MemoryError, match="identity_ambiguous"):
            resolve(Store(rows), prepared([row()]))
    db = Store([row(n) for n in range(1, 4)])
    for candidates in ([db.rows[0], db.rows[2]], [db.rows[2], db.rows[1]]):
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, prepared(candidates))
    assert resolve(db, prepared([db.rows[1]])).references[0].row_ids == (2,)


def test_single_row_stored_lineage_and_supported_split_merge():
    source = {**row(), "absorbed_message_uids": json.dumps([f"{2:032x}"])}
    assert resolve(Store([source])).source_identity_count == 2
    db = Store([row(), row(2)])
    merged = {
        **row(),
        "content": "private source 1\n\nprivate source 2",
        "absorbed_message_uids": json.dumps([f"{2:032x}"]),
    }
    assert resolve(db, prepared([merged])).references[0].row_ids == (1, 2)
    for content in ("private source 1", merged["content"] + "\n\npending"):
        with pytest.raises(MemoryError, match="mismatch"):
            resolve(db, prepared([{**merged, "content": content}]))
    db.rows[0]["role"] = db.rows[1]["role"] = "assistant"
    with pytest.raises(MemoryError, match="mismatch"):
        resolve(db, prepared([{**merged, "role": "assistant"}]))


def test_exact_bounds_full_scan_sentinel_and_partial_scan():
    rows = [{**row(n), "content": "x" * 256} for n in range(1, 257)]
    db = Store(rows)
    assert resolve(db).scanned_row_count == 256
    db.rows.append(row(257))
    db.revision = (("session",), 257, 257, 0)
    with pytest.raises(MemoryError, match="source_limit"):
        resolve(db, prepared([rows[0]]))
    db = Store([row()])
    db.revision = (("session",), 2, 2, 0)
    with pytest.raises(MemoryError, match="scan_incomplete"):
        resolve(db)
    db = Store([{**row(n), "content": "x" * 16384} for n in range(1, 6)])
    with pytest.raises(MemoryError, match="evidence_limit"):
        resolve(db, prepared([db.rows[0]]))


def test_revision_fence_and_generation_validation():
    db = Store([row()])
    revision = resolve(db).observed_revision
    db.revision = (*revision[:3], 1)
    with pytest.raises(MemoryError, match="revision_changed"):
        resolve(db, expected_revision=revision)
    assert resolve(db).observed_revision == db.revision
    db.valid = False
    with pytest.raises(MemoryError, match="generation_changed"):
        resolve(db)


@pytest.mark.parametrize("revision", [None, [], (("other",), 1, 1, 0), (("session",), True, 1, 0)])
def test_bad_revision_contract(revision):
    db = Store([row()])
    db.revision = revision
    with pytest.raises(MemoryError, match="read_contract_unsupported"):
        resolve(db)


def test_unsupported_read_and_safe_backend_errors():
    db = Store([row()])
    db.read_only = False
    with pytest.raises(MemoryError, match="read_contract_unsupported"):
        resolve(db)
    db.read_only = True

    def fail(*args, **kwargs):
        raise RuntimeError("private text /private/path id secret")

    db.get_messages = fail
    with pytest.raises(MemoryError) as error:
        resolve(db)
    assert "private" not in str(error.value)
    assert error.value.code == "checkpoint_source_read_failed"


@pytest.mark.parametrize("stage", ["enter", "exit", "read", "revision", "check"])
@pytest.mark.parametrize("custom", [False, True])
def test_all_backend_failures_are_redacted(stage, custom):
    db = Store([row()])

    def fail():
        if custom:
            raise MemoryError("private_source_text_/private/path_session_secret")
        raise RuntimeError("private_source_text_/private/path_session_secret")

    @contextmanager
    def snapshot():
        if stage == "enter":
            fail()

        def check():
            if stage == "check":
                fail()
            return True

        check.pinned = False
        yield check
        if stage == "exit":
            fail()

    db.transcript_read_snapshot = snapshot
    if stage == "read":
        db.get_messages = lambda *a, **k: fail()
    if stage == "revision":
        db.conversation_revision = lambda *a, **k: fail()
    with pytest.raises(MemoryError) as error:
        resolve(db)
    assert error.value.code == "checkpoint_source_read_failed"
    assert "private" not in str(error.value)


def test_mixed_session_barriers_and_identity_scan():
    rows = [row(), {**row(2), "role": "tool", "tool_call_id": "call"}, row(3)]
    assert resolve(Store(rows), prepared([rows[2]])).references[0].row_ids == (3,)
    with pytest.raises(MemoryError, match="mismatch"):
        resolve(Store(rows), prepared([rows[0], rows[2]]))
    rows[1]["absorbed_message_uids"] = json.dumps([rows[2]["message_uid"]])
    with pytest.raises(MemoryError, match="identity_ambiguous"):
        resolve(Store(rows), prepared([rows[2]]))


def test_lineage_bounds_complete_and_ordered():
    uids = [f"{n:032x}" for n in range(2, 1025)]
    source = {**row(), "absorbed_message_uids": json.dumps(uids)}
    assert resolve(Store([source])).source_identity_count == 1024
    evidence = prepared([source])
    for changed in (uids[:-1], list(reversed(uids)), uids + [f"{1025:032x}"]):
        db = Store([{**source, "absorbed_message_uids": json.dumps(changed)}])
        with pytest.raises(MemoryError):
            resolve(db, evidence)


@pytest.mark.parametrize(
    "content",
    [
        "[CONTEXT SUMMARY]: prior summary",
        "[CONTEXT COMPACTION — REFERENCE ONLY] prior summary",
        "quote [END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW] conservative refusal",
    ],
)
def test_summary_text_markers_without_flags_are_not_direct_sources(content):
    db = Store([{**row(), "content": content}])
    with pytest.raises(MemoryError, match="mismatch"):
        resolve(db)
