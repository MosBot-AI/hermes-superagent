"""Bounded observation, parser and presentation contracts; no native source I/O."""

import copy
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from test_memory_commands import local as local
from test_native_source_resolution import Store, row

from personal_agent import conversation_memory as commands
from personal_agent import native_source_workbench as review
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_presentation import render_memory_result


class Reader(Store):
    def get_session(self, session_id):
        return {"id": session_id}


LIST = {"limit": 10, "after": None, "expected_snapshot": None}
BINDING = ("/synthetic-profile", 1, 2)


def inspect(db, operation="source_list", payload=None, binding=BINDING):
    return review.inspect_sources(
        db, session_id="session", binding=binding, operation=operation, payload=payload or LIST
    )["data"]


def show(db, snapshot, uid="00000000000000000000000000000001"):
    return inspect(db, "source_show", {"message_uid": uid, "expected_snapshot": snapshot})


def envelope(data):
    return {"status": "ok", "data": data, "replayed": False, "request_id": None}


def test_complete_metadata_list_exact_show_and_repeated_reads():
    rows = [row(), row(2)]
    rows[0]["content"] = "中文\n\t\x1b[31m\u202esecret"
    rows[1]["role"] = "assistant"
    db = Reader(rows)
    listing = inspect(db)
    assert listing == inspect(db)
    assert listing["eligible_count"] == listing["scanned_row_count"] == 2
    assert listing["excluded_count"] == 0
    assert listing["next_after"] is None
    assert "secret" not in json.dumps(listing)
    assert listing["read_consistency"] == "generation_validated"
    for key in ("durable_checkpoint", "source_receipt", "automatic_ingestion"):
        assert listing[key] is False
    for source, meta in zip(rows, listing["items"], strict=True):
        assert meta["role"] == source["role"]
        assert meta["content_chars"] == len(source["content"])
        assert meta["content_bytes"] == len(source["content"].encode())
        assert meta["content_sha256"] == hashlib.sha256(source["content"].encode()).hexdigest()
        result = show(db, listing["snapshot"], meta["message_uid"])
        assert result["item"]["content"] == source["content"]
        text = render_memory_result(envelope(result), operation="source_show", payload={})
        assert source["role"] in text and "not a durable receipt" in text
        assert "generation_validated" in text and "Absorbed UIDs: none" in text
        assert "\x1b" not in text and "\u202e" not in text
        if source is rows[0]:
            assert "中文" in text and r"\u001b" in text and r"\u202e" in text
    assert db.calls[1] == (
        "read",
        "session",
        {
            "include_inactive": False,
            "include_compacted": False,
            "limit": 257,
            "offset": 0,
            "latest": False,
            "include_ancestors": False,
        },
    )


def test_pagination_with_copyable_exact_commands():
    db = Reader([row(n) for n in range(1, 5)])
    first = inspect(db, payload={**LIST, "limit": 2})
    assert first["next_after"] == row(2)["message_uid"]
    text = render_memory_result(envelope(first), operation="source_list", payload={"limit": 2})
    assert "private source" not in text
    for line in text.splitlines():
        if "Inspect: " in line or "Next page: " in line:
            cmd = line.split("/personal-memory ", 1)[1]
            operation, payload = commands.parse_command(cmd)
            result = inspect(db, operation, payload)
            assert result["snapshot"] == first["snapshot"]
    second = inspect(
        db,
        payload={
            **LIST,
            "after": first["next_after"],
            "expected_snapshot": first["snapshot"],
        },
    )
    assert [item["message_uid"] for item in second["items"]] == [
        row(3)["message_uid"],
        row(4)["message_uid"],
    ]
    assert second["next_after"] is None


