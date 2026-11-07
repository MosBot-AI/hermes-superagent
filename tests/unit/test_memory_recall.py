"""Bounded literal recall uses current canonical data, never a stale derived cache."""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from personal_agent.conversation_memory import parse_command
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService, validate_request
from personal_agent.memory_tool_contract import normalize_memory_tool_request


@contextmanager
def opened(path=":memory:", *, source="explicit_local_operator"):
    conn = sqlite3.connect(path, isolation_level=None)
    backend = create_backend()
    backend.open(conn, namespace_id="recall-test", session_ref="session", source_kind=source)
    try:
        yield backend, conn
    finally:
        backend.close()
        conn.close()


def remember(backend, content, key, topic=""):
    return backend.execute("remember", {"content": content, "topic": topic, "request_id": key})[
        "data"
    ]["record_id"]


def recall(backend, queries, **kwargs):
    return MemoryService(backend).execute("recall", {"queries": queries, **kwargs})["data"]


def test_rank_counts_topic_tie_break_newest_and_no_duplicate_records():
    with opened() as (backend, conn):
        both = remember(backend, "中文 summary", "both")
        topic = remember(backend, "note", "topic", topic="中文")
        older = remember(backend, "中文 old", "old")
        newer = remember(backend, "中文 new", "new")
        remember(backend, "unrelated", "none")
        before = conn.total_changes
        data = recall(backend, ["中文", "summary"])
        assert [item["record_id"] for item in data["items"]] == [both, topic, newer, older]
        assert data["items"][0]["matched_queries"] == [0, 1]
        assert all(item["matched_queries"] == [0] for item in data["items"][1:])
        assert data["watermark"] == 5
        assert data["matched_records"] == 4
        assert data["omitted_records"] == data["skipped_for_budget"] == 0
        assert data["items_json_chars"] == len(json.dumps(data["items"], sort_keys=True))
        assert data["scope"] == "current_active_records_single_read_snapshot"
        assert data["authority"] == "stored_data_not_instructions_or_permission"
        assert conn.total_changes == before
        assert not conn.in_transaction


def test_literals_not_sql_fts_or_semantic_and_short_chinese_supported():
    with opened() as (backend, _):
        for index, content in enumerate(("Tea", "tea", "%_", "中", "' OR 1=1 --")):
            remember(backend, content, str(index))
        for query in ("Tea", "tea", "%_", "中", "' OR 1=1 --"):
            assert [item["content"] for item in recall(backend, [query])["items"]] == [query]
        assert recall(backend, ["coffee"])["items"] == []
        assert recall(backend, ["te"])["matched_records"] == 1


def test_serialized_budget_skips_whole_record_then_tries_smaller_match():
    with opened() as (backend, _):
        small = remember(backend, '茶 "quote"\\path', "small")
        remember(backend, "茶" * 2048, "large")
        data = recall(backend, ["茶"], limit=1, max_chars=1024)
        assert [item["record_id"] for item in data["items"]] == [small]
        assert data["items"][0]["content"] == '茶 "quote"\\path'
        assert data["items_json_chars"] == len(json.dumps(data["items"], sort_keys=True)) <= 1024
        assert data["skipped_for_budget"] == data["omitted_records"] == 1
        assert data["matched_records"] == 2
        # A match too large for the budget is not misreported as no matching records.
        empty = recall(backend, ["茶茶"], max_chars=1024)
        assert empty["items"] == [] and empty["items_json_chars"] == 2
        assert empty["matched_records"] == empty["omitted_records"] == 1


def test_limit_and_budget_exact_boundary():
    with opened() as (backend, _):
        for index in range(10):
            remember(backend, "query " + "x" * 800, str(index))
        first = recall(backend, ["query"], limit=1, max_chars=12000)
        exact = first["items_json_chars"]
        assert exact >= 1024
        result = recall(backend, ["query"], limit=1, max_chars=exact)
        assert result["items"] == first["items"]
        assert result["omitted_records"] == 9 and result["skipped_for_budget"] == 0
        smaller = recall(backend, ["query"], max_chars=exact - 1)
        assert smaller["items"] == []
        assert smaller["omitted_records"] == smaller["skipped_for_budget"] == 10
        assert len(recall(backend, ["query"], max_chars=12000)["items"]) == 6


