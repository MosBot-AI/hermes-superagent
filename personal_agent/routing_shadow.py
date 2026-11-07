"""Pure offline routing-fixture evaluation, not a Hermes backend or admission API.

All inputs are caller assertions for simulation, not trusted runtime context.
This module never reads config, resolves credentials, creates routes or workers,
writes audit files, or calls a model. A passing report cannot authorize execution.
"""

import re
from typing import Any

_EFFORTS = frozenset(
    {"provider_default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_TIERS = frozenset({"normal", "fast", "ultrafast"})
_CAPABILITIES = frozenset({"text", "image", "audio", "tool_calling", "structured_output"})
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "policy_id",
        "capability_version",
        "baseline_route_id",
        "candidates",
        "constraints",
        "preference_order",
    }
)
_CANDIDATE_FIELDS = frozenset(
    {
        "route_id",
        "provider",
        "model",
        "endpoint_id",
        "api_mode",
        "configured",
        "available",
        "recipient_ids",
        "data_scopes",
        "region",
        "local",
        "capabilities",
        "context_limit",
        "output_limit",
        "effort",
        "supported_efforts",
        "service_tier",
        "supported_service_tiers",
        "evidence_id",
    }
)
_CONSTRAINT_FIELDS = frozenset(
    {
        "permitted_route_ids",
        "allowed_recipient_ids",
        "data_scope",
        "required_capabilities",
        "input_tokens",
        "output_tokens",
        "local_only",
        "region",
        "pin_provider",
        "pin_model",
        "pin_route_id",
        "pin_effort",
        "service_tier",
        "hard_budget",
        "hard_deadline",
    }
)


class ShadowFixtureError(ValueError):
    """Invalid fixture. Deliberately does not echo user-controlled values."""


def _fail() -> None:
    raise ShadowFixtureError("invalid_shadow_fixture")


