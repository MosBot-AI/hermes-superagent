"""Finite evidence references, not a replacement for executing/reviewing the tests."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_original_e27_scope_acceptance_references_are_exact_and_present():
    ledger = json.loads((ROOT / "docs/local-memory-acceptance-ledger.json").read_text())
    assert ledger["schema_version"] == 1 and ledger["issue"] == 44
    assert ledger["status"] == "accepted_original_local_backend_scope"
    assert ledger["accepted_baseline"]["commit"] == "15d690adbbd860f145cbc1405399d854d6bb32c4"
    assert ledger["accepted_baseline"]["main_ci"].endswith("/42813558369")
    assert ledger["controlled_writes_enabled"] is False
    criteria = ledger["criteria"]
    assert len(criteria) == 10
    assert {row["id"] for row in criteria} == {f"S{i}" for i in range(1, 7)} | {
        f"A{i}" for i in range(1, 5)
    }
    for row in criteria:
        assert row["criterion"] and row["tests"]
        assert len(row["tests"]) == len(set(row["tests"]))
        for reference in row["tests"]:
            filename, symbol = reference.split("::")
            assert filename.startswith(("tests/unit/", "tests/contracts/"))
            assert ".." not in Path(filename).parts
            nodes = ast.parse((ROOT / filename).read_text()).body
            assert (
                sum(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol
                    for n in nodes
                )
                == 1
            ), reference
    assert len(ledger["conditional_not_enabled"]) == 4
    assert "not the complete host prompt" in ledger["budget_boundary"]