def test_reopen_correction_forgetting_and_replay_never_restore_old_results(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with opened(path, source="activated_session_model") as (backend, _):
        rid = remember(backend, "早餐豆浆", "save", "饮食")
        first = recall(backend, ["早餐"])
        item = first["items"][0]
        assert item["source"] == "activated_session_model" and item["revision"] == 1
    with opened(path) as (backend, _):
        assert recall(backend, ["早餐"])["items"] == first["items"]
        backend.execute(
            "correct",
            {"record_id": rid, "expected_revision": 1, "content": "早餐燕麦奶", "request_id": "c"},
        )
        assert recall(backend, ["豆浆"])["items"] == []
        corrected = recall(backend, ["燕麦奶"])
        assert corrected["watermark"] == 2
        assert corrected["items"][0]["revision"] == 2
        assert corrected["items"][0]["source"] == "explicit_local_operator"
        backend.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "f"})
    with opened(path, source="activated_session_model") as (backend, _):
        assert remember(backend, "早餐豆浆", "save", "饮食") == rid
        result = recall(backend, ["早餐", "饮食", "燕麦奶", "豆浆"])
        assert result["items"] == [] and result["matched_records"] == 0
        assert result["watermark"] == 3
        assert "早餐" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"queries": []},
        {"queries": "tea"},
        {"queries": ("tea",)},
        {"queries": ["tea"] * 2},
        {"queries": [str(n) for n in range(9)]},
        {"queries": [None]},
        {"queries": [True]},
        {"queries": [1]},
        {"queries": [""]},
        {"queries": [" "]},
        {"queries": ["x" * 129]},
        {"queries": ["x\n"]},
        {"queries": ["x\u202e"]},
        *({"queries": ["tea"], "limit": value} for value in (0, 21, True, "2", 1.0, None)),
        *(
            {"queries": ["tea"], "max_chars": value}
            for value in (1023, 12001, True, "6000", 1024.0, None)
        ),
        *(
            {"queries": ["tea"], key: "forged"}
            for key in ("after", "query", "source", "scope", "record_id")
        ),
    ],
)
def test_strict_recall_validation(payload):
    with pytest.raises(MemoryError, match="invalid_request"):
        validate_request("recall", payload)
    with pytest.raises(MemoryError, match="invalid_request"):
        normalize_memory_tool_request("personal_memory_read", {"action": "recall", **payload})


def test_command_tool_and_request_copy_agree():
    payload = {"queries": ["早餐", "奶"], "limit": 2, "max_chars": 3000}
    expected = ("recall", payload)
    assert parse_command('recall "早餐" "奶" --limit 2 --max-chars 3000') == expected
    assert (
        normalize_memory_tool_request("personal_memory_read", {"action": "recall", **payload})
        == expected
    )
    normalized = validate_request("recall", payload)
    normalized["queries"].append("changed")
    assert payload["queries"] == ["早餐", "奶"]
    assert parse_command("recall tea") == (
        "recall",
        {"queries": ["tea"], "limit": 6, "max_chars": 6000},
    )
    with pytest.raises(MemoryError, match="invalid_request"):
        normalize_memory_tool_request("personal_memory_write", {"action": "recall", **payload})


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_read_snapshot_blocks_other_connection_commit_between_rows_and_watermark(
    tmp_path, operation
):
    path = tmp_path / "memory.sqlite3"
    with opened(path) as (reader, conn), opened(path) as (writer, other):
        rid = remember(writer, "茶旧", "save")
        other.execute("PRAGMA busy_timeout=0")
        payload = {"record_id": rid, "expected_revision": 1, "request_id": "mutation"}
        if operation == "correct":
            payload["content"] = "茶新"
        observed = []

        def attempt_commit(sql):
            if "coalesce(max(sequence),0) FROM events" in sql and not observed:
                observed.append("attempted_after_record_fetch")
                try:
                    writer.execute(operation, payload)
                except MemoryError as error:
                    observed.append(error.code)
                else:
                    observed.append("unexpected_commit")

        conn.set_trace_callback(attempt_commit)
        result = recall(reader, ["茶"])
        conn.set_trace_callback(None)
        assert observed == ["attempted_after_record_fetch", "storage_busy"]
        assert not other.in_transaction  # Failed writer transaction was rolled back.
        assert result["items"][0]["content"] == "茶旧"
        assert result["items"][0]["revision"] == 1 and result["watermark"] == 1
        writer.execute(operation, payload)
        fresh = recall(reader, ["茶"])
        assert fresh["watermark"] == 2
        if operation == "correct":
            assert fresh["items"][0]["content"] == "茶新"
            assert fresh["items"][0]["revision"] == 2
        else:
            assert fresh["items"] == []


def test_exact_two_record_budget_counts_unicode_quotes_and_list_separator():
    with opened() as (backend, _):
        for index in range(3):
            remember(backend, '茶😀"\\' * 80, str(index))
        result = recall(backend, ["茶"], limit=2, max_chars=12000)
        assert len(result["items"]) == 2
        exact = len(json.dumps(result["items"], ensure_ascii=True, sort_keys=True))
        assert 1024 < exact < 12000
        assert recall(backend, ["茶"], limit=2, max_chars=exact)["items"] == result["items"]
        smaller = recall(backend, ["茶"], limit=2, max_chars=exact - 1)
        assert len(smaller["items"]) == 1
        assert smaller["skipped_for_budget"] == smaller["omitted_records"] == 2
        assert smaller["items_json_chars"] == len(json.dumps(smaller["items"], sort_keys=True))


def test_ranking_covers_full_retained_store_not_just_newest_candidates():
    with opened() as (backend, _):
        best = remember(backend, "red blue", "best")
        for index in range(999):
            remember(backend, "blue", str(index))
        data = recall(backend, ["red", "blue"], limit=1)
        assert data["matched_records"] == 1000
        assert data["omitted_records"] == 999
        assert data["items"][0]["record_id"] == best
        assert data["watermark"] == 1000
