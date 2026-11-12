"""Check active experiment source pins without executing proposed host code."""

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = sorted((ROOT / "experiments").glob("*/manifest.json"))


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda path: path.parent.name)
def test_current_experiment_source_bindings_match_reviewed_files(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    # Only current top-level bindings: historical evidence intentionally retains
    # its original hashes and is not a claim about today's source files.
    for group, base in (
        ("source_hashes", manifest_path.parent),
        ("production_source_hashes", ROOT),
    ):
        for name, expected in manifest.get(group, {}).items():
            source = base / name
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            assert actual == expected, (
                f"{manifest_path.parent.name}: stale reviewed {group} binding for {name}; "
                "review the source change and update its manifest before host qualification"
            )
