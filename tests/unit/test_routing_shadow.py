"""Synthetic policy/negative fixtures. No actual provider or model is invoked."""

import copy
import json

import pytest

from personal_agent.routing_shadow import ShadowFixtureError, evaluate_shadow_fixture


def candidate(route_id="baseline", **changes):
    return {
        "route_id": route_id,
        "provider": "fixture-provider",
        "model": "fixture-model",
        "endpoint_id": "endpoint-v1",
        "api_mode": "fixture-api",
        "configured": True,
        "available": True,
        "recipient_ids": ["fixture-recipient"],
        "data_scopes": ["synthetic"],
        "region": "fixture-region",
        "local": False,
        "capabilities": ["text", "tool_calling", "structured_output"],
        "context_limit": 8192,
        "output_limit": 2048,
        "effort": "high",
        "supported_efforts": ["none", "low", "high"],
        "service_tier": "normal",
        "supported_service_tiers": ["normal"],
        "evidence_id": "synthetic-evidence-v1",
        **changes,
    }


def fixture():
    return {
        "schema_version": 1,
        "policy_id": "synthetic-policy-v1",
        "capability_version": "synthetic-caps-v1",
        "baseline_route_id": "baseline",
        "candidates": [candidate(), candidate("preferred")],
        "preference_order": ["preferred", "baseline"],
        "constraints": {
            "permitted_route_ids": ["baseline", "preferred"],
            "allowed_recipient_ids": ["fixture-recipient"],
            "data_scope": "synthetic",
            "required_capabilities": ["text", "tool_calling", "structured_output"],
            "input_tokens": 4096,
            "output_tokens": 1024,
            "local_only": False,
            "region": "fixture-region",
            "pin_provider": None,
            "pin_model": None,
            "pin_route_id": None,
            "pin_effort": None,
            "service_tier": "normal",
            "hard_budget": False,
            "hard_deadline": False,
        },
    }


def reasons(report, route="preferred"):
    return next(
        check["reasons"] for check in report["candidate_checks"] if check["route_id"] == route
    )


def test_advisory_only_deterministic_nonmutating_and_no_actual_route_claim():
    raw = fixture()
    before = copy.deepcopy(raw)
    report = evaluate_shadow_fixture(raw)
    assert raw == before
    assert report == evaluate_shadow_fixture(raw)
    assert report["status"] == "advisory"
    assert report["baseline_route_id"] == "baseline"
    assert report["suggested_route_id"] == "preferred"
    assert report["execution_authorized"] is False
    assert report["live_routing_enabled"] is False
    assert report["quality_validated"] is False
    assert report["fallback_plan"] == []
    assert all(
        report[field] is None
        for field in ("actual_route", "effective_wire_effort", "actual_usage", "actual_cost")
    )
    raw["candidates"].reverse()
    assert report == evaluate_shadow_fixture(raw)
    report["candidate_checks"][0]["reasons"].append("mutated")
    assert not reasons(evaluate_shadow_fixture(raw), "baseline")


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"configured": False}, "route_not_configured"),
        ({"configured": None}, "route_configured_unknown"),
        ({"available": False}, "route_not_available"),
        ({"available": None}, "route_available_unknown"),
        ({"recipient_ids": None}, "recipients_unknown"),
        ({"recipient_ids": ["other-recipient"]}, "recipient_not_permitted"),
        ({"recipient_ids": []}, "remote_recipients_missing"),
        ({"data_scopes": None}, "data_scope_unknown"),
        ({"data_scopes": []}, "data_scope_not_permitted"),
        ({"region": None}, "region_mismatch_or_unknown"),
        ({"region": "elsewhere"}, "region_mismatch_or_unknown"),
        ({"capabilities": None}, "capabilities_unknown"),
        ({"capabilities": ["text"]}, "capability_missing"),
        ({"context_limit": None}, "context_limit_unknown"),
        ({"context_limit": 5119}, "context_limit_exceeded"),
        ({"output_limit": None}, "output_limit_unknown"),
        ({"output_limit": 1023}, "output_limit_exceeded"),
        ({"supported_efforts": None}, "effort_support_unknown"),
        ({"supported_efforts": ["low"]}, "effort_unsupported"),
        ({"effort": "xhigh"}, "effort_unsupported"),
        ({"effort": "provider_default"}, "effort_unsupported"),
        ({"service_tier": "fast"}, "service_tier_mismatch"),
        ({"supported_service_tiers": None}, "service_tier_support_unknown"),
        ({"supported_service_tiers": []}, "service_tier_unsupported"),
    ],
)
def test_filters_before_ranking(changes, reason):
    raw = fixture()
    raw["candidates"][1].update(changes)
    result = evaluate_shadow_fixture(raw)
    assert result["suggested_route_id"] == "baseline"
    assert reason in reasons(result)


