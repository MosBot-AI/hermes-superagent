"""Artifact integrity only; real host tests require the explicit experiment runner."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "experiments/cron-create-requests"


def test_cron_create_proposal_integrity_and_nonactivation():
    manifest = json.loads((ARTIFACT / "manifest.json").read_text())
    assert manifest["base"] == "2281116525106e3c109993ccb5dc74d02bfc1427"
    assert manifest["production_activated"] is False
    assert manifest["submitted_upstream"] is False
    assert manifest["live_model_calls"] is False
    assert manifest["external_delivery"] is False
    assert sorted(p.name for p in ARTIFACT.iterdir() if p.is_file()) == manifest["artifact_files"]
    patch = (ARTIFACT / manifest["patch_file"]).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == manifest["patch_sha256"]
    files = re.findall(rb"^diff --git a/(\S+) b/(\S+)$", patch, re.M)
    assert [a.decode() for a, b in files if a == b] == manifest["patch_files"]
    assert len(files) == manifest["changed_files"]
    for name, digest in manifest["source_hashes"].items():
        assert hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest() == digest
    assert "cron-create-requests" not in (ROOT / "packaging/runtime-files.json").read_text()
    assert (
        json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"] == manifest["base"]
    )
