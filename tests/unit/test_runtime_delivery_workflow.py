"""Delivery stays a fail-closed push artifact, not an installation or release job."""

import ast
from pathlib import Path

import pytest

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


def test_native_handoff_acceptance_is_manual_and_preserves_package_checks():
    workflow = (ROOT / ".github/workflows/native-gateway.yml").read_text()
    assert "  workflow_dispatch:" in workflow
    assert "  pull_request:" not in workflow and "  push:" not in workflow
    assert "acceptance/live/test_packaged_gateway_handoff.py" in workflow
    assert "acceptance/live/test_packaged_gateway_tasks.py" in workflow
    assert "acceptance/live/test_packaged_gateway_memory.py" in workflow
    assert '--source-commit "$GITHUB_SHA"' in workflow and "--verify" in workflow
    assert 'export HERMES_SOURCE_COMMIT="$GITHUB_SHA"' in workflow
    assert "2281116525106e3c109993ccb5dc74d02bfc1427" in workflow
    assert "continue-on-error" not in workflow and "secrets." not in workflow
    harness = (ROOT / "acceptance/live/test_packaged_gateway_handoff.py").read_text()
    assert "from test_packaged_gateway_tasks import checked, installed" in harness
    assert 'native_cli(env, "boards", "create", BOARD)' in harness
    assert '"complete", cid, "--result", RESULT' in harness
    assert '"edit", cid, "--result", CHANGED_RESULT' in harness
    assert "NOT worker execution" in harness
    for refusal in (
        "native_review_changed",
        "revision_conflict",
        "destination_changed",
        "handoff_disabled",
        "idempotency_conflict",
    ):
        assert refusal in harness


def test_handoff_oracle_distinguishes_operator_completion_from_worker_runs():
    # Extract only the pure oracle, without importing live fixtures or starting
    # any native process. Real pinned CLI setup/complete/edit is checked separately.
    path = ROOT / "acceptance/live/test_packaged_gateway_handoff.py"
    tree = ast.parse(path.read_text())
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "assert_operator_runs"
    )
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(path), "exec"), namespace)
    check = namespace["assert_operator_runs"]
    check([], card_id=None, result=None)
    check([], card_id="t_12345678", result=None)
    run = dict.fromkeys(
        (
            "profile",
            "step_key",
            "claim_lock",
            "claim_expires",
            "worker_pid",
            "worker_started_at",
            "max_runtime_seconds",
            "last_heartbeat_at",
            "metadata",
            "error",
        )
    )
    run.update(
        id=1,
        task_id="t_12345678",
        status="completed",
        outcome="completed",
        started_at=100,
        ended_at=100,
        summary="Manually authored synthetic result",
    )
    check([run], card_id=run["task_id"], result=run["summary"])
    amended = {**run, "summary": "Operator edited result"}
    check([amended], card_id=run["task_id"], result=amended["summary"])
    for rows, result in (
        ([], run["summary"]),
        ([run], None),
        ([run, run], run["summary"]),
        ([{**run, "worker_pid": 123}], run["summary"]),
        ([{**run, "claim_lock": "worker-claim"}], run["summary"]),
        ([{**run, "ended_at": None}], run["summary"]),
    ):
        with pytest.raises(AssertionError):
            check(rows, card_id=run["task_id"], result=result)
