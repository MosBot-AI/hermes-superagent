"""Synthetic bounded discovery, strict SDK validation and metadata-only reads."""

import hashlib
import json
import sqlite3
from copy import deepcopy

import pytest
from test_retained_source_recovery import opened as disk_opened
from test_retained_source_sdk import Wrapper
from test_retained_sources import accept, opened, request

from personal_agent.memory_backend import MemoryError
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK, source_request_identity
from personal_agent.retained_source_discovery import validate


def seed_rows(connection, count):
    # Valid terminal synthetic decisions without O(n²) writer setup for page-bound tests.
    for index in range(count):
        key = f"key-{index:04}"
        connection.execute(
            "INSERT INTO retained_source_decisions VALUES "
            "(?,?,?,?,?,?,?,?,?,?,'discarded',NULL,NULL,1)",
            (
                key,
                "reader",
                index + 1,
                hashlib.sha256(key.encode()).hexdigest(),
                hashlib.sha256((key + "identity").encode()).hexdigest(),
                hashlib.sha256((key + "content").encode()).hexdigest(),
                "user",
                "a" * 64,
                "retained_native_snapshot",
                None,
            ),
        )
    connection.commit()


@pytest.mark.parametrize("count", [0, 1, 19, 20, 21, 49, 50, 51, 1000])
@pytest.mark.parametrize("limit", [1, 20, 50])
def test_exact_page_boundaries_and_no_duplicate_or_skipped_items(count, limit):
    with opened() as (sdk, _, connection):
        seed_rows(connection, count)
        payload, found, snapshot = {"state": "all", "limit": limit}, [], None
        while True:
            page = sdk.execute("source_discover", payload)["data"]
            assert page["total"] == count
            assert snapshot is None or page["snapshot"] == snapshot
            snapshot = page["snapshot"]
            assert len(page["items"]) == min(limit, count - len(found))
            found.extend(item["query"]["request_id"] for item in page["items"])
            if page["next_offset"] is None:
                break
            payload.update(offset=page["next_offset"], expected_snapshot=snapshot)
        assert found == [f"key-{index:04}" for index in range(count)]
        assert sdk.execute("source_discover", {})["data"]["items"] == []


def test_default_pending_and_explicit_filters_and_exact_recovery():
    with opened() as (sdk, _, _):
        pending = request("pending", consumer_id="zebra")
        accepted = request("accepted", "accepted original", consumer_id="alpha")
        sdk.execute("source_stage", pending)
        receipt = accept(sdk, accepted)
        page = sdk.execute("source_discover", {})["data"]
        assert len(page["items"]) == 1
        query = page["items"][0]["query"]
        assert query == source_request_identity(pending)
        assert sdk.execute("source_status", query)["data"]["decision"]["state"] == "pending"
        sdk.execute("source_discard", query)
        assert sdk.execute("source_discover", {})["data"]["total"] == 0
        assert sdk.execute("source_discover", {"consumer_id": "missing"})["data"]["total"] == 0
        page = sdk.execute("source_discover", {"state": "accepted"})["data"]
        assert page["items"][0]["record"] == receipt
        sdk.execute(
            "correct",
            {
                "record_id": receipt["record_id"],
                "expected_revision": 1,
                "content": "corrected",
                "request_id": "correction",
            },
        )
        page = sdk.execute("source_discover", {"state": "all"})["data"]
        assert [x["consumer_id"] for x in page["items"]] == ["alpha", "zebra"]
        item = page["items"][0]
        assert item["record"]["revision"] == 1 and item["current"]["revision"] == 2
        assert item["suppressed"] is True
        sdk.execute(
            "forget",
            {"record_id": receipt["record_id"], "expected_revision": 2, "request_id": "forget"},
        )
        item = sdk.execute("source_discover", {"state": "accepted"})["data"]["items"][0]
        assert item["record"]["status"] == "active" and item["current"]["status"] == "forgotten"
        fresh = request("new-source", consumer_id="different")
        with pytest.raises(MemoryError, match="source_suppressed"):
            sdk.execute("source_stage", fresh)
        raw = json.dumps(page)
        for forbidden in (
            "accepted original",
            "reviewed import",
            "fingerprint",
            "source_identity",
            "receipt_id",
            "observation_id",
            "session_ref",
            "topic",
        ):
            assert forbidden not in raw


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"state": []},
        {"state": "unknown"},
        {"limit": True},
        {"limit": 0},
        {"limit": 51},
        {"limit": 1.0},
        {"offset": True},
        {"offset": -1},
        {"offset": 1001},
        {"offset": 20},
        {"offset": 1, "expected_snapshot": "a" * 64},
        {"expected_snapshot": "a" * 65},
        {"expected_snapshot": False},
        {"consumer_id": "UPPER"},
        {"consumer_id": "x" * 65},
        {"consumer_id": False},
        {"namespace_id": "another"},
        {"path": "/arbitrary"},
        {"state": None},
    ],
)
def test_invalid_requests_before_dispatch(payload):
    with opened() as (_, backend, _):
        wrapper = Wrapper(backend)
        sdk = LocalMemorySDK(wrapper, LocalBinding("synthetic", "session"))
        with pytest.raises(MemoryError, match="invalid_request"):
            sdk.execute("source_discover", payload)
        assert wrapper.calls == []


