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


def test_unobserved_crash_helper_never_consumes_rpc_reply_and_waits_for_receipt():
    import ast

    source = (ROOT / "acceptance/live/test_packaged_gateway_tasks.py").read_text()
    tree = ast.parse(source)
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "submit_unobserved_then_crash"
    )
    code = ast.get_source_segment(source, helper)
    assert code.index("await ws.send(") < code.index("await wait_for_committed_task_receipt(")
    assert code.index("await wait_for_committed_task_receipt(") < code.index("live.hard_kill(proc)")
    assert "signal.SIGKILL" in code
    assert "ws.recv" not in code and "live.ok" not in code and "live.rpc" not in code
    assert "slash.exec" in code and "jsonrpc" in code
    assert "prompt.submit" not in code
    observer = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "wait_for_committed_task_receipt"
    )
    observer_code = ast.get_source_segment(source, observer)
    assert "?mode=ro" in observer_code and "asyncio.sleep" in observer_code
    assert "deadline" in observer_code and "request_id=?" in observer_code
    assert "timeout=30" in observer_code
    for node in ast.walk(observer):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "execute":
                assert isinstance(node.args[0], ast.Constant)
                assert node.args[0].value.startswith("SELECT ")


def test_packaged_crash_recovery_uses_three_real_instances_and_no_manual_repair():
    import ast

    source = (ROOT / "acceptance/live/test_packaged_gateway_tasks.py").read_text()
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        == "test_packaged_client_unobserved_create_and_update_survive_abrupt_gateway_death"
    )
    code = ast.get_source_segment(source, function)
    assert code.count("live.daemon(") == 3
    assert code.count("submit_unobserved_then_crash(") == 2
    assert code.count("live.planned_stop(") == 1
    for evidence in (
        "session.resume",
        "idempotency_conflict",
        "revision_conflict",
        "oracle(1, 1, 1)",
        "oracle(2, 2, 2)",
        "capture_receipt",
        "update_receipt",
        "live.control_absent(home)",
        "instance_id",
    ):
        assert evidence in code
    assert "prompt.submit" not in code
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("unlink", "remove", "rmdir", "write_text", "write_bytes")
            if node.func.attr == "execute":
                assert isinstance(node.args[0], ast.Constant)
                assert node.args[0].value.startswith(("SELECT ", "PRAGMA integrity_check"))
            if node.func.attr == "connect" and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "sqlite3":
                    assert "?mode=ro" in ast.get_source_segment(source, node)


def test_packaged_memory_lifecycle_is_manual_real_transport_and_readonly_oracle():
    import ast

    workflow = (ROOT / ".github/workflows/native-gateway.yml").read_text()
    assert "acceptance/live/test_packaged_gateway_memory.py" in workflow
    source = (ROOT / "acceptance/live/test_packaged_gateway_memory.py").read_text()
    tree = ast.parse(source)
    for evidence in (
        "session.create",
        "session.resume",
        "slash.exec",
        "live.daemon(",
        "live.planned_stop(",
        "live.control_absent(",
        "instance_id",
        "proc.pid",
        "SessionDB",
        "db.append_message(",
        "db.clear_messages(",
        "source-list",
        "source-show",
        "source-preview",
        "source-retain",
        "source-status",
        "source-cursor",
        "source-discard",
        "source_suppressed",
        "independent_snapshot",
        "--expires-at",
        "--include-expired",
        "memory_store_missing",
        'status["decision"] == decision',
        'status["current"]["revision"] == 2',
        "PRAGMA integrity_check",
        "?mode=ro",
        "db.iterdump()",
    ):
        assert evidence in source
    for forbidden in ("prompt.submit", "monkeypatch", "SIGKILL", "_connection", "DELETE FROM"):
        assert forbidden not in source
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "execute":
                assert isinstance(node.args[0], ast.Constant)
                assert node.args[0].value.startswith(("SELECT ", "PRAGMA integrity_check"))
            assert node.func.attr not in ("unlink", "rmdir")


def test_pending_fixture_uses_cold_installed_sdk_not_fake_gateway_interruption():
    import ast

    source = (ROOT / "acceptance/live/test_packaged_gateway_memory.py").read_text()
    tree = ast.parse(source)
    script = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "STAGE_INSTALLED" for t in node.targets)
    )
    ast.parse(script)
    for evidence in (
        "get_plugin_manager",
        "manager.discover_and_load()",
        "loaded.module.__name__",
        "PROVENANCE.json",
        "source_commit",
        "module.__file__",
        "is_relative_to(plugin)",
        '"personal_agent" not in sys.modules',
        "storage.open_memory_backend(home, sid)",
        "LocalMemorySDK",
        "LocalBinding(namespace, sid)",
        'sdk.execute("source_stage", payload)',
    ):
        assert evidence in script
    assert '"-I"' in source and '"-B"' in source
    assert "pending fixture" in source.lower() or "pending recovery" in source.lower()
    assert "not a simulated Gateway crash" in source
    assert "sqlite3" not in script and "monkeypatch" not in script


def test_memory_configuration_is_opted_in_only_for_memory_acceptance():
    memory = (ROOT / "acceptance/live/test_packaged_gateway_memory.py").read_text()
    tasks = (ROOT / "acceptance/live/test_packaged_gateway_tasks.py").read_text()
    assert "def installed_memory(installed):" in memory
    assert '["settings"]["local_memory"] = True' in memory
    assert '"local_memory": True' not in tasks