def test_empty_session_and_no_eligible_rows_are_honest():
    empty = inspect(Reader([]))
    assert empty["scanned_row_count"] == empty["eligible_count"] == 0
    assert empty["items"] == [] and empty["next_after"] is None
    text = render_memory_result(envelope(empty), operation="source_list", payload=LIST)
    assert "No eligible original sources" in text
    rows = [row()]
    rows[0]["role"] = "tool"
    result = inspect(Reader(rows))
    assert result["excluded_count"] == result["scanned_row_count"] == 1
    assert result["items"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "tool"),
        ("content", "[CONTEXT SUMMARY]: prior"),
        ("content", "[CONTEXT COMPACTION — REFERENCE ONLY] prior"),
        ("content", "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW] prior"),
        ("content", ""),
        ("content", None),
        ("_compressed_summary", True),
        ("tool_calls", [{"id": "tool"}]),
        ("tool_call_id", "tool"),
        ("display_kind", "notice"),
        ("tool_name", "synthetic"),
    ],
)
def test_ineligible_rows_are_counted_not_displayed_or_selectable(field, value):
    bad = row(2)
    bad[field] = value
    db = Reader([row(), bad])
    listing = inspect(db)
    assert listing["eligible_count"] == listing["excluded_count"] == 1
    with pytest.raises(MemoryError, match="source_not_found"):
        show(db, listing["snapshot"], bad["message_uid"])


@pytest.mark.parametrize("change", ["revision", "content", "role", "binding", "excluded"])
def test_observation_changes_for_all_supported_scope_and_source_changes(change):
    db = Reader([row(), row(2)])
    db.rows[1]["role"] = "tool"
    snapshot = inspect(db)["snapshot"]
    binding = BINDING
    if change == "revision":
        db.revision = (*db.revision[:3], 1)
    elif change == "binding":
        binding = ("/another-profile", 1, 2)
    elif change == "excluded":
        db.rows[1]["content"] = "changed tool output"
    else:
        db.rows[0][change] = "new content" if change == "content" else "assistant"
    with pytest.raises(MemoryError, match="source_snapshot_changed"):
        inspect(db, payload={**LIST, "expected_snapshot": snapshot}, binding=binding)


@pytest.mark.parametrize(
    "change",
    [
        {"message_uid": "invalid"},
        {"message_uid": None},
        {"active": 0},
        {"compacted": 1},
        {"session_id": "other"},
        {"id": True},
        {"content": ["not text"]},
        {"content": "\ud800"},
        {"absorbed_message_uids": "malformed"},
        {"absorbed_message_uids": '["invalid"]'},
        {"content": "x" * 16385},
    ],
)
def test_invalid_rows_fail_entire_observation(change):
    source = row()
    source.update(change)
    with pytest.raises(MemoryError):
        inspect(Reader([source]))


def test_duplicate_uid_or_lineage_and_incomplete_scan_fail():
    a, b = row(), row(2)
    b["message_uid"] = a["message_uid"]
    with pytest.raises(MemoryError, match="ambiguous"):
        inspect(Reader([a, b]))
    b = row(2)
    b["absorbed_message_uids"] = json.dumps([a["message_uid"]])
    with pytest.raises(MemoryError, match="ambiguous"):
        inspect(Reader([a, b]))
    db = Reader([row()])
    db.revision = (("session",), 2, 2, 0)
    with pytest.raises(MemoryError, match="incomplete"):
        inspect(db)


def test_generation_change_never_returns_payload_and_missing_session_fails():
    db = Reader([row()])
    db.valid = False
    with pytest.raises(MemoryError, match="source_generation_changed"):
        inspect(db)
    db.valid = True
    db.get_session = lambda _: None
    with pytest.raises(MemoryError, match="source_not_found"):
        inspect(db)


@pytest.mark.parametrize(
    "raw",
    [
        "source-list --limit 0",
        "source-list --limit 21",
        "source-list --limit true",
        "source-list --path /tmp/private",
        "source-list --session-id other",
        "source-list --lim 1",
        "source-list --after " + "1" * 32,
        "source-list --expected-snapshot invalid",
        "source-list extra",
        "source-show",
        "source-show " + "1" * 32,
        "source-show bogus --expected-snapshot " + "a" * 64,
        "source-show " + "1" * 32 + " --expected-snapshot " + "A" * 64,
    ],
)
def test_parser_refuses_unsupported_or_unfenced_selection(raw):
    with pytest.raises(MemoryError, match="invalid_request"):
        commands.parse_command(raw)


@pytest.mark.parametrize(
    "operation,payload",
    [
        ([], {}),
        ("source_accept", {}),
        ("source_list", []),
        ("source_list", {**LIST, "limit": True}),
        ("source_list", {**LIST, "after": False}),
        ("source_list", {**LIST, "expected_snapshot": 1}),
        ("source_show", {"message_uid": None, "expected_snapshot": "a" * 64}),
    ],
)
def test_strict_direct_validation(operation, payload):
    with pytest.raises(MemoryError, match="invalid_request"):
        review.validate(operation, payload)