def test_optional_capability_and_model_refuse_before_dispatch():
    with opened() as (_, backend, _):
        wrapper = Wrapper(backend, omit="retained_source_discovery")
        sdk = LocalMemorySDK(wrapper, LocalBinding("synthetic", "session"))
        with pytest.raises(MemoryError, match="capability_unavailable"):
            sdk.execute("source_discover", {})
        assert wrapper.calls == []
        wrapper = Wrapper(backend)
        sdk = LocalMemorySDK(
            wrapper, LocalBinding("synthetic", "session", "activated_session_model")
        )
        with pytest.raises(MemoryError, match="source_scope_required"):
            sdk.execute("source_discover", {})
        assert wrapper.calls == []
        backend._source_kind = "activated_session_model"
        with pytest.raises(MemoryError, match="source_scope_required"):
            backend.execute("source_discover", {})


@pytest.mark.parametrize(
    "change",
    [
        {"state": "discarded"},
        {"consumer_id": "reader"},
        {"limit": 2},
        {"expected_snapshot": "0" * 64},
    ],
)
def test_snapshot_filter_and_page_size_tampering(change):
    with opened() as (sdk, _, connection):
        seed_rows(connection, 3)
        page = sdk.execute("source_discover", {"state": "all", "limit": 1})["data"]
        payload = {"state": "all", "limit": 1, "expected_snapshot": page["snapshot"], **change}
        with pytest.raises(MemoryError, match="source_discovery_changed"):
            sdk.execute("source_discover", payload)


def test_snapshot_namespace_binding_and_invalid_end_offset():
    with opened() as (sdk, backend, connection):
        seed_rows(connection, 2)
        page = sdk.execute("source_discover", {"state": "all", "limit": 1})["data"]
        payload = {"state": "all", "limit": 1, "expected_snapshot": page["snapshot"]}
        with pytest.raises(MemoryError, match="invalid_cursor"):
            sdk.execute("source_discover", {**payload, "offset": 2})
        connection.execute("UPDATE namespace SET id='other'")
        connection.commit()
        backend._namespace = "other"
        with pytest.raises(MemoryError, match="source_discovery_changed"):
            backend.execute("source_discover", payload)


@pytest.mark.parametrize("mutation", ["stage", "accept", "discard", "correct", "forget"])
def test_other_connection_change_refuses_continuation(tmp_path, mutation):
    path = tmp_path / "synthetic.sqlite"
    with disk_opened(path) as (sdk, _, _):
        a = request("a", consumer_id="a")
        b = request("b", "second source", consumer_id="b")
        sdk.execute("source_stage", a)
        record = accept(sdk, b)
        page = sdk.execute("source_discover", {"state": "all", "limit": 1})["data"]
        with disk_opened(path) as (other, _, _):
            if mutation == "stage":
                other.execute("source_stage", request("c", "third source", consumer_id="c"))
            elif mutation == "accept":
                other.execute("source_accept", a)
            elif mutation == "discard":
                other.execute("source_discard", source_request_identity(a))
            else:
                other.execute(
                    mutation,
                    {
                        "record_id": record["record_id"],
                        "expected_revision": 1,
                        "request_id": "mutate",
                        **({"content": "changed"} if mutation == "correct" else {}),
                    },
                )
        with pytest.raises(MemoryError, match="source_discovery_changed"):
            sdk.execute(
                "source_discover",
                {"state": "all", "limit": 1, "offset": 1, "expected_snapshot": page["snapshot"]},
            )


def test_elapsed_time_stable_but_expiry_boundary_invalidates(monkeypatch):
    from personal_agent import memory_expiry

    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2030-01-01T00:00:00Z")
    with opened() as (sdk, _, _):
        accept(sdk, request("a", expires_at="2030-01-01T00:01:00Z"))
        page = sdk.execute("source_discover", {"state": "all"})["data"]
        query = {"state": "all", "expected_snapshot": page["snapshot"]}
        monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2030-01-01T00:00:59Z")
        assert sdk.execute("source_discover", query)["data"]["snapshot"] == page["snapshot"]
        monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2030-01-01T00:01:00Z")
        with pytest.raises(MemoryError, match="source_discovery_changed"):
            sdk.execute("source_discover", query)
        current = sdk.execute("source_discover", {"state": "all"})["data"]["items"][0]["current"]
        assert current["expired"] is True and current["status"] == "active"


