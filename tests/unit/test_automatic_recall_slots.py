"""General grammatical slots, independent of fixed evaluation labels."""

import json

import pytest

from personal_agent.memory_query import automatic_recall_terms, filter_automatic_recall


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Comet delivery 谁管理", ["Comet", "delivery", "管理"]),
        ("Comet delivery 由谁管理？", ["Comet", "delivery", "管理"]),
        ("我喜欢哪类小说？", ["小说"]),
        ("沈望喜欢哪种小说", ["沈望", "小说"]),
        ("请问会宁的读书会地点是哪里？", ["会宁", "读书会地点"]),
        ("我家的茶柜目前在哪里", ["我家", "茶柜"]),
        ("我的通信地址现在是哪里", ["通信地址"]),
        ("请告诉我Red Ridge的版本是什么", ["Red", "Ridge", "版本"]),
        ("北京-Hermes-v4的版本是什么", ["北京", "Hermes-v4", "版本"]),
        ("从容的会议是哪天", ["从容", "会议"]),
    ],
)
def test_literal_whole_slots(query, expected):
    assert automatic_recall_terms(query) == expected
    assert all(term in query for term in expected)


def test_entity_words_cannot_replace_attribute_and_other_entities_cannot_replace_subject():
    query = "Comet delivery 谁管理"
    terms = automatic_recall_terms(query)
    data = {
        "items": [
            {"record_id": "same-entity-wrong-attribute", "matched_queries": [0, 1]},
            {"record_id": "other-entity-same-attribute", "matched_queries": [1, 2]},
            {"record_id": "current", "matched_queries": [0, 1, 2]},
            {"record_id": "denied-fact", "matched_queries": [0, 1, 2]},
        ],
        "matched_records": 10,
        "omitted_records": 6,
        "skipped_for_budget": 2,
        "items_json_chars": 0,
    }
    result = filter_automatic_recall(data, query, terms)
    assert [item["record_id"] for item in result["items"]] == ["current", "denied-fact"]
    assert result["omitted_records"] == 8
    assert result["matched_records"] == 10
    assert result["skipped_for_budget"] == 2
    assert result["items_json_chars"] == len(json.dumps(result["items"], sort_keys=True))
    assert result["automatic_filter"] == {
        "minimum_matched_terms": 3,
        "required_query_indices": [0, 1, 2],
        "filtered_returned_records": 2,
        "refilled": False,
    }
    assert len(data["items"]) == 4


def test_recognized_oversized_slots_fail_closed_without_losing_the_attribute():
    assert automatic_recall_terms("a b c d e f g h i 谁管理") == []
    assert automatic_recall_terms("人" * 129 + "的生日是哪天") == []


def test_eight_required_terms_and_deduplication():
    query = "A B C D E F G 谁管理"
    assert automatic_recall_terms(query) == ["A", "B", "C", "D", "E", "F", "G", "管理"]
    assert automatic_recall_terms("A A 的电话是多少") == ["A", "电话"]


def test_unrecognized_multiclause_input_keeps_historical_planner():
    # Do not pretend that a single-clause recognizer parses an arbitrary request.
    assert automatic_recall_terms("我不喝咖啡，早餐选什么？") == ["咖啡", "早餐选"]
    assert automatic_recall_terms("王明 生日") == ["王明", "生日"]
