"""Strict registry data and redacted, time-bounded projections."""

import json
from datetime import UTC, datetime

import pytest

from personal_agent.routing_inventory import REGISTRY_VERSION, inspect_saved_inventory

ROUTE = "private-route"
NOW = datetime(2026, 11, 16, 18, tzinfo=UTC)


@pytest.fixture
def saved():
    registry = {
        "schema_version": REGISTRY_VERSION,
        "routes": {
            ROUTE: {
                "binding": {
                    "provider": "private-provider",
                    "model": "private/model:v1",
                    "account_ref": "private-account",
                    "api_mode": "private-mode",
                    "transport": "https",
                    "endpoint_ref": "private-endpoint",
                    "recipient_scope_ref": "private-recipient",
                    "data_scope_ref": "private-data",
                },
                "evidence": {
                    "private-current": {
                        "source": "account_configuration",
                        "observed_at": "2026-11-16T18:00:00Z",
                        "valid_until": "2026-11-17T18:00:00Z",
                    },
                    "private-expired": {
                        "source": "operator_observation",
                        "observed_at": "2026-11-16T17:59:59Z",
                        "valid_until": "2026-11-16T18:00:00Z",
                    },
                    "private-future": {
                        "source": "provider_documentation",
                        "observed_at": "2026-11-16T18:00:01Z",
                        "valid_until": "2026-11-17T18:00:00Z",
                    },
                },
                "capabilities": {
                    "text": {"state": "supported", "evidence": "private-current"},
                    "tool_calling": {"state": "unsupported", "evidence": "private-current"},
                    "image_input": {"state": "unknown"},
                    "context_tokens": {
                        "state": "supported",
                        "evidence": "private-current",
                        "value": 128000,
                    },
                    "output_tokens": {
                        "state": "supported",
                        "evidence": "private-expired",
                        "value": 4000,
                    },
                    "health": {
                        "state": "supported",
                        "evidence": "private-current",
                        "value": "unavailable",
                    },
                    "pricing": {"state": "supported", "evidence": "private-future"},
                    "reasoning_disable": {"state": "unsupported", "evidence": "private-expired"},
                },
            },
        },
    }
    raw = {
        "plugins": {
            "entries": {
                "hermes-personal-agent": {
                    "settings": {"routing_inventory": registry},
                }
            }
        }
    }
    return raw, registry


def test_observation_boundaries_and_route_redaction(saved):
    raw, _ = saved
    report = inspect_saved_inventory(raw, ROUTE, now=NOW)
    assert report["status"] == "ok"
    assert report["route_count"] == 1
    assert report["registry_status"] == "declared"
    assert report["registry_version"] == REGISTRY_VERSION
    assert report["execution_authorized"] is False
    assert report["shadow_ready"] is False
    assert report["runtime_commit_verified"] is False
    facts = report["selected_capabilities"]
    assert facts["text"] == {
        "state": "supported",
        "freshness": "current",
        "source": "account_configuration",
    }
    assert facts["tool_calling"]["state"] == "unsupported"
    assert facts["context_tokens"]["value"] == 128000
    assert facts["output_tokens"] == {
        "state": "unknown",
        "freshness": "expired",
        "source": "operator_observation",
    }
    assert facts["reasoning_disable"]["state"] == "unknown"
    assert facts["health"]["value"] == "unavailable"
    assert facts["pricing"] == {
        "state": "unknown",
        "freshness": "not_yet_observed",
        "source": "provider_documentation",
    }
    assert (
        facts["image_input"]
        == facts["audio_input"]
        == {
            "state": "unknown",
            "freshness": "no_evidence",
        }
    )
    assert "private" not in json.dumps(report)


def test_discovery_without_route_and_exact_lookup(saved):
    raw, _ = saved
    result = inspect_saved_inventory(raw, None, now=NOW)
    assert result["route_count"] == 1
    assert result["selected_capabilities"] is None
    assert inspect_saved_inventory({}, None, now=NOW)["registry_status"] == "not_configured"
    assert inspect_saved_inventory(raw, ROUTE.upper(), now=NOW)["reason"] == "route_not_found"
    assert (
        inspect_saved_inventory(raw, "https://private-url", now=NOW)["reason"] == "invalid_route_id"
    )


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("schema_version",), "personal.routing.registry.v2", "unsupported_registry_version"),
        (
            ("routes", ROUTE, "binding", "endpoint_ref"),
            "https://private-host",
            "invalid_route_binding",
        ),
        (("routes", ROUTE, "binding", "api_key"), "private-key", "invalid_route_binding"),
        (
            ("routes", ROUTE, "binding", "account_ref"),
            "${PRIVATE_ACCOUNT}",
            "invalid_route_binding",
        ),
        (("routes", ROUTE, "capabilities", "unexpected"), {}, "invalid_route_capability"),
        (
            ("routes", ROUTE, "capabilities", "context_tokens", "value"),
            True,
            "invalid_route_capability",
        ),
        (
            ("routes", ROUTE, "capabilities", "health", "value"),
            "private-host",
            "invalid_route_capability",
        ),
        (
            ("routes", ROUTE, "capabilities", "image_input", "evidence"),
            "private-current",
            "invalid_route_capability",
        ),
        (
            ("routes", ROUTE, "capabilities", "text", "evidence"),
            "private-missing",
            "invalid_capability_evidence",
        ),
        (
            ("routes", ROUTE, "evidence", "private-current", "valid_until"),
            "2026-11-16T18:00:00Z",
            "invalid_capability_evidence",
        ),
        (
            ("routes", ROUTE, "evidence", "private-current", "observed_at"),
            "2026-02-30T18:00:00Z",
            "invalid_capability_evidence",
        ),
    ],
)
def test_invalid_registry_refuses_without_echoing_data(saved, path, value, reason):
    raw, registry = saved
    parent = registry
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = value
    result = inspect_saved_inventory(raw, ROUTE, now=NOW)
    assert (result["status"], result["reason"]) == ("blocked", reason)
    assert result["execution_authorized"] is False
    assert "private" not in json.dumps(result)


def test_atomic_validation_refuses_evidence_from_another_route(saved):
    raw, registry = saved
    route = registry["routes"][ROUTE]
    registry["routes"]["other"] = {**route, "evidence": {}}
    result = inspect_saved_inventory(raw, ROUTE, now=NOW)
    assert result["reason"] == "invalid_capability_evidence"
    assert "selected_capabilities" not in result
