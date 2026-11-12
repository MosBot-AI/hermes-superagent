"""Development counterexamples for bounded literal naming slots, not fixture labels."""

import json
import sqlite3

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryService
from personal_agent.memory_query import automatic_recall_terms, filter_automatic_recall


@pytest.mark.parametrize("prefix", ["", "请问", "请告诉我", "告诉我", "我想知道"])
@pytest.mark.parametrize("ending", ["叫什么", "叫什么名字", "叫什么呢", "叫什么名字吗"])
def test_request_prefixes_and_naming_endings(prefix, ending):
    query = prefix + "只是园的负责人" + ending + "？"
    assert automatic_recall_terms(query) == ["只是园", "负责人"]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("请问云杉的负责人叫什么名字呢？", ["云杉", "负责人"]),
        ("北京-Hermes-v4的版本叫什么？", ["北京", "Hermes-v4", "版本"]),
        ("Red Ridge的负责人叫什么？", ["Red", "Ridge", "负责人"]),
        ("我的经理叫什么名字？", ["经理"]),
        ("云杉云杉的云杉云杉叫什么？", ["云杉云杉"]),
        ("A A 的B B叫什么？", ["A", "B"]),
    ],
)
def test_literal_mixed_scripts_self_reference_and_deduplication(query, expected):
    assert automatic_recall_terms(query) == expected
    assert all(term in query for term in expected)


@pytest.mark.parametrize(
    "query,prior",
    [
        ("云叫杉的经理叫什么？", ["云叫杉", "经理叫"]),
        ("云杉的呼叫员叫什么？", ["云杉", "呼叫员叫"]),
        ("云杉的部门的经理叫什么？", ["云杉", "部门的经理叫"]),
        ("云杉和松柏的经理叫什么？", ["云杉", "松柏", "经理叫"]),
        ("云杉的经理叫什么，地址在哪？", ["云杉", "经理叫", "地址", "哪"]),
        ("云杉的经理叫什么呀？", ["云杉", "经理叫", "呀"]),
        ("云杉的经理叫什么名字啊？", ["云杉", "经理叫", "名字啊"]),
    ],
)
def test_unsupported_and_ambiguous_syntax_preserves_exact_prior_terms(query, prior):
    assert automatic_recall_terms(query) == prior


@pytest.mark.parametrize(
    "query",
    [
        "云杉的___叫什么？",
        "---的经理叫什么？",
        "___的---叫什么名字呢？",
        "请问云杉的 - _ 叫什么名字？",
        "我的___叫什么？",
        "A B C D E F G H的经理叫什么？",
        "人" * 129 + "的经理叫什么？",
        "云杉的" + "人" * 129 + "叫什么？",
        "云" * 2049,
        "/云杉的经理叫什么？",
        "云杉的经理叫什么？\x00",
        "云杉的经理叫什么？\u202e",
        None,
        42,
    ],
)
def test_malformed_marker_only_and_over_limit_questions_fail_closed(query):
    assert automatic_recall_terms(query) == []


def test_exact_term_and_input_limits():
    assert automatic_recall_terms("A B C D E F G的经理叫什么？") == [
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "经理",
    ]
    assert automatic_recall_terms("人" * 128 + "的经理叫什么？") == ["人" * 128, "经理"]
    query = "云杉的经理叫什么？"
    assert automatic_recall_terms(query + " " * (2048 - len(query))) == ["云杉", "经理"]
    assert automatic_recall_terms(query + " " * (2049 - len(query))) == []


def test_backend_required_slots_negative_evidence_omissions_and_explicit_reads_unchanged():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    backend = create_backend()
    backend.open(
        conn, namespace_id="naming", session_ref="session", source_kind="explicit_local_operator"
    )
    try:
        ids = []
        for index, content in enumerate(
            [
                "Red Ridge 经理是甲",
                "Red Ridge 经理不是乙",
                "Red Ridge 预算三元",
                "Blue Ridge 经理是丙",
            ]
        ):
            ids.append(
                backend.execute("remember", {"content": content, "request_id": str(index)})["data"][
                    "record_id"
                ]
            )
        before = conn.total_changes
        query = "Red Ridge的经理叫什么？"
        terms = automatic_recall_terms(query)
        raw = MemoryService(backend).execute("recall", {"queries": terms})["data"]
        filtered = filter_automatic_recall(raw, query, terms)
        assert {r["record_id"] for r in filtered["items"]} == set(ids[:2])
        assert len(raw["items"]) == 4
        assert filtered["matched_records"] == raw["matched_records"] == 4
        assert filtered["omitted_records"] == raw["omitted_records"] + 2
        assert filtered["items_json_chars"] == len(json.dumps(filtered["items"], sort_keys=True))
        assert filtered["automatic_filter"] == {
            "minimum_matched_terms": 3,
            "required_query_indices": [0, 1, 2],
            "filtered_returned_records": 2,
            "refilled": False,
        }
        explicit = MemoryService(backend).execute("recall", {"queries": ["Red", "Ridge"]})["data"]
        assert {r["record_id"] for r in explicit["items"]} == set(ids)
        assert "automatic_filter" not in explicit
        assert MemoryService(backend).execute("search", {"query": query})["data"]["items"] == []
        assert conn.total_changes == before
    finally:
        backend.close()
        conn.close()
