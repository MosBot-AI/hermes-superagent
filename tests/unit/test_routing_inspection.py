"""Saved-config declarations do not authorize execution or expose config values."""

import argparse
import copy
import json

import pytest

from personal_agent.plugin import run_cli, setup_cli
from personal_agent.routing_inspection import inspect_saved_routing, inspection_failure


def config(**changes):
    return {
        "delegation": {
            "backend": "default",
            "provider": "private-provider",
            "model": "private-model",
            "reasoning_effort": "high",
            "fallback_providers": [],
            **changes,
        }
    }


def test_complete_saved_declarations_never_claim_a_qualified_live_baseline():
    raw = config()
    before = copy.deepcopy(raw)
    report = inspect_saved_routing(raw)
    assert raw == before
    assert report["status"] == "ok"
    assert report["saved_route_shape"] == "provider_and_model_declared"
    assert report["scope"] == "saved_user_config_only"
    assert report["runtime_commit_verified"] is False
    assert report["declarations"]["backend"] == "declared"
    assert report["saved_fallback_policy"] == "explicit_empty"
    assert report["saved_effort"] == {
        "declaration": "level_declared",
        "requested_effort": "high",
        "effective_wire_effort": None,
    }
    for name in (
        "shadow_ready",
        "automatic_routing_ready",
        "plugin_live_routing_enabled",
        "execution_authorized",
        "effective_session_observed",
    ):
        assert report[name] is False
    assert report["unverified"]
    assert "private" not in json.dumps(report)
    assert report == inspect_saved_routing(raw)
    report["unverified"].clear()
    assert inspect_saved_routing(raw)["unverified"]


@pytest.mark.parametrize(
    "changes,shape",
    [
        ({"provider": None}, "parent_dependent_uninspected"),
        ({"model": None}, "model_unspecified_or_unresolved"),
        ({"model": "${PRIVATE_MODEL}"}, "model_unspecified_or_unresolved"),
        ({"base_url": "https://private.example/key"}, "endpoint_and_model_declared"),
        ({"profile": "private-profile"}, "profile_dependent_uninspected"),
        ({"profile": "${PRIVATE_PROFILE}"}, "profile_dependent_uninspected"),
        ({"backend": "private-backend"}, "backend_defined_uninspected"),
        ({"backend": "${PRIVATE_BACKEND}"}, "backend_defined_uninspected"),
    ],
)
def test_route_shape_is_declarative_not_resolved(changes, shape):
    result = inspect_saved_routing(config(**changes))
    assert result["saved_route_shape"] == shape
    assert "private" not in json.dumps(result).lower()


@pytest.mark.parametrize("backend", [None, "", " ", "DEFAULT", " default "])
def test_default_backend_spellings(backend):
    assert inspect_saved_routing(config(backend=backend))["saved_backend"] == "default"


@pytest.mark.parametrize("value", [True, False, 1, [], {}, "x\nsecret", "x" * 4097])
@pytest.mark.parametrize(
    "field", ["backend", "provider", "model", "base_url", "api_mode", "profile"]
)
def test_malformed_route_fields_fail_without_echoing(field, value):
    result = inspect_saved_routing(config(**{field: value}))
    assert result == inspection_failure("invalid_saved_configuration")


@pytest.mark.parametrize(
    "raw", [None, [], True, "private", {"delegation": None}, {"delegation": []}]
)
def test_invalid_sections_are_not_silently_defaults(raw):
    assert inspect_saved_routing(raw) == inspection_failure("invalid_saved_configuration")


def test_missing_delegation_and_main_model_do_not_prove_worker_pins():
    result = inspect_saved_routing({"model": {"provider": "private", "default": "private"}})
    assert result["saved_backend"] == "default"
    assert result["saved_route_shape"] == "model_unspecified_or_unresolved"
    assert result["declarations"]["model"] == "absent"
    assert result["declarations"]["backend"] == "absent"
    assert result["saved_fallback_policy"] == "absent"


