"""Identifier-free inspection of saved delegation declarations, not effective routing.

The report contains only fixed states, reason codes and recognized effort enums,
not user-supplied names, URLs, keys, override values, hashes or exception details.
It does not call a backend, resolve a model, grant permission, or certify a static
or shadow execution baseline.
"""

from typing import Any

from . import HERMES_BASELINE

_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
_TEXT_FIELDS = ("provider", "model", "base_url", "api_mode", "profile")
_UNKNOWN = (
    "runtime_compatibility",
    "effective_session_route",
    "selected_backend_availability",
    "provider_endpoint_identity",
    "model_identifier_resolution",
    "credential_validity",
    "data_recipients_and_scope",
    "model_capabilities",
    "effective_wire_effort",
    "effective_service_tier",
    "effective_fallbacks",
    "usage_and_cost",
    "current_authorization",
    "budget_and_cancellation_enforcement",
)


def inspection_failure(reason: str) -> dict[str, Any]:
    """Construct a bounded failure without any exception or configuration values."""
    if reason not in {
        "invalid_saved_configuration",
        "saved_configuration_unreadable",
        "profile_context_changed",
        "inspector_closed",
        "unsupported_runtime",
        "unsupported_config_backend",
        "host_inspection_unavailable",
    }:
        raise ValueError("unsupported inspection failure")
    return {
        "schema_version": "personal.routing.inspection.v1",
        "status": "blocked",
        "reason": reason,
        "scope": "saved_user_config_only",
        "target_hermes_commit": HERMES_BASELINE,
        "runtime_commit_verified": False,
        "execution_authorized": False,
        "shadow_ready": False,
        "automatic_routing_ready": False,
        "plugin_live_routing_enabled": False,
    }


def _text_state(value: Any) -> str:
    if value is None or (type(value) is str and not value.strip()):
        return "absent"
    if type(value) is not str or len(value) > 4096 or any(ord(char) < 32 for char in value):
        return "invalid"
    if "$" in value:
        return "unexpanded_reference"
    return "declared"


def _effort(value: Any) -> dict[str, Any]:
    # This recognizes documented forms only, without claiming encoder support.
    # A bespoke mapping stays uninspected, including an enabled/disabled toggle.
    if value is None or value is True or (type(value) is str and not value.strip()):
        state, requested = "unspecified", None
    elif value is False:
        state, requested = "disabled_declared", "none"
    elif type(value) is dict:
        state, requested = "mapping_uninspected", None
    elif type(value) is str and value.strip().lower() in {"none", "false", "disabled"}:
        state, requested = "disabled_declared", "none"
    elif type(value) is str and value.strip().lower() in _EFFORTS:
        state, requested = "level_declared", value.strip().lower()
    elif type(value) is str and "$" in value:
        state, requested = "unexpanded_reference", None
    else:
        state, requested = "unrecognized", None
    return {"declaration": state, "requested_effort": requested, "effective_wire_effort": None}


def inspect_saved_routing(raw: object) -> dict[str, Any]:
    """Describe only literal saved declarations. Never echo opaque config values.

    No defaults, managed overlays, environment expansion, profile contents, live
    backend/session state or registry are consulted. Unknown keys are not copied
    or recursively walked. The caller must not treat this as effective config.
    """
    if type(raw) is not dict:
        return inspection_failure("invalid_saved_configuration")
    section = raw.get("delegation", {})
    if type(section) is not dict:
        return inspection_failure("invalid_saved_configuration")
    backend = section.get("backend")
    backend_state = _text_state(backend)
    if backend_state == "invalid":
        return inspection_failure("invalid_saved_configuration")
    default = backend_state == "absent" or (
        type(backend) is str and backend.strip().lower() == "default"
    )
    fields = {key: _text_state(section.get(key)) for key in _TEXT_FIELDS}
    if "invalid" in fields.values():
        return inspection_failure("invalid_saved_configuration")
    notes = []
    if not default:
        route = "backend_defined_uninspected"
        notes.append("selected_backend_not_evaluated")
    elif fields["profile"] != "absent":
        route = "profile_dependent_uninspected"
        notes.append("profile_route_owns_route_settings")
    elif fields["model"] != "declared":
        route = "model_unspecified_or_unresolved"
        notes.append("worker_model_not_explicitly_resolved")
    elif fields["base_url"] == "declared":
        route = "endpoint_and_model_declared"
        notes.append("endpoint_declaration_and_credentials_unverified")
    elif fields["provider"] == "declared":
        route = "provider_and_model_declared"
        notes.append("provider_model_and_endpoint_unverified")
    else:
        route = "parent_dependent_uninspected"
        notes.append("parent_provider_or_endpoint_not_observed")
    if "unexpanded_reference" in fields.values() or backend_state == "unexpanded_reference":
        notes.append("environment_references_not_expanded")
    fallback = section.get("fallback_providers")
    if "fallback_providers" not in section:
        fallback_state = "absent"
    elif fallback is None:
        fallback_state = "null"
    elif type(fallback) is not list:
        fallback_state = "invalid"
    else:
        fallback_state = "entries_uninspected" if fallback else "explicit_empty"
    if fallback_state != "explicit_empty":
        notes.append("fallback_policy_not_explicitly_empty")
    if not default or fields["profile"] != "absent":
        notes.append("backend_or_profile_may_replace_delegation_fields")
    if "request_overrides" in section:
        notes.append("request_overrides_not_inspected")
    if "service_tier" in section:
        notes.append(
            "default_backend_ignores_delegation_service_tier"
            if default
            else "backend_service_tier_semantics_uninspected"
        )
    if "child_timeout_seconds" in section:
        notes.append("child_timeout_is_inactivity_not_total_deadline")
    if "api_key" in section:
        notes.append("inline_credential_field_present_not_inspected")
    effort = _effort(section.get("reasoning_effort"))
    if effort["declaration"] in {"unspecified", "unrecognized", "mapping_uninspected"}:
        notes.append("requested_effort_not_a_verified_exact_pin")
    notes.append("saved_configuration_does_not_observe_pinned_sessions")
    return {
        "schema_version": "personal.routing.inspection.v1",
        "status": "ok",
        "scope": "saved_user_config_only",
        "target_hermes_commit": HERMES_BASELINE,
        "runtime_commit_verified": False,
        "saved_backend": "default" if default else "other_or_unresolved",
        "saved_route_shape": route,
        "declarations": {"backend": backend_state, **fields},
        "saved_effort": effort,
        "saved_fallback_policy": fallback_state,
        "notes": notes,
        "unverified": list(_UNKNOWN),
        "execution_authorized": False,
        "shadow_ready": False,
        "automatic_routing_ready": False,
        "plugin_live_routing_enabled": False,
        "effective_session_observed": False,
    }
