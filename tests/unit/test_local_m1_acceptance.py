"""Static acceptance-ledger integrity; never substitutes for execution evidence."""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_m1_acceptance_ledger_references_and_boundaries():
    ledger = json.loads((ROOT / "docs/local-m1-acceptance-ledger.json").read_text())
    assert ledger["schema_version"] == 1 and ledger["issue"] == 115
    assert ledger["status"] in {
        "pending_exact_checkpoint_live_run",
        "accepted_original_local_m1_scope",
    }
    for value in ledger["baseline"].values():
        assert re.fullmatch(r"[0-9a-f]{40}", value)
    compatibility = json.loads((ROOT / "compatibility.json").read_text())
    assert ledger["baseline"]["hermes_sha"] == compatibility["hermes_commit"]
    for standard in ledger["standards"]:
        assert (ROOT / standard["path"]).is_file()
    assert [c["id"] for c in ledger["criteria"]] == [f"M1-{i}" for i in range(1, 8)]
    assert [p["id"] for p in ledger["entry_prerequisites"]] == ["E0.1", "E0.2", "E0.4", "E0.5"]
    for prerequisite in ledger["entry_prerequisites"]:
        assert prerequisite["scope"] and prerequisite["evidence"] == ["foundation"]
    exposure = ledger["entry_prerequisites"][2]
    assert exposure["reference"] == "docs/enforcement-evidence-ledger.json"
    assert (ROOT / exposure["reference"]).is_file()
    assert "No host-wide read-only" in exposure["scope"]
    rows = [
        *ledger["entry_prerequisites"],
        *ledger["criteria"],
        *ledger["recovery_evidence"],
        ledger["additional_shipped_scenarios"],
    ]
    for row in rows:
        assert row["tests"] and row["evidence"]
        for evidence in row["evidence"]:
            assert evidence in ledger["evidence"]
        for reference in row["tests"]:
            path, function = reference.split("::")
            assert not Path(path).is_absolute() and ".." not in Path(path).parts
            source = ast.parse((ROOT / path).read_text())
            functions = {
                n.name for n in source.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            assert function.startswith("test_") and function in functions, reference
    for evidence in ledger["evidence"].values():
        assert evidence["source_sha"] == ledger["baseline"]["source_sha"]
        assert evidence["status"] in {"verified_success", "pending"}
        if evidence["status"] == "verified_success":
            assert type(evidence["run_id"]) is int and evidence["run_id"] > 0
            assert evidence["url"] == (
                "https://github.com/MosBot-AI/hermes-superagent/actions/runs/"
                + str(evidence["run_id"])
            )
        else:
            assert evidence["run_id"] is None and evidence["url"] is None
    if ledger["status"] == "accepted_original_local_m1_scope":
        assert all(e["status"] == "verified_success" for e in ledger["evidence"].values())
    recovery = {r["id"]: r for r in ledger["recovery_evidence"]}
    assert set(recovery) == {
        "normal_gateway_restart",
        "taskstore_process_crash",
        "additional_gateway_hard_kill",
    }
    assert recovery["taskstore_process_crash"]["cases"] == 88
    assert recovery["additional_gateway_hard_kill"]["hard_kills"] == 2
    assert {r["id"] for r in ledger["separately_pending"]} == {
        "E6.9",
        "issue-21",
        "issue-19",
        "remote-and-shared-rest",
        "workers",
        "memory",
    }
    assert all(
        r["status"] in {"outside_original_local_m1", "separately_pending"}
        for r in ledger["separately_pending"]
    )
    assert "does not rerun" in ledger["static_validation_limit"]
