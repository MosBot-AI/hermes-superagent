"""Static review-bundle integrity only; never import, apply or execute upstream code."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "experiments" / "command-context"
SHA = "ab47d5f7c25c4cbc007332cb05e4f5dbf146ba701ef90cd77e09df10a5af1f20"
BASE = "90d6b98fd86d20981ee06ddd5b7d93e4320f26a4"
COMMIT = "adfb1feb207943d2bb539555adcbb667bcb571ab"


def manifest():
    return json.loads((ARTIFACT / "manifest.json").read_text())


def test_exact_patch_and_inventory():
    data = manifest()
    patch = (ARTIFACT / data["patch_file"]).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == data["patch_sha256"] == SHA
    paths = re.findall(r"^diff --git a/(\S+) b/\S+$", patch.decode(), re.M)
    assert paths == data["patch_files"]
    assert len(paths) == len(set(paths)) == data["changed_files"] == 9
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
    assert verification["patch_sha256"] == SHA
    assert verification["base_commit"] == BASE
    assert verification["prototype_commit"] == COMMIT
    assert [item["path"] for item in verification["files"]] == data["patch_files"]
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
