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
    assert "acceptance/live/test_packaged_gateway_tasks.py" in workflow
    assert 'export HERMES_SOURCE_COMMIT="$GITHUB_SHA"' in workflow
    live = (ROOT / "acceptance/live/test_packaged_gateway_tasks.py").read_text()
    assert '"--yes-deps",' in live and '"--enable",' in live
    assert '"prompt.submit"' not in live
    assert '"--force"' not in live and '"--allow-removed"' not in live
    assert '"session.resume"' in live and '"slash.exec"' in live
    assert '"revision_conflict"' in live
    assert 'testpaths = ["tests/unit"]' in (ROOT / "pyproject.toml").read_text()


def test_packaged_project_plan_command_is_explicit_chinese_and_atomic():
    import ast
    import shlex

    source = (ROOT / "acceptance/live/test_packaged_gateway_tasks.py").read_text()
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "project_plan_command"
    )
    # Evaluate only the pure command builder, not any transport/installation fixture.
    namespace = {"json": json, "shlex": shlex}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<plan-command>", "exec"), namespace)
    tokens = shlex.split(namespace["project_plan_command"]())
    assert tokens[:3] == ["personal-tasks", "--json", "plan"]
    assert tokens[tokens.index("--project") + 1] == "中文项目验收"
    assert tokens[tokens.index("--request-id") + 1] == "live-project-plan"
    tasks = json.loads(tokens[tokens.index("--tasks-json") + 1])
    assert [item["title"] for item in tasks] == ["审核中文草稿", "整理中文草稿", "确认项目记录"]
    assert tasks[0]["depends_on"] == [2] and tasks[2]["depends_on"] == [1, 2]
    assert "depends_on" not in tasks[1]


def test_packaged_project_chain_requires_real_transport_and_readonly_oracle():
    import ast

    source = (ROOT / "acceptance/live/test_packaged_gateway_tasks.py").read_text()
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_packaged_project_plan_dependencies_focus_and_restart"
    )
    code = ast.get_source_segment(source, function)
    for evidence in (
        "slash.exec",
        "session.create",
        "session.resume",
        "idempotency_conflict",
        "dependencies_unsatisfied",
        "personal-tools enable-read",
        "personal-tools focus",
        "personal-tools status",
        "personal-tools disable",
        "live-plan-stale",
        "PRAGMA integrity_check",
        "task_dependencies",
        "capture_plan",
        "completed_receipts",
    ):
        assert evidence in code
    assert code.count("live.planned_stop(") == 2
    assert code.count("live.control_absent(") == 2
    assert code.count("live.daemon(") == 2
    assert '"local_model_tools": True' in source
    assert "prompt.submit" not in code
    assert "TaskStore" not in source and "capture_plan(" not in source
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "connect" and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "sqlite3":
                    assert "?mode=ro" in ast.get_source_segment(source, node)
            if node.func.attr == "execute":
                sql = node.args[0]
                assert isinstance(sql, ast.Constant) and isinstance(sql.value, str)
                assert sql.value.startswith(("SELECT ", "PRAGMA integrity_check"))
