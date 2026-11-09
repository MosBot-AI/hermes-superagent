"""Pure model-facing contract tests; no provider, native bridge or network."""

import json

import pytest

from personal_agent.memory_backend import MemoryError, validate_request
from personal_agent.memory_tool_contract import (
    PERSONAL_MEMORY_READ_SCHEMA,
    PERSONAL_MEMORY_WRITE_SCHEMA,
    normalize_memory_tool_request,
)

READ = "personal_memory_read"
WRITE = "personal_memory_write"
ID = "abcdef01-2345-4678-9abc-def012345678"
CAS = {"record_id": ID, "expected_revision": 1, "request_id": "stable"}
VALID = [
    (READ, {"action": "list"}),
    (READ, {"action": "list", "limit": 50, "after": ID}),
    (READ, {"action": "show", "record_id": ID}),
    (READ, {"action": "search", "query": "偏好", "after": None}),
    (READ, {"action": "search", "query": "x" * 128, "limit": 1}),
    (READ, {"action": "search_terms", "terms": ["北京", "Hermes"], "include_expired": True}),
    (READ, {"action": "search_terms", "terms": ["x" * 128], "limit": 50, "after": ID}),
    (WRITE, {"action": "remember", "content": "Synthetic\n\tnote", "request_id": "a._-9"}),
    (
        WRITE,
        {"action": "remember", "content": "x" * 2048, "topic": "t" * 128, "request_id": "x" * 128},
    ),
    (WRITE, {"action": "correct", **CAS, "content": "Correction"}),
    (WRITE, {"action": "correct", **CAS, "topic": ""}),
    (WRITE, {"action": "correct", **CAS, "content": "Correction", "topic": "New"}),
    (WRITE, {"action": "forget", **CAS}),
]


@pytest.mark.parametrize("tool,arguments", VALID)
def test_shared_validation_and_input_immutability(tool, arguments):
    before = dict(arguments)
    payload = dict(arguments)
    action = payload.pop("action")
    operation = "get" if action == "show" else action
    assert normalize_memory_tool_request(tool, arguments) == (
        operation,
        validate_request(operation, payload),
    )
    assert arguments == before


@pytest.mark.parametrize(
    "tool,arguments",
    [
        (None, {}),
        ([], {}),
        ("unknown", {}),
        (READ, None),
        (READ, []),
        (READ, "{}"),
        (READ, {}),
        (READ, {"action": None}),
        (READ, {"action": []}),
        (READ, {"action": "get", "record_id": ID}),
        (READ, {"action": "export"}),
        (WRITE, {"action": "export"}),
        (WRITE, {"action": "list"}),
        (READ, {"action": "remember", "content": "x", "request_id": "x"}),
        (READ, {"action": "correct", **CAS, "content": "x"}),
        (READ, {"action": "forget", **CAS}),
        (READ, {"action": "show"}),
        (READ, {"action": "show", "record_id": ID, "limit": 1}),
        (READ, {"action": "list", "query": "x"}),
        (READ, {"action": "search"}),
        (READ, {"action": "search_terms"}),
        (READ, {"action": "search_terms", "query": "北京"}),
        (READ, {"action": "search", "terms": ["北京"]}),
        (WRITE, {"action": "search_terms", "terms": ["北京"]}),
        (READ, {"action": "search_terms", "terms": ["北京"], "max_chars": 6000}),
        (WRITE, {"action": "remember", "content": "x"}),
        (WRITE, {"action": "remember", "request_id": "x"}),
        (WRITE, {"action": "remember", **CAS, "content": "x"}),
        (WRITE, {"action": "correct", **CAS}),
        (WRITE, {"action": "correct", "record_id": ID, "request_id": "x", "content": "x"}),
        (WRITE, {"action": "forget", "expected_revision": 1, "request_id": "x"}),
        (WRITE, {"action": "forget", **CAS, "topic": "x"}),
        (WRITE, {"action": "forget", **CAS, "content": "x"}),
    ],
)
def test_invalid_actions_and_action_specific_fields(tool, arguments):
    with pytest.raises(MemoryError, match="invalid_request"):
        normalize_memory_tool_request(tool, arguments)


@pytest.mark.parametrize(
    "field", ["owner", "profile", "source", "session", "approved", "path", "extra"]
)
@pytest.mark.parametrize("tool,arguments", VALID)
def test_no_caller_selected_context(tool, arguments, field):
    with pytest.raises(MemoryError, match="invalid_request"):
        normalize_memory_tool_request(tool, {**arguments, field: True})


