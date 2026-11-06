"""Static review-bundle integrity only; never import, apply or execute upstream code."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "experiments" / "command-context"
SHA = "fd437b865f54bf64cfb453db05b60aa8417653840ff83587a9f5cfcd3cc92ad3"
OLD_SHA = "ab47d5f7c25c4cbc007332cb05e4f5dbf146ba701ef90cd77e09df10a5af1f20"
BASE = "90d6b98fd86d20981ee06ddd5b7d93e4320f26a4"
COMMIT = "b93642ca32739d4426293603e66175a72582de98"
OLD_COMMIT = "adfb1feb207943d2bb539555adcbb667bcb571ab"


def manifest():
    return json.loads((ARTIFACT / "manifest.json").read_text())


def test_exact_patch_and_inventory():
    data = manifest()
    patch = (ARTIFACT / data["patch_file"]).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == data["patch_sha256"] == SHA
    paths = re.findall(r"^diff --git a/(\S+) b/\S+$", patch.decode(), re.M)
    assert paths == data["patch_files"]
    assert len(paths) == len(set(paths)) == data["changed_files"] == 10
    assert sorted(data["artifact_files"]) == sorted(p.name for p in ARTIFACT.iterdir())
    assert data["base"] == BASE
    assert data["commit"] == COMMIT


def test_preserved_historical_evidence_hashes_and_classification():
    data = manifest()
    evidence = data["historical_evidence"]
    for label in ("verification", "package_inventory"):
        raw = (ARTIFACT / evidence[f"{label}_file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == evidence[f"{label}_sha256"]
    verification = json.loads((ARTIFACT / evidence["verification_file"]).read_text())
    assert verification["patch_sha256"] == OLD_SHA
    assert verification["base_commit"] == BASE
    assert verification["prototype_commit"] == OLD_COMMIT
    assert len(verification["files"]) == 9
    assert {item["path"] for item in verification["files"]} <= set(data["patch_files"])
    assert evidence["prototype_commit"] == OLD_COMMIT
    assert evidence["patch_sha256"] == OLD_SHA
    suite = evidence["selected_suite"]
    assert suite == {
        "passed": 146,
        "failed_at_environment_setup": 9,
        "new_contract_tests_passed": 70,
        "full_green": False,
    }
    results = verification["test_results"]
    assert results["selected_total_passed"] == suite["passed"]
    assert results["selected_total_failed_at_environment_setup"] == 9
    assert results["new_contract_tests_passed"] == 70
    assert results["static_checks_passed"] == evidence["static_checks_passed"] == 14
    assert len(verification["blocked_files"]) == 3
    assert "EPERM" in verification["blocker"]
    assert evidence["lock_environment_equivalence_attested"] is False
    assert evidence["raw_logs_included"] is False


def test_no_runner_or_automatic_integration():
    data = manifest()
    assert all(value is False for value in data["packaging"].values())
    assert not any(p.suffix in {".py", ".sh"} for p in ARTIFACT.iterdir())
    for path in ARTIFACT.iterdir():
        assert not path.stat().st_mode & 0o111
        text = path.read_text()
        assert "/workspace/shared/" not in text
        assert "/home/agent/" not in text
    assert data["prototype_git_remotes"] == []
    assert len(data["integration_gates"]) >= 8
    assert len(data["limits"]) >= 8


def test_bilingual_review_guidance_and_license():
    assert "[简体中文](README-zh.md)" in (ARTIFACT / "README.md").read_text()
    assert "[English](README.md)" in (ARTIFACT / "README-zh.md").read_text()
    for name in ("README.md", "README-zh.md"):
        text = (ARTIFACT / name).read_text()
        for marker in (SHA, BASE, COMMIT, "EPERM", "146", "ABA", "command_context"):
            assert marker in text
        assert 'apply --check "$ARTIFACT/command-context-prototype.patch"' in text
        assert "apply --index" not in text
        assert "scripts/run_tests.sh" not in text
    license_text = (ARTIFACT / "LICENSE.hermes-agent").read_text()
    assert "MIT License" in license_text
    assert "Copyright (c) 2025 Nous Research" in license_text
    for suffix in ("", "-zh"):
        path = ROOT / "docs" / f"23-host-command-context-experiment{suffix}.md"
        text = path.read_text()
        for marker in (BASE, COMMIT, "EPERM", "146", "ABA", "command_context"):
            assert marker in text


def test_current_revision_evidence_is_separate_and_bounded():
    data = manifest()
    evidence = data["revision_evidence"]
    raw = (ARTIFACT / evidence["verification_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == evidence["verification_sha256"]
    revision = json.loads(raw)
    assert revision["base_commit"] == BASE
    assert revision["previous_prototype_commit"] == OLD_COMMIT
    assert revision["prototype_commit"] == COMMIT
    assert revision["patch_sha256"] == SHA
    assert [item["path"] for item in revision["source_files"]] == data["patch_files"]
    assert len(revision["revision_files"]) == 4
    suite = revision["guarded_tests"]
    assert suite["passed"] == evidence["passed"] == 87
    assert suite["failed"] == suite["skipped"] == 0
    assert suite["new_tests"] == evidence["new_tests"] == 17
    assert sum(item["passed"] for item in suite["files"]) == 87
    assert suite["parent_and_child_socket_guards"] is True
    assert suite["production_argv_preserved"] is True
    assert suite["child_guard_marker_and_distinct_pid_verified"] is True
    assert set(suite["guarded_operations"]) == {
        "bind",
        "listen",
        "connect",
        "connect_ex",
        "create_connection",
    }
    assert revision["static_checks"]["passed"] == evidence["static_checks_passed"] == 14
    assert revision["historical_socket_setup_failures_unresolved"] == 9
    for key in (
        "restricted_suites_retried",
        "full_upstream_suite_run",
        "live_ingress_tested",
        "remote_upstream_ci_run",
        "owner_authorization_enabled",
        "current_prototype_full_release_gate_passed",
        "regressions_demonstrated_red_before_fix",
    ):
        assert revision[key] is False


def test_patch_uses_command_only_seam_without_generic_context_import():
    patch = (ARTIFACT / "command-context-prototype.patch").read_text()
    assert "def _invoke_command(" in patch
    assert "def op_invoke_command(" in patch
    assert 'name == "handler"' in patch
    assert 'method == "register_command"' in patch
    assert "test_generic_hook_and_tool_keep_command_context_data" in patch
    assert "test_native_registration_exports_once_and_generic_call_cannot_consume" in patch
    # These strings are source inventory checks, not runtime authorization evidence.
    for suffix in ("", "-zh"):
        text = (ROOT / "docs" / f"23-host-command-context-experiment{suffix}.md").read_text()
        for marker in ("87", "17", "14", OLD_COMMIT, COMMIT, "owner_id", "TaskStore.run"):
            assert marker in text
