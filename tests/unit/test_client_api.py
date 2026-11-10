"""Shared wire conformance, not a claim of HTTP/native-mobile acceptance."""

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from personal_agent.client_api import build_client_capabilities
from personal_agent.status import build_status

ROOT = Path(__file__).resolve().parents[2] / "contracts" / "personal-api"
SCHEMA = json.loads((ROOT / "schema.json").read_text())
FIXTURES = json.loads((ROOT / "fixtures.json").read_text())


def validator(name):
    return jsonschema.Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{name}"})


def test_schema_and_pinned_artifacts():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["contract_version"] == "0.1.0"
    assert manifest["authority"] == "MosBot-AI/hermes-superagent"
    assert set(manifest["files"]) == {"schema.json", "openapi.json", "fixtures.json"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    api = json.loads((ROOT / "openapi.json").read_text())
    assert api["info"]["version"] == manifest["contract_version"]
    assert set(api["paths"]) == {"/capabilities", "/tasks"}


@pytest.mark.parametrize("case", FIXTURES["valid"])
def test_shared_positive_fixture(case):
    validator(case["schema"]).validate(case["value"])


@pytest.mark.parametrize("case", FIXTURES["invalid"])
def test_shared_negative_fixture(case):
    with pytest.raises(jsonschema.ValidationError):
        validator(case["schema"]).validate(case["value"])


def test_hermes_metadata_matches_shared_fixture_without_io():
    assert build_client_capabilities() == FIXTURES["valid"][0]["value"]
    assert build_status()["client_api"] == build_client_capabilities()


def test_local_permissions_cannot_enable_remote_client_api():
    result = build_status(mode="local_tasks", local_conversation=True, local_model_tools=True)
    assert result["client_api"] == FIXTURES["valid"][0]["value"]


def test_diagnostics_returns_fresh_data_and_no_authentication_override():
    first = build_client_capabilities()
    first["data"]["capabilities"].clear()
    assert build_client_capabilities() == FIXTURES["valid"][0]["value"]
    with pytest.raises(TypeError):
        build_client_capabilities(authenticated=True)
