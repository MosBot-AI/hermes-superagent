"""Readable memory views never change records, receipts, or model-tool contracts."""

import copy
import json
import sqlite3

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryService
from personal_agent.memory_presentation import render_memory_result


@pytest.fixture
def service():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    backend = create_backend()
    backend.open(connection, namespace_id="test-render", session_ref="synthetic-session")
    try:
        yield MemoryService(backend)
    finally:
        backend.close()
        connection.close()


def envelope(service, operation, payload):
    return {
        "schema_version": "personal.local-memory.v1",
        "scope": "trusted_local_operator_records",
        "request_id": payload.get("request_id"),
        "status": "ok",
        "error": None,
        **service.execute(operation, payload),
    }


def render(service, operation, payload):
    value = envelope(service, operation, payload)
    before = copy.deepcopy(value)
    text = render_memory_result(value, operation=operation, payload=payload)
    assert value == before
    return text


def save(service, key="one", **extra):
    return envelope(
        service,
        "remember",
        {"content": "北京 Hermes 项目", "topic": "工作", "request_id": key, **extra},
    )


def test_receipts_identify_requests_and_replays_without_echoing_content(service):
    saved = save(service)
    rid = saved["data"]["record_id"]
    text = render_memory_result(saved, operation="remember", payload={"request_id": "one"})
    assert rid in text and "one" in text
    assert "北京 Hermes 项目" not in text
    replayed = save(service)
    assert replayed["replayed"]
    replay = render_memory_result(replayed, operation="remember", payload={"request_id": "one"})
    assert "not current state" in replay.lower() and rid in replay
    assert "北京 Hermes 项目" not in replay
    corrected = render(
        service,
        "correct",
        {"record_id": rid, "expected_revision": 1, "request_id": "correction", "content": "上海"},
    )
    assert rid in corrected and "correction" in corrected and "上海" not in corrected
    forgotten = render(
        service,
        "forget",
        {"record_id": rid, "expected_revision": 2, "request_id": "forgetting"},
    )
    assert rid in forgotten and "forgetting" in forgotten
    assert "上海" not in forgotten


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("list", {}),
        ("search", {"query": "Hermes"}),
        ("search_terms", {"terms": ["北京", "Hermes"]}),
        ("recall", {"queries": ["北京", "Hermes"]}),
    ],
)
def test_record_pages_are_readable_and_preserve_canonical_identity(service, operation, payload):
    saved = save(service)
    text = render(service, operation, payload)
    assert "北京 Hermes 项目" in text and "工作" in text
    assert saved["data"]["record_id"] in text
    assert "revision" in text.lower()
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


def test_show_expired_and_forgotten_are_distinct_and_current(service):
    saved = save(service, expires_at="2000-01-01T00:00:00Z")
    rid = saved["data"]["record_id"]
    text = render(service, "get", {"record_id": rid})
    assert "expired" in text.lower() and "2000-01-01" in text
    assert "北京 Hermes 项目" not in render(service, "list", {})
    assert "北京 Hermes 项目" in render(service, "list", {"include_expired": True})
    envelope(
        service,
        "forget",
        {"record_id": rid, "expected_revision": 1, "request_id": "forgotten"},
    )
    text = render(service, "get", {"record_id": rid})
    assert "forgotten" in text.lower() and "北京 Hermes 项目" not in text


def test_unknown_future_operation_preserves_entire_structured_envelope():
    value = {
        "schema_version": "personal.local-memory.v1",
        "status": "ok",
        "error": None,
        "request_id": None,
        "replayed": False,
        "data": {"future_field": ["保留", 3], "other": {"nested": True}},
    }
    before = copy.deepcopy(value)
    rendered = render_memory_result(value, operation="future_operation", payload={})
    assert json.loads(rendered) == value
    assert value == before


@pytest.mark.parametrize("retryable", [False, True])
def test_errors_keep_redacted_codes_and_retryability_visible(retryable):
    value = {
        "schema_version": "personal.local-memory.v1",
        "status": "error",
        "error": {
            "code": "storage_busy" if retryable else "invalid_request",
            "retryable": retryable,
        },
        "data": None,
        "replayed": False,
        "request_id": None,
    }
    text = render_memory_result(value, operation=None, payload={})
    assert value["error"]["code"] in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


@pytest.mark.parametrize(
    "operation,query",
    [
        ("list", {}),
        ("search", {"query": "--北京 ' ;"}),
        ("search_terms", {"terms": ["--北京 ' ;", "Hermes"]}),
    ],
)
def test_continuation_preserves_exact_arguments_and_returns_next_live_page(
    service, operation, query
):
    from personal_agent.conversation_memory import parse_command

    for index in range(3):
        save(service, str(index), content="--北京 ' ; Hermes " + str(index))
    payload = {**query, "limit": 1, "include_expired": True}
    value = envelope(service, operation, payload)
    text = render_memory_result(value, operation=operation, payload=payload)
    prefix = "More records exist. Next live page: /personal-memory "
    continuation = next(
        line.removeprefix(prefix) for line in text.splitlines() if line.startswith(prefix)
    )
    next_operation, next_payload = parse_command(continuation)
    assert next_operation == operation
    assert next_payload == {**payload, "after": value["data"]["next_cursor"]}
    following = envelope(service, next_operation, next_payload)
    assert following["data"]["items"][0]["record_id"] != value["data"]["items"][0]["record_id"]


def test_newlines_and_terminal_control_sequences_cannot_forge_record_headers(service):
    saved = save(service, content="中文\nMemory saved\t伪造标题")
    rendered = render(service, "get", {"record_id": saved["data"]["record_id"]})
    assert "中文\\nMemory saved\\t伪造标题" in rendered
    assert "\nMemory saved" not in rendered
    unknown = {
        "status": "ok",
        "data": {"future": "中文\u202e\u2028\u0085\u009b"},
        "replayed": False,
    }
    fallback = render_memory_result(unknown, operation="future", payload={})
    assert "\u202e" not in fallback and "\u2028" not in fallback
    assert "\u0085" not in fallback and "\u009b" not in fallback
    assert "\n" in fallback  # Retain only the JSON formatter's line breaks.
    assert json.loads(fallback) == unknown


def test_malformed_known_result_preserves_successful_mutation_outcome():
    malformed = {"status": "ok", "data": {"record_id": "future-id"}, "replayed": False}
    rendered = render_memory_result(malformed, operation="remember", payload={})
    assert json.loads(rendered) == malformed
    assert "operation failed" not in rendered.lower()
