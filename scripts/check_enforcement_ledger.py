"""Validate offline E0.4 evidence references, never grant runtime authority."""

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Direct script execution must not depend on the caller's cwd or PYTHONPATH.
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from personal_agent.enforcement import build_enforcement_inventory  # noqa: E402


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(rows, key):
    values = [row[key] for row in rows]
    require(len(values) == len(set(values)), f"duplicate {key}")
    return set(values)


def symbol_exists(path, symbol):
    nodes = ast.parse(path.read_text()).body
    for part in symbol.split("."):
        matches = [
            node
            for node in nodes
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == part
        ]
        if len(matches) != 1:
            return False
        nodes = matches[0].body
    return True


def validate(ledger, root=ROOT):
    inventory = build_enforcement_inventory()
    baseline = json.loads((root / "compatibility.json").read_text())["hermes_commit"]
    require(ledger["schema_version"] == 1, "ledger schema")
    require(
        ledger["baseline_hermes_commit"] == baseline == inventory["baseline_hermes_commit"],
        "baseline mismatch",
    )
    for report in (ledger, inventory):
        require(
            report["runtime_enforcement_verified"] is False, "runtime verification must stay false"
        )
        require(report["release_gate"] == "blocked", "release must stay blocked")
    require(ledger["controlled_writes_enabled"] is False, "writes must stay disabled")
    for field in ("scope", "completion", "non_exposure_limits", "downstream_limits"):
        require(bool(ledger[field].strip()), f"missing {field}")
    expected = {row["path_id"]: row for row in inventory["paths"]}
    require(unique(ledger["paths"], "path_id") == set(expected), "path inventory mismatch")
    wanted = set()
    for row in ledger["paths"]:
        ids = row["contract_ids"]
        require(len(ids) == len(set(ids)), "duplicate path contract ID")
        require(
            set(ids) == set(expected[row["path_id"]]["contract_ids"]), "path contracts mismatch"
        )
        require(row["controlled_writes_enabled"] is False, "path writes must stay disabled")
        require(row["release_gate"] == "blocked", "path release must stay blocked")
        require(bool(row["unsupported_or_downstream"].strip()), "missing path limits")
        wanted.update(ids)
    require(unique(ledger["contracts"], "contract_id") == wanted, "contract inventory mismatch")
    exposures = ledger["project_non_exposure_contracts"]
    require(
        len(exposures) == len(set(exposures)) and set(exposures) <= wanted, "exposure references"
    )
    require(
        set(exposures) == {cid for cid in wanted if cid.startswith("production_")},
        "exposure coverage",
    )
    for contract in ledger["contracts"]:
        require(bool(contract["effect_oracle"].strip()), "missing independent oracle")
        require(bool(contract["native_entrypoints"]), "missing native entry")
        require(bool(contract["assertions"]), "missing assertions")
        seen = set()
        for ref in contract["assertions"]:
            key = (ref["file"], ref["function"])
            require(key not in seen, "duplicate assertion")
            seen.add(key)
            path = root / ref["file"]
            require(
                path.is_relative_to(root / "tests/contracts") and ".." not in path.parts,
                "test path",
            )
            require(path.is_file(), "missing test file")
            require(
                ref["function"].startswith("test_") and symbol_exists(path, ref["function"]),
                "missing test function",
            )
        for ref in contract["native_entrypoints"]:
            require(
                ref["file"].endswith(".py") and not Path(ref["file"]).is_absolute(), "native file"
            )
            require(
                ".." not in Path(ref["file"]).parts and bool(ref["symbol"].strip()), "native symbol"
            )


def main():
    validate(json.loads((ROOT / "docs/enforcement-evidence-ledger.json").read_text()))
    print("Finite enforcement ledger references match the blocked runtime inventory.")


if __name__ == "__main__":
    main()