def test_commands_dispatch_outside_canonical_opener_and_preserve_gates(local, monkeypatch):
    instance, call, config, binding, opened = local
    source_reads = []
    listing = inspect(Reader([row()]))

    def read(home, sid, operation, payload):
        source_reads.append((home, sid, operation, payload))
        return {"data": listing, "replayed": False}

    monkeypatch.setattr(commands, "review_native_sources", read)
    assert call("source-list")["data"] == listing
    assert source_reads[0][1:3] == ("session", "source_list")
    assert not opened
    for key, value, code in [
        ("local_memory", False, "local_memory_disabled"),
        ("local_memory", "true", "invalid_configuration"),
    ]:
        config[key] = value
        assert call("source-list")["error"]["code"] == code
    config["local_memory"] = True
    binding["key"] = "other"
    assert call("source-list")["error"]["code"] == "unsupported_origin"
    binding["key"] = "route"
    instance.close()
    assert call("source-list")["error"]["code"] == "local_memory_unloaded"
    assert len(source_reads) == 1 and not opened


def test_fixed_private_opener_uses_read_only_and_rechecks_file_binding(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    path.write_bytes(b"synthetic")
    path.chmod(0o600)
    calls = []

    @contextmanager
    def opener(actual, *, read_only):
        calls.append((actual, read_only))
        yield Reader([row()])

    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=opener))
    result = review.run(tmp_path, "session", "source_list", LIST)
    assert result["data"]["eligible_count"] == 1
    assert calls == [(path, True)]
    old_binding = review._binding
    count = 0

    def changed(home):
        nonlocal count
        count += 1
        real, identity = old_binding(home)
        return (real, identity) if count == 1 else (real, (identity[0], identity[1] + 1))

    monkeypatch.setattr(review, "_binding", changed)
    with pytest.raises(MemoryError, match="source_generation_changed"):
        review.run(tmp_path, "session", "source_list", LIST)


@pytest.mark.parametrize(
    "kind", ["missing", "symlink", "hardlink", "directory", "public", "journal"]
)
def test_unsafe_path_refused_before_native_import(tmp_path, monkeypatch, kind):
    path = tmp_path / "state.db"
    if kind != "missing":
        path.write_bytes(b"synthetic")
        path.chmod(0o600)
    if kind == "symlink":
        path.rename(tmp_path / "other")
        path.symlink_to(tmp_path / "other")
    elif kind == "hardlink":
        os.link(path, tmp_path / "other")
    elif kind == "directory":
        path.unlink()
        path.mkdir()
    elif kind == "public":
        path.chmod(0o644)
    elif kind == "journal":
        journal = tmp_path / "state.db-journal"
        journal.write_bytes(b"synthetic")
        journal.chmod(0o600)
    monkeypatch.setitem(sys.modules, "hermes_state", None)
    with pytest.raises(MemoryError) as error:
        review.run(tmp_path, "session", "source_list", LIST)
    assert error.value.code in {"source_unsafe_path", "source_storage_unavailable"}


def test_original_arguments_are_unchanged_and_unexpected_host_failure_redacted(
    tmp_path, monkeypatch
):
    original = copy.deepcopy(LIST)
    assert review.validate("source_list", LIST) == LIST == original
    path = tmp_path / "state.db"
    path.write_bytes(b"synthetic")
    path.chmod(0o600)

    def broken(*args, **kwargs):
        raise RuntimeError("private host secret")

    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=broken))
    with pytest.raises(MemoryError) as error:
        review.run(tmp_path, "session", "source_list", LIST)
    assert error.value.code == "source_read_failed"
    assert "private" not in str(error.value)


def test_human_review_includes_absorbed_lineage_and_consistency():
    source = row()
    absorbed = "f" * 32
    source["absorbed_message_uids"] = json.dumps([absorbed])
    db = Reader([source])
    listing = inspect(db)
    result = show(db, listing["snapshot"])
    assert result["item"]["absorbed_message_uids"] == [absorbed]
    text = render_memory_result(envelope(result), operation="source_show", payload={})
    assert absorbed in text and 'Read consistency: "generation_validated"' in text
