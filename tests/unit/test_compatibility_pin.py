"""Current runtime and review-only candidate pins agree; history stays labeled."""

import json
import subprocess
from pathlib import Path

from personal_agent import HERMES_BASELINE
from personal_agent.native_kanban_pin import HOST_COMMIT

ROOT = Path(__file__).resolve().parents[2]


def test_current_pin_matches_runtime_and_workflow():
    expected = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    assert len(expected) == 40
    assert HERMES_BASELINE == HOST_COMMIT == expected
    workflow = (ROOT / ".github/workflows/check.yml").read_text()
    current = workflow.split("Verify gated worker on separate disposable proposed host")[0]
    assert f"fetch --depth=1 origin {expected}" in current
    for filename in ("README.md", "README-zh.md"):
        assert f"checkout --detach {expected}" in (ROOT / filename).read_text()


def test_worker_proposal_uses_current_clean_source_and_interpreter():
    manifest = json.loads((ROOT / "experiments/text-worker/manifest.json").read_text())
    expected = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    assert manifest["base"] == expected
    assert manifest["historical_evidence"]["base"] != expected
    workflow = (ROOT / ".github/workflows/check.yml").read_text()
    proposal = workflow.split("Verify gated worker on separate disposable proposed host")[1]
    proposal = proposal.split("      - name:")[0]
    assert f'worktree add --detach "$proposed" {expected}' in proposal
    assert '--clean-checkout "$RUNNER_TEMP/hermes"' in proposal
    assert '--python "$RUNNER_TEMP/hermes-test-venv/bin/python"' in proposal
    assert "proposal-test-venv" not in proposal and "legacy" not in proposal


def test_workflow_shell_fragments_parse():
    workflow = (ROOT / ".github/workflows/check.yml").read_text()
    for block in workflow.split("        run: |\n")[1:]:
        lines = []
        for line in block.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])
        subprocess.run(["bash", "-n"], input="\n".join(lines), text=True, check=True)
