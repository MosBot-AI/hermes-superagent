"""Select and verify the exact host for a disposable native Bot reply case."""

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def verify_checkout(host, env, *, review=False, upstream=False):
    pin = json.loads((REPO / "compatibility.json").read_bytes())["hermes_commit"]
    if review or upstream:
        artifact = REPO / "experiments/bot-sender-recovery"
        if upstream:
            artifact /= "upstream"
        proposal = json.loads((artifact / "manifest.json").read_bytes())
        patch = artifact / "bot-sender-recovery.patch"
        assert proposal["status"] == "review_only"
        assert hashlib.sha256(patch.read_bytes()).hexdigest() == proposal["patch_sha256"]
        if upstream:
            pin = proposal["hermes_base"]
        else:
            assert proposal["hermes_base"] == pin

    checks = [(["rev-parse", "HEAD"], pin)]
    if review:
        checks = [
            (["show", "-s", "--format=%P", "HEAD"], pin),
            (["rev-parse", "HEAD^{tree}"], proposal["proposal_tree"]),
        ]
    checks.append((["status", "--porcelain", "--untracked-files=all"], ""))
    for args, expected in checks:
        assert (
            subprocess.check_output(
                ["git", *args], cwd=host, env=env, stdin=subprocess.DEVNULL, text=True, timeout=10
            ).strip()
            == expected
        )
    return pin