def test_no_payload_reads_or_writes_during_operation():
    with opened() as (sdk, _, connection):
        accept(sdk, request())
        before = connection.total_changes
        reads = []

        def authorize(action, table, column, *_):
            if action == sqlite3.SQLITE_READ:
                reads.append((table, column))
                if (
                    table == "records" and column in {"content", "topic", "source", "session_ref"}
                ) or table in {"memory_candidates", "memory_source_candidates"}:
                    return sqlite3.SQLITE_DENY
            if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        # SDK construction deliberately keeps its existing export-based binding admission.
        connection.set_authorizer(authorize)
        assert sdk.execute("source_discover", {"state": "all"})["data"]["total"] == 1
        connection.set_authorizer(None)
        assert connection.total_changes == before
        assert ("retained_source_decisions", "request_digest") in reads


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE retained_source_decisions SET request_digest='bad'",
        "UPDATE retained_source_decisions SET request_id=printf('%0100000d',1)",
        "UPDATE retained_source_decisions SET source_receipt=printf('%0100000d',1)",
        "UPDATE retained_source_decisions SET receipt=printf('%0100000d',1)",
        "UPDATE retained_source_decisions SET consumer_id='bad consumer'",
        "UPDATE records SET expires_at='broken'",
        "DELETE FROM receipts",
        "DELETE FROM events",
        "UPDATE namespace SET id='other'",
    ],
)
def test_malformed_oversized_metadata_fails_closed(sql):
    with opened() as (sdk, _, connection):
        accept(sdk, request())
        connection.execute(sql)
        connection.commit()
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute("source_discover", {})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra="secret"),
        lambda d: d.update(namespace_id="another"),
        lambda d: d.update(total=True),
        lambda d: d.update(total=1001),
        lambda d: d.update(next_offset=True),
        lambda d: d.update(next_offset=1),
        lambda d: d.update(snapshot="bad"),
        lambda d: d.update(evaluated_at=None),
        lambda d: d.update(items=[]),
        lambda d: d.update(items=d["items"] * 2, total=2),
        lambda d: d.update(limit=True),
        lambda d: d["items"][0].update(content="secret"),
        lambda d: d["items"][0].update(suppressed=1),
        lambda d: d["items"][0].update(source_sequence=1001),
        lambda d: d["items"][0].update(state="pending"),
        lambda d: d["items"][0]["query"].update(expected_digest="bad"),
        lambda d: d["items"][0]["query"].update(request_id="x" * 129),
        lambda d: d["items"][0]["current"].update(expired=True, status="forgotten"),
        lambda d: d["items"][0]["record"].update(revision=2),
    ],
)
def test_sdk_rejects_malformed_result(mutate):
    with opened() as (_, backend, _):
        inner = LocalMemorySDK(backend, LocalBinding("synthetic", "session"))
        accept(inner, request())

        def transform(result):
            mutate(result)
            return result

        sdk = LocalMemorySDK(
            Wrapper(backend, transform=transform), LocalBinding("synthetic", "session")
        )
        with pytest.raises(MemoryError, match="invalid_result"):
            sdk.execute("source_discover", {"state": "all"})


def test_request_defaults_do_not_mutate():
    payload = {"limit": 1}
    original = deepcopy(payload)
    assert validate(payload) == {
        "state": "pending",
        "consumer_id": None,
        "limit": 1,
        "offset": 0,
        "expected_snapshot": None,
    }
    assert payload == original


@pytest.mark.parametrize(
    "state,second_state", [("pending", "pending"), ("all", "pending"), ("all", "discarded")]
)
def test_sdk_rejects_same_consumer_after_pending(state, second_state):
    with opened() as (_, backend, _):
        backend.execute("source_stage", request("a", consumer_id="a"))
        backend.execute("source_stage", request("b", "second", consumer_id="b"))

        def transform(data):
            data["items"][1].update(
                consumer_id="a",
                source_sequence=2,
                state=second_state,
                suppressed=second_state == "discarded",
            )
            return data

        sdk = LocalMemorySDK(
            Wrapper(backend, transform=transform), LocalBinding("synthetic", "session")
        )
        with pytest.raises(MemoryError, match="invalid_result"):
            sdk.execute("source_discover", {"state": state})


def test_filtered_terminal_sequence_gaps_remain_valid():
    with opened() as (sdk, _, _):
        first = request("a")
        second = request("b", "second", expected_sequence=1)
        third = request("c", "third", expected_sequence=2)
        for action in (first, second, third):
            sdk.execute("source_stage", action)
            if action is second:
                sdk.execute("source_accept", action)
            else:
                sdk.execute("source_discard", source_request_identity(action))
        page = sdk.execute("source_discover", {"state": "discarded"})["data"]
        assert [item["source_sequence"] for item in page["items"]] == [1, 3]
