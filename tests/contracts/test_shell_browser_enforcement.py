"""Native terminal/browser admission with offline synthetic backend endpoints.

The plugin loader, registry handlers, terminal pre-exec/approval guards and browser
URL scanner are real. Environment acquisition/execution and browser lifecycle are
inert substitutes: recorded effects mean reaching that boundary, not an executed
shell command, a real browser write, or proof of backend containment.
"""

import json
import os
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_enforcement_boundaries import probe as probe

COMMAND = "printf synthetic-effect"


def call(tool, args, *, direct=False):
    if direct:
        from tools.registry import registry

        result = registry.dispatch(tool, args)
    else:
        from model_tools import handle_function_call

        result = handle_function_call(tool, args)
    return json.loads(result)


@pytest.fixture
def isolated(probe, monkeypatch):
    """No subprocess or DNS can accidentally escape a substituted backend."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("shell/browser contracts must remain offline and process-free")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for key in tuple(os.environ):
        if key.startswith(("BU_", "HERMES_SESSION_")) or key.endswith(
            ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIALS")
        ):
            monkeypatch.delenv(key)
    # Real profile-local configuration, not a patched policy loader or decision.
    path = Path(os.environ["HERMES_HOME"]) / "config.yaml"
    config = json.loads(path.read_text())
    config["approvals"] = {"mode": "manual", "deny": [COMMAND]}
    config["browser"] = {"allow_private_urls": True}
    path.write_text(json.dumps(config))
    return probe


@pytest.fixture
def shell(isolated, monkeypatch, tmp_path):
    from tools import terminal_tool as terminal

    effects = []
    plan = terminal._ExecPlan(
        config={},
        env_type="local",
        effective_task_id="synthetic-shell",
        image="",
        cwd=str(tmp_path),
        host_cwd=None,
        effective_timeout=10,
    )
    monkeypatch.setattr(terminal, "_plan_execution", lambda *_a, **_k: plan)
    monkeypatch.setattr(terminal, "_acquire_env", lambda *_a, **_k: SimpleNamespace())

    def execute(command, *_args, **_kwargs):
        effects.append(command)
        return json.dumps({"output": "synthetic backend", "exit_code": 0})

    monkeypatch.setattr(terminal, "_run_foreground", execute)
    monkeypatch.setattr(isolated, "TOOL_NAME", "terminal")
    return isolated, terminal, effects


@pytest.mark.parametrize("direct", [False, True], ids=["model", "registry"])
def test_terminal_native_deny_survives_registry_and_model_force_argument(shell, direct):
    """The registry wrapper never forwards a model-supplied internal force flag."""
    probe, terminal, effects = shell
    assert "force" not in terminal.TERMINAL_SCHEMA["parameters"]["properties"]
    result = call("terminal", {"command": COMMAND, "force": True}, direct=direct)
    assert result["status"] == "blocked", result
    assert "deny" in result["error"].lower(), result
    assert effects == []
    assert len(probe.HOOK_CALLS) == (0 if direct else 1)
    allowed = "printf allowed-control"
    assert call("terminal", {"command": allowed}, direct=direct)["exit_code"] == 0
    assert effects == [allowed]


def test_terminal_internal_force_skips_approval_but_not_workdir_guard(shell):
    """Internal helper authority is distinct from the public registry argument surface."""
    probe, terminal, effects = shell
    probe.HOOK_MODE = "block"
    result = json.loads(terminal.terminal_tool(COMMAND, force=True))
    assert result["exit_code"] == 0, result
    assert effects == [COMMAND]
    refused = json.loads(terminal.terminal_tool(COMMAND, force=True, workdir="/tmp/a;b"))
    assert refused["status"] == "blocked", refused
    assert "workdir" in refused["error"]
    assert effects == [COMMAND]
    assert probe.HOOK_CALLS == []


def test_terminal_plugin_veto_does_not_cover_direct_registry(shell):
    probe, _, effects = shell
    probe.HOOK_MODE = "block"
    args = {"command": "printf permitted-synthetic-effect"}
    assert "synthetic policy denial" in call("terminal", args)["error"]
    assert effects == []
    result = call("terminal", args, direct=True)
    assert result["exit_code"] == 0, result
    assert effects == [args["command"]]
    assert probe.HOOK_CALLS == [args]


@pytest.fixture
def browser(isolated, monkeypatch, tmp_path):
    from tools import browser_use_cli as browser

    effects = []
    monkeypatch.setattr(isolated, "TOOL_NAME", "browser_exec")
    monkeypatch.setattr(browser, "_find_cli", lambda: ["synthetic-browser-never-launched"])
    monkeypatch.setattr(browser, "_base_subprocess_env", lambda: {"HOME": str(tmp_path)})
    monkeypatch.setattr(
        browser,
        "_route_exec_current",
        lambda env, *_args: (env, None, False, None),
    )
    monkeypatch.setattr(browser, "_workspace_dir", lambda *_args: None)
    for name in (
        "_attach_vault_supervisor",
        "_own_harness_daemon_until_owned",
        "_reload_if_republished",
        "_own_harness_daemon",
    ):
        monkeypatch.setattr(browser, name, lambda *_args: None)

    def execute(_cmd, code, env, _timeout):
        assert not any(key.endswith(("_API_KEY", "_TOKEN")) for key in env)
        effects.append(code)  # Never evaluate submitted Python or start any browser.
        return SimpleNamespace(returncode=0, stdout="synthetic browser effect", stderr="")

    monkeypatch.setattr(browser, "_run_cli_killing_process_group", execute)
    # Restore lifecycle tracking even though the synthetic daemon never exists.
    monkeypatch.setattr(browser, "_driven_daemons", {})
    monkeypatch.setattr(browser, "_exec_route_is_sidecar", {})
    return isolated, browser, effects


@pytest.mark.parametrize("direct", [False, True], ids=["model", "registry"])
def test_browser_metadata_literal_is_blocked_before_backend(browser, direct):
    probe, _, effects = browser
    args = {"code": 'new_tab("http://169.254.169.254/latest/meta-data/")'}
    result = call("browser_exec", args, direct=direct)
    assert "cloud metadata" in result["error"], result
    assert effects == []
    assert len(probe.HOOK_CALLS) == (0 if direct else 1)
    allowed = 'print("allowed control")'
    assert call("browser_exec", {"code": allowed}, direct=direct)["success"] is True
    assert effects == [allowed]


def test_browser_plugin_veto_and_direct_helper_boundary(browser):
    probe, native, effects = browser
    probe.HOOK_MODE = "block"
    args = {"code": 'print("synthetic action")'}
    assert "synthetic policy denial" in call("browser_exec", args)["error"]
    assert effects == []
    assert call("browser_exec", args, direct=True)["success"] is True
    assert json.loads(native.browser_exec(**args))["success"] is True
    assert effects == [args["code"], args["code"]]
    assert probe.HOOK_CALLS == [args]


def test_browser_dynamic_url_is_not_evaluated_by_literal_prescan(browser):
    """Only pre-scan coverage is claimed: the synthetic backend does not evaluate code.

    This does not establish whether a real harness/CDP layer would deny this URL.
    """
    _, _, effects = browser
    code = 'new_tab("http" + "://169.254.169.254/latest/meta-data/")'
    result = call("browser_exec", {"code": code}, direct=True)
    assert result["success"] is True, result
    assert effects == [code]
