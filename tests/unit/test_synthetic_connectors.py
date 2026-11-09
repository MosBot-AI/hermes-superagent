"""Reusable offline connector corpus, ground truth, attack and recovery evidence."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from personal_agent.action_intents import ActionIntentStore, IntentError
from personal_agent.authorization import evaluate_read
from personal_agent.enforcement import build_enforcement_inventory
from tests.fixtures.synthetic_connectors import Capabilities, FixtureError, LostResponse, Remote
from tests.fixtures.synthetic_connectors.core import (
    MAX_JSON_BYTES,
    MAX_PAYLOAD_BYTES,
    binding,
    canonical,
    prepare_envelope,
    strict_json,
    strict_object,
)
from tests.fixtures.synthetic_connectors.oracles import (
    Observations,
    assert_matching_receipt,
    assert_no_blind_resend,
    assert_pure,
    classify_receipt,
    execute_once,
    ground_truth,
    reconcile_only,
    sanitized_report,
    validate_sources,
)

SPEC = {
    "account_ref": "account-a",
    "operation": "message.send",
    "target": "recipient-a@fixture.invalid",
    "payload": "SYNTHETIC_BODY_A",
    "effect_key": "effect-1",
    "prepared_version": 1,
}
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def remote(tmp_path):
    return Remote(tmp_path / "remote.sqlite3")


def spec(**changes):
    return {**SPEC, **changes}


def test_bounded_corpus_has_stable_provenance_and_separate_accounts(remote):
    a = remote.read({"account_ref": "account-a", "cursor": 0, "limit": 2})
    items = validate_sources(a, "account-a")
    assert a["next_cursor"] == 2
    b = remote.read({"account_ref": "account-b", "cursor": 0, "limit": 4})
    assert b["next_cursor"] is None
    assert {r["source_id"] for r in items}.isdisjoint(r["source_id"] for r in b["items"])
    assert "SYNTHETIC_ACCOUNT_B_PRIVATE_CANARY" not in canonical(a)
    again = remote.read({"account_ref": "account-a", "cursor": 0, "limit": 2})
    assert again == a
    tail = remote.read({"account_ref": "account-a", "cursor": 2, "limit": 4})
    scenarios = {r["scenario"] for r in items + validate_sources(tail, "account-a")}
    assert scenarios == {"normal", "spoofed_owner", "prompt_injection", "conflicting_record"}
    for record in items + tail["items"] + b["items"]:
        assert record["provenance"]["locator"].startswith("https://sources.fixture.invalid/")
        assert record["provenance"]["observed_at"] == "2026-11-09T00:00:00Z"
        assert record["authenticated_owner"] is False
    assert ground_truth(remote.path)["effects"] == []


def test_source_prose_cannot_establish_owner_or_production_authority(remote):
    sources = remote.read({"account_ref": "account-a", "cursor": 0, "limit": 4})["items"]
    for source in sources:
        decision = evaluate_read(
            source,
            source,
            source,
            current_policy_revision=1,
            current_epoch=1,
            now=datetime(2026, 11, 9, tzinfo=UTC),
        )
        assert decision.allowed is False
        assert decision.reason == "invalid_context"
    inventory = build_enforcement_inventory()
    assert inventory["release_gate"] == "blocked"
    assert not any(p["controlled_writes_enabled"] for p in inventory["paths"])
    assert ground_truth(remote.path)["effects"] == []


def test_prepare_read_describe_health_are_pure(remote):
    before = remote.path.read_bytes()
    remote.describe()
    remote.health()
    remote.read({"account_ref": "account-a", "cursor": 0, "limit": 4})
    envelope = remote.prepare(SPEC)
    assert_pure(before, remote.path.read_bytes())
    assert envelope["binding_digest"] and envelope["payload_digest"]
    assert remote.describe()["write_release_gate"] == "blocked"
    assert remote.describe()["limits"]["batch_max"] == 1


def test_success_deduplicates_and_receipts_are_accepted_not_delivered(remote):
    envelope = remote.prepare(SPEC)
    receipt = remote.execute(envelope)
    assert_matching_receipt(remote.path, envelope, receipt)
    assert receipt["status"] == "accepted" and receipt["delivered"] is False
    assert remote.execute(envelope) == receipt
    assert remote.reconcile(envelope) == receipt
    assert_no_blind_resend(remote.path, effects=1, execute_attempts=2)
    stored = remote.path.read_bytes()
    assert SPEC["payload"].encode() not in stored
    assert SPEC["target"].encode() not in stored


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_ref", "account-b"),
        ("operation", "message.delete"),
        ("target", "recipient-b@fixture.invalid"),
        ("payload", "SYNTHETIC_CHANGED"),
        ("effect_key", "effect-2"),
        ("prepared_version", 2),
        ("target_digest", "0" * 64),
        ("payload_digest", "0" * 64),
        ("binding_digest", "0" * 64),
        ("schema_version", "other"),
    ],
)
def test_tampering_prepared_fields_is_rejected_without_effect(remote, field, value):
    envelope = remote.prepare(SPEC)
    with pytest.raises(FixtureError):
        remote.execute({**envelope, field: value})
    assert ground_truth(remote.path)["effects"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", "recipient-b@fixture.invalid"),
        ("payload", "SYNTHETIC_CHANGED"),
    ],
)
def test_reprepared_changed_data_conflicts_with_stable_effect_key(remote, field, value):
    original = remote.prepare(SPEC)
    remote.execute(original)
    other = remote.prepare(spec(**{field: value}))
    with pytest.raises(FixtureError, match="effect_conflict"):
        remote.execute(other)
    assert remote.reconcile(other) == {"status": "unknown_outcome", "reason": "binding_mismatch"}
    assert len(ground_truth(remote.path)["effects"]) == 1


def test_account_namespace_is_explicit_not_implicit_permission(remote):
    first = remote.execute(remote.prepare(SPEC))
    second_spec = spec(account_ref="account-b", target="recipient-b@fixture.invalid")
    second_envelope = remote.prepare(second_spec)
    second = remote.execute(second_envelope)
    assert first["receipt_ref"] != second["receipt_ref"]
    assert_matching_receipt(remote.path, second_envelope, second)
    assert classify_receipt(second_envelope, first) == "unknown_outcome"


@pytest.mark.parametrize("auth", ["expired", "revoked", "unavailable"])
def test_auth_change_refuses_reads_preparation_and_execution(remote, auth):
    envelope = remote.prepare(SPEC)
    remote.configure_account("account-a", auth=auth)
    assert remote.health()["accounts"]["account-a"] == auth
    for action in [
        lambda: remote.prepare(SPEC),
        lambda: remote.execute(envelope),
        lambda: remote.reconcile(envelope),
        lambda: remote.cancel(envelope),
        lambda: remote.read({"account_ref": "account-a", "cursor": 0, "limit": 1}),
    ]:
        with pytest.raises(FixtureError, match="auth_" + auth):
            action()
    assert ground_truth(remote.path)["effects"] == []


def test_prepared_version_is_checked_at_execution(remote):
    envelope = remote.prepare(SPEC)
    remote.configure_account("account-a", version=2)
    with pytest.raises(FixtureError, match="stale_preparation"):
        remote.execute(envelope)
    assert ground_truth(remote.path)["effects"] == []
    newer = remote.prepare(spec(prepared_version=2))
    remote.execute(newer)
    assert len(ground_truth(remote.path)["effects"]) == 1


@pytest.mark.parametrize("fault,effects", [("precommit_loss", 0), ("postcommit_loss", 1)])
def test_indistinguishable_losses_remain_unknown_without_blind_retry(tmp_path, fault, effects):
    path = tmp_path / "remote.sqlite3"
    remote = Remote(path, fault=fault)
    envelope = remote.prepare(SPEC)
    observed = Observations(tmp_path / "client.sqlite3")
    outcome = execute_once(lambda: remote, envelope, observed)
    assert outcome == {"status": "unknown_outcome"}
    assert observed.report()["accepted_observations"] == 0
    assert_no_blind_resend(path, effects=effects)
    recovered = reconcile_only(
        lambda: Remote(path),
        envelope,
        observed,
        verifier=lambda e, r: assert_matching_receipt(path, e, r),
    )
    assert recovered["status"] == ("accepted" if effects else "unknown_outcome")
    assert_no_blind_resend(path, effects=effects)


@pytest.mark.parametrize(
    "mode,reconciliation",
    [
        ("native_key", True),
        ("reconciliation_only", True),
        ("none", False),
    ],
)
def test_capability_variants_and_unknown_recovery(tmp_path, mode, reconciliation):
    path = tmp_path / "remote.sqlite3"
    caps = Capabilities(idempotency=mode, reconciliation=reconciliation)
    remote = Remote(path, capabilities=caps, fault="postcommit_loss")
    envelope = remote.prepare(SPEC)
    observed = Observations(tmp_path / "client.sqlite3")
    execute_once(lambda: remote, envelope, observed)
    recovered = reconcile_only(
        lambda: Remote(path),
        envelope,
        observed,
        verifier=lambda e, r: assert_matching_receipt(path, e, r),
    )
    assert recovered["status"] == ("accepted" if reconciliation else "unknown_outcome")
    assert_no_blind_resend(path, effects=1)
    assert Remote(path).capabilities == caps


@pytest.mark.parametrize("behavior", ["reconcile_unavailable", "reconcile_empty"])
def test_unavailable_or_empty_reconciliation_cannot_prove_nonexecution(tmp_path, behavior):
    remote = Remote(tmp_path / "remote.sqlite3", fault="postcommit_loss")
    envelope = remote.prepare(SPEC)
    observed = Observations(tmp_path / "client.sqlite3")
    execute_once(lambda: remote, envelope, observed)
    outcome = reconcile_only(lambda: Remote(remote.path, behavior=behavior), envelope, observed)
    assert outcome["status"] == "unknown_outcome"
    assert_no_blind_resend(remote.path, effects=1)


def test_finite_idempotency_expiry_unsafe_resend_positive_control(tmp_path):
    now = [1000]
    remote = Remote(tmp_path / "remote.sqlite3", clock=lambda: now[0])
    envelope = remote.prepare(SPEC)
    first = remote.execute(envelope)
    now[0] = 1059
    assert remote.execute(envelope) == first
    now[0] = 1060
    # Deliberately unsafe consumer. This is the failure the oracle must detect.
    duplicate = remote.execute(envelope)
    assert duplicate["receipt_ref"] != first["receipt_ref"]
    with pytest.raises(AssertionError, match="unexpected_remote_effect_count"):
        assert_no_blind_resend(remote.path, effects=1)
    assert len(ground_truth(remote.path)["effects"]) == 2
    assert remote.reconcile(envelope) == {"status": "unknown_outcome", "reason": "ambiguous"}


@pytest.mark.parametrize("mode", ["reconciliation_only", "none"])
def test_no_native_key_replay_is_deliberately_not_deduplicated(tmp_path, mode):
    remote = Remote(tmp_path / "remote.sqlite3", capabilities=Capabilities(idempotency=mode))
    envelope = remote.prepare(SPEC)
    remote.execute(envelope)
    remote.execute(envelope)
    assert len(ground_truth(remote.path)["effects"]) == 2


def test_unsupported_and_too_late_cancellation_are_truthful(tmp_path):
    remote = Remote(tmp_path / "unsupported.sqlite3")
    envelope = remote.prepare(SPEC)
    assert remote.cancel(envelope) == {"status": "cancel_requested", "reason": "unsupported"}
    assert len(ground_truth(remote.path)["effects"]) == 0
    supported = Remote(tmp_path / "supported.sqlite3", capabilities=Capabilities(cancellation=True))
    envelope = supported.prepare(SPEC)
    supported.execute(envelope)
    assert supported.cancel(envelope) == {"status": "cancel_requested", "reason": "too_late"}
    assert supported.reconcile(envelope)["status"] == "accepted"


def test_supported_cancellation_before_acceptance_is_terminal(tmp_path):
    remote = Remote(tmp_path / "remote.sqlite3", capabilities=Capabilities(cancellation=True))
    envelope = remote.prepare(SPEC)
    result = remote.cancel(envelope)
    assert result["status"] == "cancelled"
    assert remote.cancel(envelope) == result
    with pytest.raises(FixtureError, match="cancelled"):
        Remote(remote.path).execute(envelope)
    assert ground_truth(remote.path)["effects"] == []


@pytest.mark.parametrize("behavior", ["lying_read", "impure_prepare"])
def test_dishonest_purity_is_detected_by_independent_oracle(tmp_path, behavior):
    remote = Remote(tmp_path / "remote.sqlite3", behavior=behavior)
    before = ground_truth(remote.path)
    if behavior == "lying_read":
        remote.read({"account_ref": "account-a", "cursor": 0, "limit": 4})
    else:
        remote.prepare(SPEC)
    with pytest.raises(AssertionError, match="declared_read_or_prepare_mutated_remote"):
        assert_pure(before, ground_truth(remote.path))
    assert len(ground_truth(remote.path)["effects"]) == 1


@pytest.mark.parametrize(
    "behavior",
    [
        "prose_only",
        "wrong_account",
        "wrong_target",
        "wrong_effect",
        "wrong_receipt",
        "contradictory",
        "prompt_injection",
    ],
)
def test_malicious_receipts_fail_independent_evidence_oracle(tmp_path, behavior):
    remote = Remote(tmp_path / "remote.sqlite3", behavior=behavior)
    envelope = remote.prepare(SPEC)
    receipt = remote.execute(envelope)
    with pytest.raises(AssertionError):
        assert_matching_receipt(remote.path, envelope, receipt)
    # A structurally plausible fabricated receipt needs the independent oracle.
    expected = "accepted_claim" if behavior == "wrong_receipt" else "unknown_outcome"
    assert classify_receipt(envelope, receipt) == expected
    assert len(ground_truth(remote.path)["effects"]) == 1
    observations = Observations(tmp_path / "client.sqlite3")
    report = canonical(sanitized_report(remote.path, observations))
    for forbidden in [SPEC["payload"], SPEC["target"], "CANARY", "approved", "instructions"]:
        assert forbidden not in report


@pytest.mark.parametrize("behavior", ["malformed_result", "oversized_result"])
def test_malformed_and_oversized_source_results_are_rejected(tmp_path, behavior):
    remote = Remote(tmp_path / "remote.sqlite3", behavior=behavior)
    result = remote.read({"account_ref": "account-a", "cursor": 0, "limit": 4})
    with pytest.raises(FixtureError):
        validate_sources(result, "account-a")


@pytest.mark.parametrize(
    "raw",
    [
        '{"x":1,"x":2}',
        '{"x":{"y":1,"y":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":1.0}',
        "{bad",
        "[]",
        "null",
        '"string"',
        '{"x":' + "[" * 12 + "0" + "]" * 12 + "}",
        '{"x":"' + "x" * MAX_JSON_BYTES + '"}',
    ],
)
def test_strict_json_rejects_duplicate_malformed_deep_and_oversized(raw):
    with pytest.raises(FixtureError):
        strict_json(raw)


def test_strict_json_valid_round_trip():
    assert strict_json(canonical(SPEC)) == SPEC


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": True},
        {"payload": "x" * (MAX_PAYLOAD_BYTES + 1)},
        {"payload": b"bytes"},
        {"payload": object()},
        {"payload": "\ud800"},
        {"payload": ""},
        {"prepared_version": True},
        {"prepared_version": -1},
        {"target": "someone@example.com"},
        {"account_ref": "environment-account"},
        {"effect_key": "../../credential"},
        {"operation": "read.credentials"},
        {"batch": [SPEC]},
    ],
)
def test_invalid_input_never_commits_and_errors_are_redacted(remote, changes):
    with pytest.raises(FixtureError) as error:
        remote.prepare(spec(**changes))
    assert SPEC["payload"] not in str(error.value)
    assert "credential" not in str(error.value)
    assert ground_truth(remote.path)["effects"] == []


def test_lists_and_executable_subclasses_are_rejected_before_execution(remote):
    class Hostile(dict):
        def items(self):
            raise AssertionError("must_not_execute")

    for invalid in [[SPEC], Hostile(SPEC), None]:
        with pytest.raises(FixtureError):
            remote.prepare(invalid)
    assert ground_truth(remote.path)["effects"] == []


def test_invalid_read_scope_and_bounds(remote):
    for changes in [
        {"account_ref": "unknown"},
        {"cursor": True},
        {"cursor": -1},
        {"limit": 5},
        {"limit": 0},
        {"unexpected": "field"},
    ]:
        with pytest.raises(FixtureError):
            remote.read({"account_ref": "account-a", "cursor": 0, "limit": 4, **changes})


def test_clock_rollback_is_refused_without_new_effect(tmp_path):
    now = [1000]
    remote = Remote(tmp_path / "remote.sqlite3", clock=lambda: now[0])
    envelope = remote.prepare(SPEC)
    remote.execute(envelope)
    now[0] = 999
    with pytest.raises(FixtureError, match="clock_rollback"):
        remote.execute(envelope)
    assert len(ground_truth(remote.path)["effects"]) == 1


def test_concurrent_native_key_attempts_create_one_effect(remote):
    envelope = remote.prepare(SPEC)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: Remote(remote.path).execute(envelope), range(8)))
    assert len({r["receipt_ref"] for r in receipts}) == 1
    assert len(ground_truth(remote.path)["effects"]) == 1


@pytest.mark.parametrize(
    "stage,effects",
    [
        ("before_commit", 0),
        ("after_commit", 1),
        ("after_response", 1),
    ],
)
def test_process_crashes_preserve_separate_remote_and_consumer_truth(tmp_path, stage, effects):
    path = tmp_path / "remote.sqlite3"
    client_path = tmp_path / "client.sqlite3"
    remote = Remote(path)
    envelope = remote.prepare(SPEC)
    child = r"""
