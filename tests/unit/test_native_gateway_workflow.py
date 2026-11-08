"""Native transport acceptance is prepared but only explicitly triggered."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_lifecycle_is_manual_and_credential_free():
    workflow = (ROOT / ".github/workflows/native-gateway.yml").read_text()
    assert "on:\n  workflow_dispatch:\n" in workflow
    assert "pull_request:" not in workflow and "push:" not in workflow
    assert "permissions:\n  contents: read\n" in workflow
    assert "persist-credentials: false" in workflow
    expected = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    assert f"fetch --depth=1 origin {expected}" in workflow
    assert "--group dev --group test" in workflow
    steps = {step.split("\n", 1)[0]: step for step in workflow.split("      - name: ")[1:]}
    native = steps["Verify pinned native Gateway lifecycle without provider credentials"]
    receipt = steps["Upload synthetic native Gateway test receipt"]
    assert "timeout-minutes: 8" in native
    assert "if:" not in native and "continue-on-error" not in native
    assert "tests/gateway/test_unified_gateway_native_live.py" in native
    assert '--junitxml="$UGW_ARTIFACT_DIR/results.xml"' in native
    assert 'cd "$RUNNER_TEMP/hermes"' in native
    assert 'export HERMES_HOME="$RUNNER_TEMP/native-gateway-test-home"' in native
    assert "if: always()" in receipt
    assert "path: ${{ runner.temp }}/native-gateway-evidence/results.xml" in receipt
    assert "secrets." not in workflow
