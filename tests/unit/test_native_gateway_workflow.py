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
    assert "path: ${{ runner.temp }}/native-gateway-evidence/*.xml" in receipt
    assert "secrets." not in workflow


def test_packaged_live_acceptance_does_not_enter_default_unit_suite():
    workflow = (ROOT / ".github/workflows/native-gateway.yml").read_text()
    assert 'scripts/build_runtime_distribution.py --source-commit "$GITHUB_SHA"' in workflow
    assert '--output-dir "$RUNNER_TEMP/live-runtime" --verify' in workflow
    assert "tests/live/test_packaged_gateway_tasks.py" in workflow
    assert 'export HERMES_SOURCE_COMMIT="$GITHUB_SHA"' in workflow
    live = (ROOT / "tests/live/test_packaged_gateway_tasks.py").read_text()
    assert '"--yes-deps",' in live and '"--enable",' in live
    assert '"prompt.submit"' not in live
    assert '"--force"' not in live and '"--allow-removed"' not in live
    assert '"session.resume"' in live and '"slash.exec"' in live
    assert '"revision_conflict"' in live
    assert 'testpaths = ["tests/unit"]' in (ROOT / "pyproject.toml").read_text()