import json, os, socket, sys
from tests.fixtures.synthetic_connectors import Remote
from tests.fixtures.synthetic_connectors.oracles import Observations, execute_once

def deny(*args, **kwargs):
    raise AssertionError("network_forbidden")
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
path, client, stage, encoded = sys.argv[1:]
envelope = json.loads(encoded)
def checkpoint(current):
    if current == stage:
        os._exit(75)
def before_observe():
    if stage == "after_response":
        print("response_ready", flush=True)
        os._exit(75)
remote = Remote(path, checkpoint=checkpoint)
execute_once(lambda: remote, envelope, Observations(client), before_observe=before_observe)
raise AssertionError("crash_point_not_reached")
"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", child, str(path), str(client_path), stage, canonical(envelope)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 75, result.stderr
    assert ("response_ready" in result.stdout) is (stage == "after_response")
    observations = Observations(client_path)
    assert observations.report()["latest_outcome"] == "unknown_outcome"
    assert observations.report()["accepted_observations"] == 0
    assert_no_blind_resend(path, effects=effects)
    recovered = reconcile_only(
        lambda: Remote(path),
        envelope,
        observations,
        verifier=lambda e, r: assert_matching_receipt(path, e, r),
    )
    assert recovered["status"] == ("accepted" if effects else "unknown_outcome")
    assert_no_blind_resend(path, effects=effects)


