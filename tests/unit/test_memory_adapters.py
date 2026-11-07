"""Offline adapter review and fail-closed runtime negotiation."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_adapters import (
    ENTRY_POINT_GROUP,
    AdapterCandidate,
    discover_adapter_candidates,
    select_reviewed_candidate,
    validate_backend_descriptor,
)
from personal_agent.memory_backend import MemoryError, MemoryService


def error(code, call):
    with pytest.raises(MemoryError) as caught:
        call()
    assert caught.value.code == code
    assert "private" not in str(caught.value)


class Backend:
    def __init__(self, **changes):
        self.description = {**create_backend().describe(), **changes}
        self.calls = []

    def describe(self):
        return self.description

    def execute(self, operation, payload):
        self.calls.append((operation, payload))
        return {}

    def close(self):
        pass


def test_local_descriptor_is_immutable_and_detached():
    backend = Backend()
    descriptor = validate_backend_descriptor(backend.describe())
    backend.description["capabilities"].clear()
    backend.description["max_content_chars"] = 1
    assert "durable_write" in descriptor.capabilities
    assert dict(descriptor.limits)["max_content_chars"] == 2048
    with pytest.raises(AttributeError):
        descriptor.adapter_id = "changed"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("api_version", True),
        ("api_version", 1.0),
        ("api_version", 2),
        ("api_version", "1"),
        ("schema_version", True),
        ("schema_version", 0),
        ("schema_version", 2**31),
        ("adapter_id", "private/name"),
        ("adapter_id", "A" * 65),
        ("adapter_version", "private\nversion"),
        ("deployment", "remote_canonical"),
        ("query_semantics", "semantic_similarity"),
        ("deletion", "eventual"),
        ("export_format", "snapshot"),
        ("export_scope", "everything"),
        ("data_recipients", ["private.example"]),
        ("data_recipients", ()),
        ("capabilities", ["explicit_records", "checkpoint"]),
        ("capabilities", ["explicit_records", "explicit_records"]),
        ("capabilities", []),
        ("capabilities", "explicit_records"),
        ("unsupported", ["explicit_records"]),
        ("unsupported", [["private"]]),
        ("unsupported", ["x"] * 33),
        ("max_content_chars", True),
        ("max_content_chars", 2049),
        ("max_topic_chars", 0),
        ("max_query_chars", 129),
        ("max_page_records", 51),
        ("max_total_records", 1001),
        ("max_total_mutations", 1),
    ],
)
def test_bad_descriptors_never_reach_execute(key, value):
    backend = Backend(**{key: value})
    error("unsupported_backend", lambda: MemoryService(backend))
    assert backend.calls == []


@pytest.mark.parametrize("value", [None, [], {"api_version": 1}, {"private": "content"}])
def test_descriptor_requires_complete_shape(value):
    error("unsupported_backend", lambda: validate_backend_descriptor(value))


def test_unknown_fields_and_missing_methods_fail_closed():
    backend = Backend(private="value")
    error("unsupported_backend", lambda: MemoryService(backend))
    error("unsupported_backend", lambda: MemoryService(object()))


@pytest.mark.parametrize("method", ["describe", "execute", "close"])
def test_protocol_members_must_be_callable(method):
    backend = Backend()
    setattr(backend, method, 1)
    error("unsupported_backend", lambda: MemoryService(backend))


def test_describe_exception_is_redacted():
    class Broken(Backend):
        def describe(self):
            raise RuntimeError("private path and data")

    error("unsupported_backend", lambda: MemoryService(Broken()))


@pytest.mark.parametrize(
    ("operation", "payload", "capability"),
    [
        ("remember", {"content": "test", "request_id": "r"}, "durable_write"),
        ("remember", {"content": "test", "request_id": "r"}, "idempotency"),
        (
            "correct",
            {
                "record_id": str(uuid4()),
                "content": "test",
                "expected_revision": 1,
                "request_id": "r",
            },
            "cas",
        ),
        (
            "forget",
            {"record_id": str(uuid4()), "expected_revision": 1, "request_id": "r"},
            "cas",
        ),
        ("search", {"query": "test"}, "literal_search"),
        ("recall", {"queries": ["test"]}, "bounded_recall"),
        ("recall", {"queries": ["test"]}, "literal_search"),
        ("export", {}, "bounded_record_export"),
        ("changes", {}, "metadata_changes"),
        ("consumer_get", {"consumer_id": "x"}, "durable_consumer_cursor"),
        (
            "consumer_advance",
            {"consumer_id": "x", "expected_revision": 0, "through_sequence": 0, "request_id": "x"},
            "durable_consumer_cursor",
        ),
        (
            "consumer_advance",
            {"consumer_id": "x", "expected_revision": 0, "through_sequence": 0, "request_id": "x"},
            "cas",
        ),
        (
            "consumer_advance",
            {"consumer_id": "x", "expected_revision": 0, "through_sequence": 0, "request_id": "x"},
            "idempotency",
        ),
    ],
)
def test_missing_capabilities_rejected_before_call(operation, payload, capability):
    backend = Backend()
    backend.description["capabilities"].remove(capability)
    service = MemoryService(backend)
    error("capability_unavailable", lambda: service.execute(operation, payload))
    assert backend.calls == []
    assert service.execute("list", {}) == {"data": {}, "replayed": False}


@pytest.mark.parametrize(
    ("operation", "payload", "limit", "ceiling"),
    [
        ("remember", {"content": "abc", "request_id": "r"}, "max_content_chars", 2),
        (
            "remember",
            {"content": "test", "topic": "abc", "request_id": "r"},
            "max_topic_chars",
            2,
        ),
        ("search", {"query": "abc"}, "max_query_chars", 2),
        ("recall", {"queries": ["a", "abc"]}, "max_query_chars", 2),
        ("recall", {"queries": ["a"], "limit": 3}, "max_page_records", 2),
        ("list", {}, "max_page_records", 10),
        ("export", {"limit": 3}, "max_page_records", 2),
        ("changes", {"limit": 3}, "max_page_records", 2),
    ],
)
def test_smaller_declared_limits_not_silently_overridden(operation, payload, limit, ceiling):
    backend = Backend(**{limit: ceiling})
    service = MemoryService(backend)
    error("backend_limit_exceeded", lambda: service.execute(operation, payload))
    assert backend.calls == []


def test_service_validates_request_before_capability_or_backend():
    backend = Backend(capabilities=["explicit_records"])
    service = MemoryService(backend)
    error("invalid_request", lambda: service.execute("remember", {"private": "bad"}))
    assert backend.calls == []


def entry(name="sample", *, distribution="Sample.Memory", version="1.2.3", value="sample:factory"):
    def load():
        raise AssertionError("Discovery must never import third-party code")

    return SimpleNamespace(
        name=name,
        group=ENTRY_POINT_GROUP,
        value=value,
        dist=SimpleNamespace(metadata={"Name": distribution}, version=version),
        load=load,
    )


def catalog(monkeypatch, entries):
    def installed(*, group):
        assert group == ENTRY_POINT_GROUP
        return entries

    monkeypatch.setattr("personal_agent.memory_adapters.metadata.entry_points", installed)


def test_discovery_and_selection_never_import_or_call_factories(monkeypatch):
    catalog(monkeypatch, [entry("zulu"), entry("alpha", distribution="Other")])
    candidates = discover_adapter_candidates()
    assert [item.adapter_id for item in candidates] == ["alpha", "zulu"]
    assert candidates[1] == AdapterCandidate("zulu", "sample-memory", "1.2.3", "sample:factory")
    assert select_reviewed_candidate(candidates[1]) == candidates[1]


def test_empty_catalog_has_no_implicit_local_fallback(monkeypatch):
    catalog(monkeypatch, [])
    assert discover_adapter_candidates() == ()
    error(
        "adapter_not_installed",
        lambda: select_reviewed_candidate(AdapterCandidate("sample", "example", "1", "x:y")),
    )


@pytest.mark.parametrize(
    "candidate",
    [entry("sample", distribution="Other"), entry(version="2"), entry(value="other:factory")],
)
def test_changed_distribution_version_or_target_requires_new_review(monkeypatch, candidate):
    catalog(monkeypatch, [entry()])
    reviewed = discover_adapter_candidates()[0]
    catalog(monkeypatch, [candidate])
    error("adapter_review_changed", lambda: select_reviewed_candidate(reviewed))


def test_duplicate_and_reserved_ids_fail_whole_discovery(monkeypatch):
    catalog(monkeypatch, [entry(), entry(distribution="Other")])
    error("adapter_id_conflict", discover_adapter_candidates)
    for name in ("local_sqlite", "builtin", "default", "none"):
        catalog(monkeypatch, [entry(name)])
        error("reserved_adapter_id", discover_adapter_candidates)


@pytest.mark.parametrize(
    "candidate",
    [
        entry("private/name"),
        entry(distribution="private\nname"),
        entry(version="private version"),
        entry(value="x:y [extras]"),
        entry(value="x"),
        entry(value="x:y; private()"),
    ],
)
def test_malformed_metadata_rejected_without_import(monkeypatch, candidate):
    catalog(monkeypatch, [candidate])
    error("invalid_adapter_metadata", discover_adapter_candidates)


def test_missing_distribution_wrong_group_and_discovery_errors(monkeypatch):
    item = entry()
    item.dist = None
    catalog(monkeypatch, [item])
    error("invalid_adapter_metadata", discover_adapter_candidates)
    item = entry()
    item.group = "hermes_agent.memory_providers"
    catalog(monkeypatch, [item])
    error("invalid_adapter_metadata", discover_adapter_candidates)

    def broken(**_kwargs):
        raise OSError("private directory")

    monkeypatch.setattr("personal_agent.memory_adapters.metadata.entry_points", broken)
    error("adapter_discovery_failed", discover_adapter_candidates)


def test_discovery_has_candidate_bound(monkeypatch):
    catalog(monkeypatch, [entry(f"adapter_{index}") for index in range(129)])
    error("adapter_discovery_limit", discover_adapter_candidates)


def test_review_target_cannot_be_an_unstructured_model_payload(monkeypatch):
    catalog(monkeypatch, [entry()])
    error("invalid_adapter_metadata", lambda: select_reviewed_candidate({"adapter_id": "sample"}))


def test_descriptor_is_not_mutated_during_validation():
    description = create_backend().describe()
    original = deepcopy(description)
    validate_backend_descriptor(description)
    assert description == original
