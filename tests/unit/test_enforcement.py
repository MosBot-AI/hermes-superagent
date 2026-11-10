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


def test_boundary_contracts_do_not_become_full_write_path_coverage():
    rows = {row["path_id"]: row for row in build_enforcement_inventory()["paths"]}
    for path in (
        "native_dispatch",
        "direct_registry",
        "mcp",
        "execute_code_rpc",
        "shell",
        "browser",
        "local_tool_batch",
        "connector_batch",
        "short_worker",
        "managed_worker",
        "scheduled_job",
    ):
        assert rows[path]["evidence"] == "pinned_host_boundary_contract"
        assert rows[path]["contract_ids"]
        assert rows[path]["controlled_writes_enabled"] is False
        assert rows[path]["release_gate"] == "blocked"
    assert "mcp_native_trust_gate" in rows["mcp"]["contract_ids"]
    assert "rpc_persistent_client_response_loss" in rows["execute_code_rpc"]["contract_ids"]
    assert "shell_native_deny_and_force_surface" in rows["shell"]["contract_ids"]
    assert "browser_metadata_literal_floor" in rows["browser"]["contract_ids"]
    assert "local_batch_uncertain_retry" in rows["local_tool_batch"]["contract_ids"]
    assert "delegated_child_toolset_and_batch_admission" in rows["short_worker"]["contract_ids"]
    assert "connector_batch_item_veto_partial_retry" in rows["connector_batch"]["contract_ids"]
    assert "worker_current_policy_recheck" in rows["managed_worker"]["contract_ids"]
    assert "worker_revoke_before_admission" in rows["managed_worker"]["contract_ids"]
    assert "production_default_exposure" in rows["native_dispatch"]["contract_ids"]
    assert "production_worker_unsupported" in rows["direct_registry"]["contract_ids"]
    assert "production_safe_bootstrap" in rows["managed_worker"]["contract_ids"]
    assert "production_blueprint_consumers" in rows["scheduled_job"]["contract_ids"]


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