@pytest.mark.parametrize(
    "tool,arguments,field,values",
    [
        (READ, {"action": "list"}, "limit", [True, 1.0, "1", 0, 51, None]),
        (
            WRITE,
            {"action": "forget", **CAS},
            "expected_revision",
            [True, 1.0, "1", 0, 2**63 - 1, None],
        ),
        (
            WRITE,
            {"action": "remember", "content": "x"},
            "request_id",
            ["", " ", "x" * 129, "x\n", True, None],
        ),
        (READ, {"action": "search"}, "query", ["", " ", "x" * 129, "x\n", None, True]),
        (
            WRITE,
            {"action": "remember", "request_id": "x"},
            "content",
            ["", " ", "x" * 2049, "x\x00", None, True],
        ),
        (WRITE, {"action": "correct", **CAS}, "topic", ["x" * 129, "x\n", "x\u202e", None, True]),
    ],
)
def test_bounds(tool, arguments, field, values):
    for value in values:
        with pytest.raises(MemoryError, match="invalid_request"):
            normalize_memory_tool_request(tool, {**arguments, field: value})


@pytest.mark.parametrize(
    "value",
    ["invented", ID.upper(), ID.replace("-", ""), "00000000-0000-1000-8000-000000000000", True],
)
@pytest.mark.parametrize(
    "arguments,field", [({"action": "show"}, "record_id"), ({"action": "list"}, "after")]
)
def test_canonical_uuid4_required(value, arguments, field):
    with pytest.raises(MemoryError, match="invalid_request"):
        normalize_memory_tool_request(READ, {**arguments, field: value})


@pytest.mark.parametrize(
    "schema,name,actions,required",
    [
        (
            PERSONAL_MEMORY_READ_SCHEMA,
            READ,
            ["list", "show", "search", "search_terms", "recall"],
            ["action"],
        ),
        (
            PERSONAL_MEMORY_WRITE_SCHEMA,
            WRITE,
            ["remember", "correct", "forget"],
            ["action", "request_id"],
        ),
    ],
)
def test_closed_flat_json_schema(schema, name, actions, required):
    assert json.loads(json.dumps(schema)) == schema
    assert schema["name"] == name
    parameters = schema["parameters"]
    assert parameters["type"] == "object"
    assert parameters["additionalProperties"] is False
    assert parameters["required"] == required
    assert parameters["properties"]["action"]["enum"] == actions
    assert (
        not {"owner", "profile", "source", "session", "approved"} & parameters["properties"].keys()
    )
    assert all("properties" not in prop for prop in parameters["properties"].values())
    for phrase in ("configured model", "per-instruction intent", "No external action"):
        assert phrase in schema["description"]


def test_schema_bounds_and_receipt_guidance():
    read = PERSONAL_MEMORY_READ_SCHEMA["parameters"]["properties"]
    write = PERSONAL_MEMORY_WRITE_SCHEMA["parameters"]["properties"]
    assert read["limit"]["maximum"] == 50
    assert read["query"]["maxLength"] == 128
    assert write["content"]["maxLength"] == 2048
    assert write["topic"]["maxLength"] == 128
    assert write["expected_revision"]["maximum"] == 2**63 - 2
    for phrase in (
        "explicitly requested",
        "do not infer enduring preferences",
        "metadata-only",
        "read back",
        "Forgotten IDs never",
        "not current state",
    ):
        assert phrase in PERSONAL_MEMORY_WRITE_SCHEMA["description"]


@pytest.mark.parametrize(
    "terms",
    [
        None,
        "北京",
        [],
        [""],
        [" "],
        ["北京", "北京"],
        [True],
        ["x" * 129],
        ["x\n"],
        [f"term{i}" for i in range(9)],
    ],
)
def test_search_terms_rejects_invalid_term_lists(terms):
    with pytest.raises(MemoryError, match="invalid_request"):
        normalize_memory_tool_request(READ, {"action": "search_terms", "terms": terms})


def test_search_terms_schema_documents_bounded_distinct_literal_terms():
    field = PERSONAL_MEMORY_READ_SCHEMA["parameters"]["properties"]["terms"]
    assert field["type"] == "array"
    assert field["minItems"] == 1 and field["maxItems"] == 8 and field["uniqueItems"]
    assert field["items"] == {"type": "string", "minLength": 1, "maxLength": 128}
    assert "literal" in field["description"]