@pytest.mark.parametrize(
    "value,state",
    [
        (None, "null"),
        ([], "explicit_empty"),
        ([{"provider": "private"}], "entries_uninspected"),
        (False, "invalid"),
        ({"provider": "private"}, "invalid"),
        ("private", "invalid"),
    ],
)
def test_fallback_declaration_does_not_walk_or_validate_recipients(value, state):
    result = inspect_saved_routing(config(fallback_providers=value))
    assert result["saved_fallback_policy"] == state
    assert "effective_fallbacks" in result["unverified"]
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "value,state,requested",
    [
        (None, "unspecified", None),
        (True, "unspecified", None),
        (" ", "unspecified", None),
        (False, "disabled_declared", "none"),
        ("disabled", "disabled_declared", "none"),
        ("NONE", "disabled_declared", "none"),
        ("false", "disabled_declared", "none"),
        ("high", "level_declared", "high"),
        (" MAX ", "level_declared", "max"),
        ("${PRIVATE_EFFORT}", "unexpanded_reference", None),
        ({"enabled": False, "effort": "private"}, "mapping_uninspected", None),
        ("private-bespoke", "unrecognized", None),
        (1, "unrecognized", None),
        ([], "unrecognized", None),
    ],
)
def test_effort_keeps_requested_distinct_from_effective(value, state, requested):
    result = inspect_saved_routing(config(reasoning_effort=value))
    assert result["saved_effort"] == {
        "declaration": state,
        "requested_effort": requested,
        "effective_wire_effort": None,
    }
    assert "private" not in json.dumps(result).lower()


def test_native_ignored_tier_override_and_timeout_warnings_are_explicit():
    result = inspect_saved_routing(
        config(
            service_tier="fast",
            child_timeout_seconds=60,
            request_overrides={"secret": "private"},
            api_key="private",
        )
    )
    assert {
        "default_backend_ignores_delegation_service_tier",
        "child_timeout_is_inactivity_not_total_deadline",
        "request_overrides_not_inspected",
        "inline_credential_field_present_not_inspected",
    } <= set(result["notes"])
    assert "private" not in json.dumps(result)


def test_unknown_fields_and_cyclic_secret_values_are_not_traversed():
    private = {}
    private["secret"] = private
    raw = config(request_overrides=private)
    raw["api_key"] = private
    raw["delegation"]["backends"] = private
    raw["delegation"]["unrecognized_private_field"] = private
    assert inspect_saved_routing(raw)["status"] == "ok"


@pytest.mark.parametrize(
    "argv",
    [
        ["routing"],
        ["routing", "enable"],
        ["routing", "switch"],
        ["routing", "inspect", "--profile", "private"],
        ["routing", "inspect", "--model", "private"],
        ["routing", "inspect", "--apply"],
    ],
)
def test_parser_offers_no_activation_or_alternate_profile(argv):
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    with pytest.raises(SystemExit) as error:
        parser.parse_args(argv)
    assert error.value.code == 2


def test_unbound_generic_cli_does_not_silently_read_a_profile(capsys):
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    assert run_cli(parser.parse_args(["routing", "inspect"])) == 1
    assert json.loads(capsys.readouterr().out) == inspection_failure("host_inspection_unavailable")


def test_failure_reasons_are_closed_and_never_echo_arbitrary_errors():
    with pytest.raises(ValueError, match="unsupported inspection failure"):
        inspection_failure("private-exception-body")


def test_generic_status_advertises_inspection_without_reading_configuration():
    from personal_agent.status import build_status

    result = build_status()
    assert result["routing"]["saved_config_inspection_cli_implemented"] is True
    assert result["routing"]["effective_session_observed"] is False
    assert result["routing"]["plugin_live_routing_enabled"] is False
    assert result["capabilities"]["worker_model_routing"] is False
