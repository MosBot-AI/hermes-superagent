"""Delivery stays a fail-closed push artifact, not an installation or release job."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_acceptance_covers_pr_head_and_publication_is_push_only():
    workflow = (ROOT / ".github/workflows/check.yml").read_text()
    assert "permissions:\n  contents: read\n" in workflow
    assert "pull_request_target" not in workflow
    assert "  pull_request:\n" in workflow
    assert "    runs-on: ubuntu-latest\n" in workflow
    assert "          persist-credentials: false\n" in workflow
    expected = "${{ github.event.pull_request.head.sha || github.sha }}"
    assert f"          ref: {expected}\n" in workflow
    assert f"          EXPECTED_SOURCE_SHA: {expected}\n" in workflow
    check, cron_proposal, proposal, build, upload = workflow.split("      - name: ")[-5:]
    assert "scripts/check.py" in check
    assert "worktree add --detach" in cron_proposal
    assert "2281116525106e3c109993ccb5dc74d02bfc1427" in cron_proposal
    assert "apply --check" in cron_proposal and "apply --index" in cron_proposal
    assert "experiments/cron-create-requests/run_tests.py" in cron_proposal
    assert "if: " not in cron_proposal and "continue-on-error" not in cron_proposal
    assert "set -euo pipefail" in cron_proposal
    assert "worktree add --detach" in proposal
    assert "apply --check" in proposal and "apply --index" in proposal
    assert "--clean-checkout" in proposal and "--disposable-copy" in proposal
    assert "if: " not in proposal
    assert "if: " not in build
    assert "        if: github.event_name == 'push'\n" in upload
    for step in (build, upload):
        assert "continue-on-error" not in step and "always()" not in step
    assert "set -euo pipefail" in build
    assert 'test "$source_sha" = "$EXPECTED_SOURCE_SHA"' in build
    assert "git --no-replace-objects rev-parse HEAD" in build
    assert "for copy in one two" in build
    assert 'cmp "$RUNNER_TEMP/runtime-one.tar.gz" "$RUNNER_TEMP/runtime-two.tar.gz"' in build
    assert "scripts/check_runtime_distribution.py" in build
    assert '--package "$RUNNER_TEMP/runtime-extracted/hermes-personal-agent"' in build
    assert "sha256sum hermes-personal-agent.tar.gz VALIDATION.json > SHA256SUMS" in build
    assert "uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in upload
    assert "name: hermes-personal-agent-runtime-${{ github.sha }}" in upload
    assert "path: ${{ runner.temp }}/hermes-runtime-delivery/" in upload
    assert "if-no-files-found: error" in upload
    assert "retention-days: 30" in upload
    assert "install" not in build.lower()
    assert "secrets." not in workflow