def test_actual_action_intents_remain_drafts_across_reopen_cancel_and_expiry(tmp_path, remote):
    now = [datetime(2026, 11, 9, tzinfo=UTC)]
    prepared = remote.prepare(SPEC)
    intent_spec = {
        "owner_id": "synthetic-owner",
        "profile_id": "synthetic-profile",
        "request_id": "synthetic-request",
        "operation": prepared["operation"],
        "policy_revision": 1,
        "epoch": 0,
        "resource_revision": 1,
        "expires_at": now[0] + timedelta(minutes=5),
        "target": prepared["target"].encode(),
        "payload": prepared["payload"].encode(),
    }
    key = {k: intent_spec[k] for k in ("owner_id", "profile_id", "request_id")}
    path = tmp_path / "intent.sqlite3"
    conn = sqlite3.connect(path)
    store = ActionIntentStore(conn, clock=lambda: now[0])
    store.initialize()
    draft = store.prepare(intent_spec)
    assert draft["state"] == "draft"
    with pytest.raises(IntentError, match="request_conflict"):
        store.prepare({**intent_spec, "payload": b"SYNTHETIC_CHANGED"})
    conn.close()
    conn = sqlite3.connect(path)
    store = ActionIntentStore(conn, clock=lambda: now[0])
    store.initialize()
    assert store.prepare(intent_spec) == draft
    assert not hasattr(store, "approve") and not hasattr(store, "execute")
    assert store.cancel(key, expected_revision=1)["state"] == "cancelled"
    second = {**intent_spec, "request_id": "synthetic-second"}
    store.prepare(second)
    now[0] += timedelta(minutes=5)
    assert store.inspect({**key, "request_id": "synthetic-second"})["state"] == "expired"
    conn.close()
    assert SPEC["payload"].encode() not in path.read_bytes()
    assert ground_truth(remote.path)["effects"] == []


