"""Validate a local route registry and project only bounded diagnostic facts."""

import re
from datetime import UTC, datetime
from typing import Any, TypeGuard, cast

from . import HERMES_BASELINE

PLUGIN_ID = "hermes-personal-agent"
REGISTRY_VERSION = "personal.routing.registry.v1"

_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
_MODEL = re.compile(r"[A-Za-z0-9_.-]+(?:[/:][A-Za-z0-9_.-]+)*")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_BINDING_FIELDS = {
    "provider",
    "model",
    "account_ref",
    "api_mode",
    "transport",
    "endpoint_ref",
    "recipient_scope_ref",
    "data_scope_ref",
}
_TRANSPORTS = {"in_process", "local_process", "local_http", "https"}
_SOURCES = {
    "provider_documentation",
    "account_configuration",
    "native_contract_test",
    "operator_observation",
}
_BOOLEAN_FACTS = (
    "text",
    "image_input",
    "audio_input",
    "tool_calling",
    "structured_output",
    "reasoning_effort",
    "reasoning_token_budget",
    "reasoning_toggle",
    "reasoning_disable",
    "service_tiers",
    "cache_metering",
    "usage_metering",
    "pricing",
)
_LIMIT_FACTS = ("context_tokens", "output_tokens")
_VALUE_FACTS = (*_LIMIT_FACTS, "health")
_FACTS = (*_BOOLEAN_FACTS, *_VALUE_FACTS)
_FACTS_SET = frozenset(_FACTS)
_HEALTH_VALUES = {"available", "degraded", "unavailable"}
_MAX_ROUTES = 64
_MAX_EVIDENCE = 64
_MAX_TOKENS = 1_000_000_000


class _InvalidRegistry(ValueError):
    """The exception message is a fixed reason code."""


def _report() -> dict[str, Any]:
    return {
        "schema_version": "personal.routing.inventory.v1",
        "scope": "saved_user_config_only",
        "target_hermes_commit": HERMES_BASELINE,
        "runtime_commit_verified": False,
        "execution_authorized": False,
        "shadow_ready": False,
        "automatic_routing_ready": False,
        "plugin_live_routing_enabled": False,
    }


def inventory_failure(reason: str) -> dict[str, Any]:
    return {**_report(), "status": "blocked", "reason": reason}


def _label(value: object) -> TypeGuard[str]:
    return type(value) is str and _LABEL.fullmatch(value) is not None


def _mapping(value: object, keys: set[str], reason: str) -> dict[str, Any]:
    if type(value) is not dict or value.keys() != keys:
        raise _InvalidRegistry(reason)
    return cast("dict[str, Any]", value)


def _registry_settings(raw: object) -> dict[str, Any]:
    for key in ("plugins", "entries", PLUGIN_ID, "settings"):
        if type(raw) is not dict:
            raise _InvalidRegistry("invalid_saved_configuration")
        raw = raw.get(key, {})
    if type(raw) is not dict:
        raise _InvalidRegistry("invalid_saved_configuration")
    return cast("dict[str, Any]", raw)


def _check_binding(raw: object) -> None:
    binding = _mapping(raw, _BINDING_FIELDS, "invalid_route_binding")
    model = binding["model"]
    transport = binding["transport"]
    if (
        type(model) is not str
        or len(model) > 128
        or _MODEL.fullmatch(model) is None
        or type(transport) is not str
        or transport not in _TRANSPORTS
        or any(not _label(binding[key]) for key in _BINDING_FIELDS - {"model", "transport"})
    ):
        raise _InvalidRegistry("invalid_route_binding")


