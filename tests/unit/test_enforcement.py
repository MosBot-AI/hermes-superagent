"""The release inventory never represents a permission grant or host isolation."""

import argparse
import json

from personal_agent.enforcement import build_enforcement_inventory, build_enforcement_summary
from personal_agent.plugin import run_cli, setup_cli
from personal_agent.status import build_status


def test_every_known_or_unlisted_write_path_remains_blocked():
    report = build_enforcement_inventory()
    assert report["release_gate"] == "blocked"
    assert report["runtime_enforcement_verified"] is False
    assert report["is_action_authorization"] is False
    assert report["unlisted_paths"] == "blocked and unverified"
    rows = report["paths"]
    assert len({row["path_id"] for row in rows}) == len(rows)
    assert all(row["release_gate"] == "blocked" for row in rows)
    assert not any(row["controlled_writes_enabled"] for row in rows)


def test_synthetic_contracts_do_not_become_real_connector_coverage():
    rows = {row["path_id"]: row for row in build_enforcement_inventory()["paths"]}
    assert rows["native_dispatch"]["evidence"] == "synthetic_contract"
    assert rows["managed_worker"]["evidence"] == "synthetic_contract"
    for path in (
        "mcp",
        "shell",
        "browser",
        "execute_code_rpc",
        "connector_batch",
        "short_worker",
        "scheduled_job",
    ):
        assert rows[path]["evidence"] == "not_tested"
        assert rows[path]["contract_ids"] == []


def test_mutating_a_returned_inventory_cannot_change_later_results():
    first = build_enforcement_inventory()
    first["paths"][0]["controlled_writes_enabled"] = True
    first["paths"][0]["contract_ids"].clear()
    fresh = build_enforcement_inventory()
    assert fresh["paths"][0]["controlled_writes_enabled"] is False
    assert fresh["paths"][0]["contract_ids"]


def test_model_summary_does_not_claim_runtime_verification():
    summary = build_enforcement_summary()
    assert summary == build_status()["write_path_inventory"]
    assert summary["controlled_write_paths_enabled"] == 0
    assert summary["known_write_paths"] == len(build_enforcement_inventory()["paths"])
    assert summary["runtime_enforcement_verified"] is False


def test_coverage_cli_is_a_read_only_inventory(capsys):
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    run_cli(parser.parse_args(["coverage"]))
    assert json.loads(capsys.readouterr().out) == build_enforcement_inventory()