def test_loss_exception_and_reports_never_contain_canaries(remote, tmp_path):
    envelope = remote.prepare(spec(payload="SYNTHETIC_SECRET_CANARY_DO_NOT_REPORT"))
    remote.fault = "postcommit_loss"
    with pytest.raises(LostResponse) as error:
        remote.execute(envelope)
    assert str(error.value) == "unknown_outcome"
    report = sanitized_report(remote.path, Observations(tmp_path / "client.sqlite3"))
    assert "CANARY" not in canonical(report)
    assert "binding" not in canonical(report)
    assert report["production_authorized"] is False
    assert report["remote_effect_count"] == 1
    assert report["consumer"]["delivered"] is False


def test_fixture_binding_is_not_action_intent_or_authorization(remote):
    prepared = remote.prepare(SPEC)
    assert binding(prepared) == {
        k: v for k, v in prepared.items() if k not in {"target", "payload"}
    }
    assert "approved" not in prepared and "permit" not in prepared
    assert prepare_envelope(SPEC) == prepared
    with pytest.raises(FixtureError):
        remote.execute({**prepared, "approved": True})
    assert ground_truth(remote.path)["effects"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("next_cursor", {}),
        ("next_cursor", True),
        ("next_cursor", -1),
        ("source_id", {}),
        ("source_id", "src-b-foreign"),
        ("source_id", "src-a-../file"),
        ("author_ref", {}),
        ("author_ref", "actual-owner"),
        ("content", "\ud800"),
        ("authenticated_owner", True),
        ("scenario", "grant_authority"),
        ("provenance.scope_ref", "scope-b"),
        ("provenance.locator", "file:///credentials"),
        ("provenance.observed_at", "not-a-time"),
        ("provenance.kind", {}),
        ("provenance.owner_approved", True),
    ],
)
def test_invalid_source_schema_is_rejected_with_fixed_error(remote, field, value):
    page = remote.read({"account_ref": "account-a", "cursor": 0, "limit": 1})
    if field == "next_cursor":
        page[field] = value
    elif field.startswith("provenance."):
        page["items"][0]["provenance"][field.split(".")[1]] = value
    else:
        page["items"][0][field] = value
    with pytest.raises(FixtureError) as error:
        validate_sources(page, "account-a")
    assert "credentials" not in str(error.value)
    assert "actual-owner" not in str(error.value)