def _time(value: object) -> datetime:
    if type(value) is str and _TIMESTAMP.fullmatch(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    raise _InvalidRegistry("invalid_capability_evidence")


def _evidence(raw: object, now: datetime) -> dict[str, dict[str, str]]:
    reason = "invalid_capability_evidence"
    if type(raw) is not dict or len(raw) > _MAX_EVIDENCE:
        raise _InvalidRegistry(reason)
    projected = {}
    for reference, item in raw.items():
        if not _label(reference):
            raise _InvalidRegistry(reason)
        record = _mapping(item, {"source", "observed_at", "valid_until"}, reason)
        source = record["source"]
        if type(source) is not str or source not in _SOURCES:
            raise _InvalidRegistry(reason)
        observed, expiry = _time(record["observed_at"]), _time(record["valid_until"])
        if observed >= expiry:
            raise _InvalidRegistry(reason)
        freshness = "current"
        if now < observed:
            freshness = "not_yet_observed"
        elif now >= expiry:
            freshness = "expired"
        projected[reference] = {"source": source, "freshness": freshness}
    return projected


def _observation(key: str, raw: object, evidence: dict[str, dict[str, str]]) -> dict[str, Any]:
    reason = "invalid_route_capability"
    if type(raw) is not dict:
        raise _InvalidRegistry(reason)
    state = raw.get("state")
    if type(state) is not str:
        raise _InvalidRegistry(reason)
    if state == "unknown":
        _mapping(raw, {"state"}, reason)
        return {"state": "unknown", "freshness": "no_evidence"}
    if state not in ("supported", "unsupported"):
        raise _InvalidRegistry(reason)
    has_value = state == "supported" and key in _VALUE_FACTS
    expected = {"state", "evidence", "value"} if has_value else {"state", "evidence"}
    observation = _mapping(raw, expected, reason)
    reference = observation["evidence"]
    if type(reference) is not str or reference not in evidence:
        raise _InvalidRegistry("invalid_capability_evidence")
    if has_value:
        value = observation["value"]
        if key == "health":
            if type(value) is not str or value not in _HEALTH_VALUES:
                raise _InvalidRegistry(reason)
        elif type(value) is not int or not 0 < value <= _MAX_TOKENS:
            raise _InvalidRegistry(reason)
    fact = evidence[reference]
    if fact["freshness"] != "current":
        return {**fact, "state": "unknown"}
    result = {**fact, "state": state}
    if has_value:
        result["value"] = observation["value"]
    return result


def _route(raw: object, now: datetime) -> dict[str, Any]:
    row = _mapping(raw, {"binding", "evidence", "capabilities"}, "invalid_route_record")
    _check_binding(row["binding"])
    evidence = _evidence(row["evidence"], now)
    capabilities = row["capabilities"]
    if type(capabilities) is not dict or not capabilities.keys() <= _FACTS_SET:
        raise _InvalidRegistry("invalid_route_capability")
    return {
        key: _observation(key, capabilities.get(key, {"state": "unknown"}), evidence)
        for key in _FACTS
    }


def inspect_saved_inventory(
    raw: object, route_id: str | None, *, now: datetime | None = None
) -> dict[str, Any]:
    """Inspect the whole saved registry with one observation time and exact lookup."""
    if route_id is not None and not _label(route_id):
        return inventory_failure("invalid_route_id")
    try:
        settings = _registry_settings(raw)
        configured = "routing_inventory" in settings
        routes: dict[str, Any] = {}
        if configured:
            registry = _mapping(
                settings["routing_inventory"], {"schema_version", "routes"}, "invalid_registry"
            )
            if registry["schema_version"] != REGISTRY_VERSION:
                raise _InvalidRegistry("unsupported_registry_version")
            routes = registry["routes"]
            if type(routes) is not dict or len(routes) > _MAX_ROUTES:
                raise _InvalidRegistry("invalid_registry")
        observation_time = now if now is not None else datetime.now(UTC)
        selected = None
        for key, value in routes.items():
            if not _label(key):
                raise _InvalidRegistry("invalid_route_id")
            capabilities = _route(value, observation_time)
            if key == route_id:
                selected = capabilities
        if route_id is not None and selected is None:
            raise _InvalidRegistry("route_not_found")
    except _InvalidRegistry as exc:
        return inventory_failure(str(exc))
    return {
        **_report(),
        "status": "ok",
        "registry_status": "declared" if configured else "not_configured",
        "registry_version": REGISTRY_VERSION if configured else None,
        "route_count": len(routes),
        "selected_capabilities": selected,
    }
