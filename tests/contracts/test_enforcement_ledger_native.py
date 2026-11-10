"""Pinned-source existence checks, not behavioral enforcement evidence."""

import json
import subprocess
from pathlib import Path

from scripts.check_enforcement_ledger import ROOT, symbol_exists


def test_ledger_native_symbols_exist_at_exact_baseline():
    import hermes_cli.plugins

    host = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    ledger = json.loads((ROOT / "docs/enforcement-evidence-ledger.json").read_text())
    observed = subprocess.run(
        ["git", "-C", str(host), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    assert observed == ledger["baseline_hermes_commit"]
    for contract in ledger["contracts"]:
        for ref in contract["native_entrypoints"]:
            assert symbol_exists(host / ref["file"], ref["symbol"]), (contract["contract_id"], ref)