def test_duplicate_source_ids_are_rejected(remote):
    page = remote.read({"account_ref": "account-a", "cursor": 0, "limit": 1})
    page["items"].append(page["items"][0])
    with pytest.raises(FixtureError, match="invalid_source_result"):
        validate_sources(page, "account-a")


@pytest.mark.parametrize("behavior", ["normal", "wrong_receipt"])
def test_plausible_claim_is_not_accepted_without_independent_evidence(tmp_path, behavior):
    remote = Remote(tmp_path / "remote.sqlite3", behavior=behavior)
    prepared = remote.prepare(SPEC)
    observations = Observations(tmp_path / "client.sqlite3")
    assert execute_once(lambda: remote, prepared, observations)["status"] == "unknown_outcome"
    assert observations.report()["accepted_observations"] == 0
    assert observations.report()["observation_count"] == 1
    result = reconcile_only(
        lambda: remote,
        prepared,
        observations,
        verifier=lambda e, r: assert_matching_receipt(remote.path, e, r),
    )
    expected = "accepted" if behavior == "normal" else "unknown_outcome"
    assert result["status"] == expected
    assert observations.report()["accepted_observations"] == (behavior == "normal")
    assert_no_blind_resend(remote.path, effects=1)


@pytest.mark.parametrize("account", ["account-a", "account-b"])
@pytest.mark.parametrize("effect_key", ["effect-1", "effect-other"])
@pytest.mark.parametrize("behavior", ["wrong_account", "wrong_effect"])
def test_malicious_controls_differ_even_for_nondefault_inputs(
    tmp_path, account, effect_key, behavior
):
    remote = Remote(tmp_path / "remote.sqlite3", behavior=behavior)
    prepared = remote.prepare(spec(account_ref=account, effect_key=effect_key))
    receipt = remote.execute(prepared)
    assert classify_receipt(prepared, receipt) == "unknown_outcome"
    with pytest.raises(AssertionError, match="receipt_schema_or_binding"):
        assert_matching_receipt(remote.path, prepared, receipt)


