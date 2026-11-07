"""Literal local search: unchanged records, bounded live pages and legacy replay."""

import sqlite3
from uuid import uuid4

import pytest
from test_task_agenda import change, expect_error, seed_v1, snapshot
from test_task_agenda import store as store

from personal_agent.tasks import TaskStore, validate_request


def capture(store, title="Synthetic search", details="", **fields):
    return store.run(
        "capture", {"title": title, "details": details, "request_id": str(uuid4()), **fields}
    )["data"]


def search(store, query, **fields):
    result = store.run("search", {"query": query, **fields})
    assert result["replayed"] is False
    return result["data"]


@pytest.mark.parametrize("field", ["title", "details"])
@pytest.mark.parametrize("query", ["中文", "Case", "%", "_", "' OR 1=1 --", "é", "e\u0301", " x "])
def test_exact_literal_title_or_details(store, field, query):
    record = capture(store, **{field: f"prefix {query} suffix"})
    capture(store, title="unrelated", details="unrelated")
    assert search(store, query)["items"] == [record]


def test_no_casefold_normalization_or_wildcards(store):
    record = capture(store, title="Case café 100% a_b")
    for query in ("case", "CAFÉ", "cafe\u0301", "100_", "a%b", "missing"):
        assert search(store, query) == {"items": [], "next_cursor": None, "has_more": False}
    assert search(store, "%")["items"] == [record]
    assert search(store, "_")["items"] == [record]


@pytest.mark.parametrize(
    "query",
    [
        None,
        True,
        42,
        1.2,
        [],
        {},
        "",
        " ",
        "\u3000",
        "a" * 241,
        "a\n",
        "a\r",
        "a\t",
        "a\x00",
        "a\x7f",
        "a\u202e",
        "a\ud800",
        "a\u2028",
        "a\u2029",
    ],
)
def test_invalid_query_before_sql(store, query):
    traced = []
    store._connection.set_trace_callback(traced.append)
    expect_error("invalid_request", lambda: search(store, query))
    assert traced == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": "x", "request_id": "no-receipt"},
        *[{"query": "x", "limit": value} for value in (False, True, 0, 101, 1.0, "1", None)],
        *[{"query": "x", "state": value} for value in (None, [], {}, "active", "ALL")],
        *[{"query": "x", "after": value} for value in (False, "", "invalid", str(uuid4()).upper())],
    ],
)
def test_invalid_request(payload):
    expect_error("invalid_request", lambda: validate_request("search", payload))


def test_defaults_preserve_text_and_maximum(store):
    query = " x "
    assert validate_request("search", {"query": query}) == {
        "query": query,
        "state": "captured",
        "limit": 20,
        "after": None,
    }
    assert search(store, "x" * 240)["items"] == []
    records = [capture(store) for _ in range(101)]
    traced = []
    store._connection.set_trace_callback(traced.append)
    default = search(store, "search")
    maximum = search(store, "search", limit=100)
    assert default["items"] == records[::-1][:20] and default["has_more"]
    assert maximum["items"] == records[::-1][:100] and maximum["has_more"]
    assert any(sql.endswith("LIMIT 21") for sql in traced)
    assert any(sql.endswith("LIMIT 101") for sql in traced)
    assert all(sql.startswith("SELECT") or sql in ("BEGIN", "COMMIT") for sql in traced)


def test_states_due_dates_and_read_only_records(store):
    active = capture(store, due_date="2028-02-29")
    done = change(store, capture(store), "complete", note="Only note needle")["data"]
    cancelled = change(store, capture(store), "cancel", note="Cancelled")["data"]
    before = snapshot(store._connection)
    assert search(store, "search")["items"] == [active]
    assert search(store, "search", state="done")["items"] == [done]
    assert search(store, "search", state="cancelled")["items"] == [cancelled]
    assert search(store, "search", state="all")["items"] == [cancelled, done, active]
    assert search(store, "needle", state="all")["items"] == []
    assert search(store, "2028-02-29", state="all")["items"] == []
    assert snapshot(store._connection) == before


def test_live_creation_order_pages_and_current_store_anchor(store):
    records = [capture(store) for _ in range(5)]
    first = search(store, "search", limit=2)
    assert first == {"items": records[4:2:-1], "next_cursor": records[3]["id"], "has_more": True}
    change(store, records[3], "complete", note="Resolved between pages")
    change(store, records[0], title="Synthetic search updated")
    capture(store)  # New rows are above the existing creation-sequence anchor.
    second = search(store, "search", limit=2, after=first["next_cursor"])
    assert second == {"items": records[2:0:-1], "next_cursor": records[1]["id"], "has_more": True}
    last = search(store, "search", limit=2, after=second["next_cursor"])
    assert [item["id"] for item in last["items"]] == [records[0]["id"]]
    assert not last["has_more"] and last["next_cursor"] is None
    # An anchor is an existing task, not a token bound to the query or state.
    unrelated = capture(store, title="unrelated")
    assert len(search(store, "search", after=unrelated["id"])["items"]) == 5
    expect_error("invalid_cursor", lambda: search(store, "search", after=str(uuid4())))
    with sqlite3.connect(":memory:") as connection:
        other = TaskStore(connection)
        other.initialize()
        foreign = capture(other)
    expect_error("invalid_cursor", lambda: search(store, "search", after=foreign["id"]))


def test_migration_search_and_legacy_receipts_unchanged(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        history = seed_v1(conn)
        before = snapshot(conn)
        store = TaskStore(conn)
        store.initialize()
        records = search(store, "legacy", state="all")["items"]
        assert len(records) == 2 and all(record["due_date"] is None for record in records)
        assert len(search(store, "legacy")["items"]) == 1
        for operation, request, receipt in history:
            assert store.run(operation, request) == {"data": receipt, "replayed": True}
        after = snapshot(conn)
        for table in ("events", "receipts", "sqlite_sequence"):
            assert after[table] == before[table]
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        assert search(store, "legacy", state="all")["items"] == records