@pytest.mark.parametrize(
    "pin,field,value",
    [
        ("pin_provider", "provider", "different-provider"),
        ("pin_model", "model", "different-model"),
        ("pin_effort", "effort", "low"),
    ],
)
def test_exact_pins_are_never_optimized_away(pin, field, value):
    raw = fixture()
    raw["constraints"][pin] = raw["candidates"][0][field]
    raw["candidates"][1][field] = value
    result = evaluate_shadow_fixture(raw)
    assert result["suggested_route_id"] == "baseline"
    assert f"{field}_pin_mismatch" in reasons(result)


def test_only_permitted_route_ids_and_exact_route_pin_remain_eligible():
    raw = fixture()
    raw["constraints"]["permitted_route_ids"] = ["baseline"]
    assert evaluate_shadow_fixture(raw)["suggested_route_id"] == "baseline"
    raw["constraints"]["permitted_route_ids"].append("preferred")
    raw["constraints"]["pin_route_id"] = "baseline"
    assert "route_id_pin_mismatch" in reasons(evaluate_shadow_fixture(raw))


@pytest.mark.parametrize("change", ["missing", "unavailable", "not-permitted", "pin-mismatch"])
def test_unqualified_baseline_blocks_even_when_an_alternative_is_feasible(change):
    raw = fixture()
    if change == "missing":
        raw["baseline_route_id"] = "absent"
    elif change == "unavailable":
        raw["candidates"][0]["available"] = False
    elif change == "not-permitted":
        raw["constraints"]["permitted_route_ids"] = ["preferred"]
    else:
        raw["constraints"]["pin_route_id"] = "preferred"
    result = evaluate_shadow_fixture(raw)
    assert result["status"] == "blocked"
    assert result["suggested_route_id"] is None
    assert not reasons(result)


@pytest.mark.parametrize("hard", ["budget", "deadline"])
def test_hard_runtime_guarantees_are_never_fabricated(hard):
    raw = fixture()
    raw["constraints"][f"hard_{hard}"] = True
    result = evaluate_shadow_fixture(raw)
    assert result["status"] == "blocked"
    assert f"hard_{hard}_enforcement_unavailable" in reasons(result)


def test_local_only_and_required_modalities_fail_closed():
    raw = fixture()
    raw["constraints"]["local_only"] = True
    result = evaluate_shadow_fixture(raw)
    assert result["status"] == "blocked"
    assert "locality_unverified" in reasons(result)
    for value in raw["candidates"]:
        value.update(local=True, recipient_ids=[])
    assert evaluate_shadow_fixture(raw)["status"] == "advisory"
    raw["constraints"]["required_capabilities"].append("image")
    assert "capability_missing" in reasons(evaluate_shadow_fixture(raw))


def test_effort_none_is_exact_and_wire_is_never_inferred_from_fixture_support():
    raw = fixture()
    raw["constraints"]["pin_effort"] = "none"
    for value in raw["candidates"]:
        value["effort"] = "none"
    result = evaluate_shadow_fixture(raw)
    assert result["status"] == "advisory"
    assert result["effective_wire_effort"] is None
    assert result["suggested_requested_effort"] == "none"
    raw["candidates"][0]["supported_efforts"] = ["high"]
    assert evaluate_shadow_fixture(raw)["status"] == "blocked"


def test_audit_has_no_provider_endpoint_model_or_freeform_fields():
    raw = fixture()
    raw["candidates"][0].update(
        provider="private-provider", model="private-model", endpoint_id="private-endpoint"
    )
    report = json.dumps(evaluate_shadow_fixture(raw))
    assert "private-" not in report
    for name in ("prompt", "context", "goal", "api_key", "authorization", "owner_id"):
        raw[name] = "DO NOT ECHO THIS"
        with pytest.raises(ShadowFixtureError, match="^invalid_shadow_fixture$"):
            evaluate_shadow_fixture(raw)
        del raw[name]