def test_runtime_allowlist_and_imports_exclude_fixture_package():
    manifest = json.loads((ROOT / "packaging/runtime-files.json").read_text())
    assert all(not path.startswith("tests/") for path in manifest["files"])
    for source in (ROOT / "personal_agent").glob("*.py"):
        text = source.read_text()
        assert "synthetic_connectors" not in text
        assert "tests.fixtures" not in text


@pytest.mark.parametrize("replacement", [True, False, "1", 1.0])
def test_receipt_numeric_binding_is_exact_typed(remote, replacement):
    envelope = remote.prepare(SPEC)
    receipt = remote.execute(envelope)
    receipt["binding"]["prepared_version"] = replacement
    assert classify_receipt(envelope, receipt) == "unknown_outcome"
    with pytest.raises(AssertionError, match="receipt_schema_or_binding"):
        assert_matching_receipt(remote.path, envelope, receipt)


def test_invalid_expected_envelope_cannot_make_receipt_truth(remote):
    envelope = remote.prepare(SPEC)
    receipt = remote.execute(envelope)
    envelope["prepared_version"] = True
    receipt["binding"]["prepared_version"] = True
    assert classify_receipt(envelope, receipt) == "unknown_outcome"


@pytest.mark.parametrize(
    "column,value", [("account_ref", "account-b"), ("effect_key", "effect-foreign")]
)
def test_oracle_detects_contradictory_remote_scope_columns(remote, column, value):
    prepared = remote.prepare(SPEC)
    receipt = remote.execute(prepared)
    # Deliberately corrupt independent truth while leaving plausible binding JSON.
    with sqlite3.connect(remote.path) as conn:
        conn.execute(f"UPDATE effects SET {column}=?", (value,))
    with pytest.raises(AssertionError, match="remote_.*_disagrees"):
        assert_matching_receipt(remote.path, prepared, receipt)


def test_oversized_decoded_object_preserves_precise_bound_error():
    with pytest.raises(FixtureError, match="^input_too_large$"):
        strict_object({"raw": "x" * MAX_JSON_BYTES})