def _object(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or value.keys() != fields:
        _fail()
    return value


def _identifier(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value) is None:
        _fail()


def _names(value: Any, *, nullable: bool = False, choices: frozenset[str] | None = None) -> None:
    if nullable and value is None:
        return
    if type(value) is not list or len(value) > 32:
        _fail()
    for item in value:
        _identifier(item)
    if len(value) != len(set(value)) or (choices is not None and not set(value) <= choices):
        _fail()


def _bool(value: Any, *, nullable: bool = False) -> None:
    if type(value) is not bool and not (nullable and value is None):
        _fail()


def _tokens(value: Any, *, nullable: bool = False, positive: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not int or not int(positive) <= value <= 2**31 - 1:
        _fail()


def _enum(value: Any, choices: frozenset[str], *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or value not in choices:
        _fail()


def _validate(raw: object) -> dict[str, Any]:
    fixture = _object(raw, _ROOT_FIELDS)
    if type(fixture["schema_version"]) is not int or fixture["schema_version"] != 1:
        _fail()
    for key in ("policy_id", "capability_version", "baseline_route_id"):
        _identifier(fixture[key])
    candidates = fixture["candidates"]
    if type(candidates) is not list or not 1 <= len(candidates) <= 32:
        _fail()
    for value in candidates:
        candidate = _object(value, _CANDIDATE_FIELDS)
        for key in ("route_id", "provider", "model", "endpoint_id", "api_mode", "evidence_id"):
            _identifier(candidate[key])
        _identifier(candidate["region"], nullable=True)
        for key in ("configured", "available", "local"):
            _bool(candidate[key], nullable=True)
        for key in ("recipient_ids", "data_scopes"):
            _names(candidate[key], nullable=True)
        _names(candidate["capabilities"], nullable=True, choices=_CAPABILITIES)
        for key in ("context_limit", "output_limit"):
            _tokens(candidate[key], nullable=True, positive=True)
        _enum(candidate["effort"], _EFFORTS)
        _names(candidate["supported_efforts"], nullable=True, choices=_EFFORTS)
        _enum(candidate["service_tier"], _TIERS)
        _names(candidate["supported_service_tiers"], nullable=True, choices=_TIERS)
    ids = [candidate["route_id"] for candidate in candidates]
    if len(ids) != len(set(ids)):
        _fail()
    _names(fixture["preference_order"])
    if set(fixture["preference_order"]) != set(ids):
        _fail()
    constraints = _object(fixture["constraints"], _CONSTRAINT_FIELDS)
    for key in ("permitted_route_ids", "allowed_recipient_ids"):
        _names(constraints[key])
    _names(constraints["required_capabilities"], choices=_CAPABILITIES)
    _identifier(constraints["data_scope"])
    for key in ("region", "pin_provider", "pin_model", "pin_route_id"):
        _identifier(constraints[key], nullable=True)
    _enum(constraints["pin_effort"], _EFFORTS, nullable=True)
    _enum(constraints["service_tier"], _TIERS)
    for key in ("input_tokens", "output_tokens"):
        _tokens(constraints[key], positive=True)
    for key in ("local_only", "hard_budget", "hard_deadline"):
        _bool(constraints[key])
    return fixture


def _exclusions(candidate: dict[str, Any], constraints: dict[str, Any]) -> list[str]:
    reasons = []
    if candidate["route_id"] not in constraints["permitted_route_ids"]:
        reasons.append("route_not_permitted")
    for key in ("configured", "available"):
        if candidate[key] is not True:
            reasons.append(f"route_{key}_unknown" if candidate[key] is None else f"route_not_{key}")
    recipients = candidate["recipient_ids"]
    if recipients is None:
        reasons.append("recipients_unknown")
    elif not set(recipients) <= set(constraints["allowed_recipient_ids"]):
        reasons.append("recipient_not_permitted")
    elif not recipients and candidate["local"] is not True:
        reasons.append("remote_recipients_missing")
    scopes = candidate["data_scopes"]
    if scopes is None:
        reasons.append("data_scope_unknown")
    elif constraints["data_scope"] not in scopes:
        reasons.append("data_scope_not_permitted")
    if constraints["local_only"] and (candidate["local"] is not True or recipients != []):
        reasons.append("locality_unverified")
    if constraints["region"] is not None and candidate["region"] != constraints["region"]:
        reasons.append("region_mismatch_or_unknown")
    capabilities = candidate["capabilities"]
    if capabilities is None:
        reasons.append("capabilities_unknown")
    elif not set(constraints["required_capabilities"]) <= set(capabilities):
        reasons.append("capability_missing")
    # Conservative total window requirement, including reserved output. These
    # asserted limits are fixture evidence, not the provider's actual encoder.
    for key, minimum in (
        ("context_limit", constraints["input_tokens"] + constraints["output_tokens"]),
        ("output_limit", constraints["output_tokens"]),
    ):
        if candidate[key] is None:
            reasons.append(f"{key}_unknown")
        elif candidate[key] < minimum:
            reasons.append(f"{key}_exceeded")
    for key in ("provider", "model", "route_id", "effort"):
        pin = constraints[f"pin_{key}"]
        if pin is not None and candidate[key] != pin:
            reasons.append(f"{key}_pin_mismatch")
    supported = candidate["supported_efforts"]
    if supported is None:
        reasons.append("effort_support_unknown")
    elif candidate["effort"] not in supported:
        reasons.append("effort_unsupported")
    if candidate["service_tier"] != constraints["service_tier"]:
        reasons.append("service_tier_mismatch")
    tiers = candidate["supported_service_tiers"]
    if tiers is None:
        reasons.append("service_tier_support_unknown")
    elif candidate["service_tier"] not in tiers:
        reasons.append("service_tier_unsupported")
    for field in ("budget", "deadline"):
        if constraints[f"hard_{field}"]:
            reasons.append(f"hard_{field}_enforcement_unavailable")
    return reasons


def evaluate_shadow_fixture(raw: object) -> dict[str, Any]:
    """Filter before deterministic fixture-defined ranking, with no side effects.

    The baseline must pass the same checks; otherwise no suggestion is returned.
    IDs in reports must be non-sensitive opaque references supplied by the caller.
    Reports intentionally omit prompts, provider/model/endpoint details and pins.
    Effective wire effort, costs, actual route and quality remain unobserved.
    """
    fixture = _validate(raw)
    constraints = fixture["constraints"]
    candidates = sorted(fixture["candidates"], key=lambda item: item["route_id"])
    checks = [
        {"route_id": candidate["route_id"], "reasons": _exclusions(candidate, constraints)}
        for candidate in candidates
    ]
    eligible = {check["route_id"] for check in checks if not check["reasons"]}
    baseline = fixture["baseline_route_id"]
    baseline_valid = baseline in eligible
    suggested = (
        next((route for route in fixture["preference_order"] if route in eligible), None)
        if baseline_valid
        else None
    )
    return {
        "schema_version": 1,
        "mode": "offline_fixture",
        "status": "advisory" if baseline_valid else "blocked",
        "reason": "qualified_fixture_baseline" if baseline_valid else "baseline_not_qualified",
        "policy_id": fixture["policy_id"],
        "capability_version": fixture["capability_version"],
        "baseline_route_id": baseline,
        "suggested_route_id": suggested,
        "suggested_requested_effort": next(
            (item["effort"] for item in candidates if item["route_id"] == suggested), None
        ),
        "candidate_checks": checks,
        "execution_authorized": False,
        "live_routing_enabled": False,
        "actual_route": None,
        "effective_wire_effort": None,
        "actual_usage": None,
        "actual_cost": None,
        "quality_validated": False,
        "fallback_plan": [],
    }
