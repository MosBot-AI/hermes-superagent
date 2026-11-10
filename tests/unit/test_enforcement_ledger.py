"""Ledger reference checks and adversarial drift controls, not host enforcement."""

import json
import os
import subprocess
import sys

import pytest

from scripts.check_enforcement_ledger import ROOT, validate


def ledger():
    return json.loads((ROOT / "docs/enforcement-evidence-ledger.json").read_text())


def test_finite_ledger_matches_inventory_and_real_test_functions():
    validate(ledger())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "duplicate",
        "path_missing",
        "path_extra",
        "path_duplicate",
        "path_contract_missing",
        "path_contract_extra",
        "path_contract_duplicate",
        "function",
        "file",
        "baseline",
        "runtime",
        "writes",
        "gate",
        "path_writes",
        "path_gate",
        "oracle",
        "entry",
        "exposure",
    ],
)
def test_ledger_rejects_drift_and_false_authority(mutation):
    data = ledger()
    if mutation == "missing":
        data["contracts"].pop()
    elif mutation == "extra":
        data["contracts"].append({"contract_id": "invented"})
    elif mutation == "duplicate":
        data["contracts"].append(data["contracts"][0])
    elif mutation == "path_missing":
        data["paths"].pop()
    elif mutation == "path_extra":
        data["paths"].append({"path_id": "invented"})
    elif mutation == "path_duplicate":
        data["paths"].append(data["paths"][0])
    elif mutation == "path_contract_missing":
        data["paths"][0]["contract_ids"].pop()
    elif mutation == "path_contract_extra":
        data["paths"][0]["contract_ids"].append("invented")
    elif mutation == "path_contract_duplicate":
        data["paths"][0]["contract_ids"].append(data["paths"][0]["contract_ids"][0])
    elif mutation == "function":
        data["contracts"][0]["assertions"][0]["function"] = "test_invented"
    elif mutation == "file":
        data["contracts"][0]["assertions"][0]["file"] = "tests/contracts/missing.py"
    elif mutation == "baseline":
        data["baseline_hermes_commit"] = "0" * 40
    elif mutation == "runtime":
        data["runtime_enforcement_verified"] = True
    elif mutation == "writes":
        data["controlled_writes_enabled"] = True
    elif mutation == "gate":
        data["release_gate"] = "enabled"
    elif mutation == "path_writes":
        data["paths"][0]["controlled_writes_enabled"] = True
    elif mutation == "path_gate":
        data["paths"][0]["release_gate"] = "enabled"
    elif mutation == "oracle":
        data["contracts"][0]["effect_oracle"] = ""
    elif mutation == "entry":
        data["contracts"][0]["native_entrypoints"] = []
    elif mutation == "exposure":
        data["project_non_exposure_contracts"].pop()
    with pytest.raises(ValueError):
        validate(data)


def test_checker_direct_cli_without_pythonpath(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts/check_enforcement_ledger.py")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "ledger references match the blocked runtime inventory" in result.stdout