@pytest.mark.parametrize("value", [None, [], True, 1, "fixture"])
def test_invalid_top_level(value):
    with pytest.raises(ShadowFixtureError):
        evaluate_shadow_fixture(value)


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("schema_version",), 2),
        (("policy_id",), "token\nsecret"),
        (("policy_id",), ""),
        (("policy_id",), "x" * 129),
        (("preference_order",), ["baseline"]),
        (("preference_order",), ["baseline", "baseline"]),
        (("preference_order",), ["baseline", "preferred", "unknown"]),
        (("candidates",), []),
        (("candidates",), [candidate()] * 33),
        (("candidates", 1, "route_id"), "baseline"),
        (("candidates", 1, "configured"), 1),
        (("candidates", 1, "available"), "yes"),
        (("candidates", 1, "context_limit"), True),
        (("candidates", 1, "context_limit"), 0),
        (("candidates", 1, "output_limit"), float("inf")),
        (("candidates", 1, "effort"), ["high"]),
        (("candidates", 1, "effort"), "HIGH"),
        (("candidates", 1, "capabilities"), ["unknown"]),
        (("candidates", 1, "recipient_ids"), ["one", "one"]),
        (("candidates", 1, "recipient_ids"), {"one": True}),
        (("constraints", "input_tokens"), 0),
        (("constraints", "output_tokens"), True),
        (("constraints", "input_tokens"), 2**31),
        (("constraints", "hard_budget"), "false"),
        (("constraints", "pin_effort"), "automatic"),
        (("constraints", "service_tier"), "premium"),
    ],
)
def test_strict_fixture_validation(path, value):
    raw = fixture()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ShadowFixtureError, match="^invalid_shadow_fixture$"):
        evaluate_shadow_fixture(raw)


@pytest.mark.parametrize(
    "field", ["api_key", "base_url", "profile", "fallback_providers", "request_overrides", "prompt"]
)
def test_unknown_candidate_fields_cannot_smuggle_routes_or_credentials(field):
    raw = fixture()
    raw["candidates"][0][field] = "ignored-is-not-safe"
    with pytest.raises(ShadowFixtureError):
        evaluate_shadow_fixture(raw)


def test_local_only_rejects_outbound_recipient_even_for_local_execution():
    raw = fixture()
    raw["constraints"]["local_only"] = True
    for value in raw["candidates"]:
        value["local"] = True
    result = evaluate_shadow_fixture(raw)
    assert result["status"] == "blocked"
    assert "locality_unverified" in reasons(result)


def test_fixture_script_sample_and_errors(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    main = runpy.run_path(str(root / "scripts/check_routing_fixture.py"))["main"]
    monkeypatch.setattr(
        sys, "argv", ["script", str(root / "experiments/routing/synthetic-shadow.json")]
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "offline_fixture"
    path = tmp_path / "secret-fixture-name.json"
    monkeypatch.setattr(sys, "argv", ["script", str(path)])
    for data in ("secret-fixture-body", "x" * 65537, "[" * 10000, "\ud800"):
        path.write_bytes(data.encode("utf-8", errors="surrogatepass"))
        assert main() == 2
        assert json.loads(capsys.readouterr().out) == {
            "status": "invalid",
            "reason": "invalid_shadow_fixture",
        }
    blocked = fixture()
    blocked["constraints"]["hard_budget"] = True
    path.write_text(json.dumps(blocked))
    assert main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_exact_limits_unknown_locality_and_partial_recipient_approval():
    raw = fixture()
    for value in raw["candidates"]:
        value.update(context_limit=5120, output_limit=1024)
    assert evaluate_shadow_fixture(raw)["status"] == "advisory"
    raw["candidates"][1]["recipient_ids"].append("unapproved-recipient")
    assert "recipient_not_permitted" in reasons(evaluate_shadow_fixture(raw))
    raw["constraints"]["local_only"] = True
    raw["candidates"][0].update(local=None, recipient_ids=[])
    result = evaluate_shadow_fixture(raw)
    assert "locality_unverified" in reasons(result, "baseline")
    assert result["status"] == "blocked"


@pytest.mark.parametrize("extra", [False, True])
def test_missing_or_extra_constraint_fields_are_rejected(extra):
    raw = fixture()
    if extra:
        raw["constraints"]["authorized"] = True
    else:
        del raw["constraints"]["pin_effort"]
    with pytest.raises(ShadowFixtureError):
        evaluate_shadow_fixture(raw)


def test_provider_default_is_supported_only_as_an_explicit_unknown_wire_control():
    raw = fixture()
    for value in raw["candidates"]:
        value.update(effort="provider_default", supported_efforts=["provider_default"])
    report = evaluate_shadow_fixture(raw)
    assert report["status"] == "advisory"
    assert report["effective_wire_effort"] is None
    assert report["suggested_requested_effort"] == "provider_default"
    raw["constraints"]["pin_effort"] = "none"
    assert evaluate_shadow_fixture(raw)["status"] == "blocked"


def test_cli_rejects_duplicate_json_fields_and_missing_file(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    main = runpy.run_path(str(root / "scripts/check_routing_fixture.py"))["main"]
    path = tmp_path / "fixture.json"
    monkeypatch.setattr(sys, "argv", ["script", str(path)])
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"
    path.write_text(
        json.dumps(fixture()).replace(
            '"hard_budget": false', '"hard_budget": true, "hard_budget": false'
        )
    )
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"
