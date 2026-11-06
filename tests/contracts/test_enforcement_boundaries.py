"""Pinned-host failure boundaries, not a shell/MCP/browser or host-wide sandbox test.

The real loader discovers a test-only directory plugin, whose public registrations
record only in-memory effects. No manager, context, parser, registry, or config loader
is replaced. Only an escaping dispatcher exception is injected explicitly. Worker
policy probes run in fresh execs because its binding is immutable and pre-import.
Run through the pinned Hermes scripts/run_tests.sh, never bare pytest.
"""

import contextvars
import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "enforcement_probe"
PLUGIN_ID = "enforcement-probe"
TOOL_NAME = "enforcement_probe"


def stage_plugin(home):
    shutil.copytree(
        FIXTURE, home / "plugins" / PLUGIN_ID, ignore=shutil.ignore_patterns("__pycache__")
    )


def config(timeout=2.0):
    return {
        "plugins": {"enabled": [PLUGIN_ID], "hook_callback_timeout": timeout},
        "delegation": {"backend": "default"},
    }


@pytest.fixture
def probe(tmp_path, monkeypatch, request):
    home = tmp_path / "hermes-home"
    stage_plugin(home)
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "os-home")
    (home / "config.yaml").write_text(
        json.dumps(config(getattr(request, "param", 2.0))), encoding="utf-8"
    )
    from hermes_cli.plugins import get_plugin_manager

    manager = get_plugin_manager()
    manager.discover_and_load()
    loaded = manager._plugins[PLUGIN_ID]
    assert loaded.enabled and loaded.error is None
    module = loaded.module
    assert module is not None
    assert Path(module.__file__).is_relative_to(home / "plugins" / PLUGIN_ID)
    try:
        yield module
    finally:
        module.RELEASE.set()
        # The host abandons timed-out workers rather than killing them. Drain our
        # event-held workers before unloading; never leave a fixture daemon alive.
        for thread in set(module.HOOK_THREADS):
            if thread is not threading.current_thread():
                thread.join(timeout=5)
                assert not thread.is_alive(), "fixture hook worker did not finish"
        manager.unload()


def dispatch(**kwargs):
    from model_tools import handle_function_call

    return json.loads(handle_function_call(TOOL_NAME, {}, **kwargs))


@pytest.mark.parametrize("probe", [0.0, 2.0], indirect=True, ids=["inline", "bounded"])
@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("block", "synthetic policy denial"),
        ("exception", "RuntimeError: synthetic policy exception"),
        ("system_exit", "SystemExit: synthetic policy exit"),
    ],
)
def test_registered_policy_denials_and_callback_failures_stop_dispatch(probe, mode, message):
    """Explicit veto and caught callback failures block before the synthetic handler."""
    probe.HOOK_MODE = mode
    result = dispatch(tool_call_id="synthetic-policy")
    assert message in result["error"]
    assert probe.HOOK_CALLS == [{}]
    assert probe.HANDLER_CALLS == []
    assert probe.MIDDLEWARE_CALLS == []


@pytest.mark.parametrize("probe", [2.0], indirect=True)
def test_timeout_and_suppressed_retry_do_not_reach_handler(probe):
    """Timeout returns a block; its still-live callback is not started again on retry."""
    probe.HOOK_MODE = "wait"
    first = dispatch(tool_call_id="synthetic-timeout")
    # A saturated runner may deliver the timeout before scheduling the hook.
    # Wait for its rendezvous before inspecting calls or relying on teardown's join.
    assert probe.STARTED.wait(timeout=5)
    assert "timed out or is still running" in first["error"]
    second = dispatch(tool_call_id="synthetic-retry")
    assert "timed out or is still running" in second["error"]
    assert probe.HOOK_CALLS == [{}]
    assert probe.HANDLER_CALLS == []
    # Fixture teardown releases and joins the abandoned host hook worker.


@pytest.mark.parametrize("probe", [10.0], indirect=True)
def test_same_call_still_running_is_blocked_before_any_timeout(probe):
    """A second delivery of the active call id is blocked, independently of backoff."""
    probe.HOOK_MODE = "wait"
    results, failures = [], []

    def first_call():
        try:
            results.append(dispatch(tool_call_id="synthetic-active"))
        except BaseException as exc:
            failures.append(exc)

    caller = threading.Thread(target=contextvars.copy_context().run, args=(first_call,))
    caller.start()
    try:
        assert probe.STARTED.wait(timeout=5)
        second = dispatch(tool_call_id="synthetic-active")
        assert "timed out or is still running" in second["error"]
        assert probe.HOOK_CALLS == [{}]
        assert probe.HANDLER_CALLS == []
    finally:
        probe.RELEASE.set()
        caller.join(timeout=5)
        assert not caller.is_alive()
    assert failures == []
    assert results == [{"ran": 1}]
    assert probe.HANDLER_CALLS == [{}]


@pytest.mark.parametrize("mode", ["raise_before", "raise_after", "call_twice"])
def test_execution_middleware_failure_fails_open_without_replaying_handler(probe, mode):
    """An execution frame is skipped on its own failure; completed downstream runs once."""
    probe.MIDDLEWARE_MODE = mode
    assert dispatch() == {"ran": 1}
    assert probe.MIDDLEWARE_CALLS == [{}]
    assert probe.HANDLER_CALLS == [{}]


def test_escaping_hook_dispatcher_failure_is_not_a_callback_failure(probe, monkeypatch):
    """The outer dispatcher catch is fail-open, unlike PluginManager callback isolation."""
    import hermes_cli.plugins as plugins

    probe.HOOK_MODE = "block"

    def broken_dispatcher(*_args, **_kwargs):
        raise RuntimeError("synthetic outer dispatcher failure")

    monkeypatch.setattr(plugins, "_dispatch_pre_tool_call_hooks", broken_dispatcher)
    assert dispatch() == {"ran": 1}
    assert probe.HOOK_CALLS == []
    assert probe.HANDLER_CALLS == [{}]


def test_direct_registry_dispatch_has_no_plugin_hook_or_middleware_gate(probe):
    """Low-level registry.dispatch does not claim the model-facing policy pipeline."""
    from tools.registry import registry

    probe.HOOK_MODE = "block"
    assert json.loads(registry.dispatch(TOOL_NAME, {})) == {"ran": 1}
    assert probe.HOOK_CALLS == []
    assert probe.MIDDLEWARE_CALLS == []
    assert probe.HANDLER_CALLS == [{}]


@pytest.mark.parametrize("mode", ["safe", "managed", "config_only"])
def test_worker_snapshot_and_plugin_suppression_are_distinct(tmp_path, monkeypatch, mode):
    """Safe mode suppresses discovery/hooks; ordinary managed and config-only keep them."""
    import hermes_cli.plugins

    root = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    home = tmp_path / "worker-home"
    stage_plugin(home)
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    snapshot = {**config(timeout=0), "agent": {"max_turns": 7}}
    live = {"plugins": {"enabled": []}, "agent": {"max_turns": 99}}
    (home / "config.yaml").write_text(json.dumps(live), encoding="utf-8")
    script = tmp_path / "worker_probe.py"
    script.write_text(
        textwrap.dedent(f"""
        import json, os, socket, sys
        from pathlib import Path
        assert 'SYNTHETIC_TEST_CREDENTIAL' not in os.environ
        def deny_network(*_args, **_kwargs):
            raise AssertionError('Worker probe must not connect to the network')
        socket.create_connection = deny_network
        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        sys.path.insert(0, {str(root)!r})
        from agent.managed_worker import bind_worker_policy
        snapshot = {snapshot!r}
        bind_worker_policy({{
            'safe_mode': {mode == "safe"!r},
            'ignore_user_config': {mode != "managed"!r},
            'policy': {{'config_json': json.dumps(snapshot)}},
        }})
        snapshot['agent']['max_turns'] = 999
        from agent.safe_worker_policy import safe_worker_enabled
        from hermes_cli.config import load_config, read_raw_config
        from hermes_cli.plugins import get_plugin_manager, invoke_hook
        from tools.registry import registry
        manager = get_plugin_manager()
        manager.discover_and_load()
        loaded = manager._plugins.get({PLUGIN_ID!r})
        if loaded is not None:
            assert loaded.error is None
            loaded.module.HOOK_MODE = 'block'
        verdict = invoke_hook('pre_tool_call', tool_name={TOOL_NAME!r}, args={{}})
        cfg = load_config()
        first = cfg['agent']['max_turns']
        cfg['agent']['max_turns'] = 123
        Path({str(home / "config.yaml")!r}).write_text('[broken YAML', encoding='utf-8')
        print(json.dumps({{
            'safe': safe_worker_enabled(),
            'values': [first, load_config()['agent']['max_turns'],
                       read_raw_config()['agent']['max_turns']],
            'plugin_loaded': loaded is not None,
            'tool_registered': registry.get_entry({TOOL_NAME!r}) is not None,
            'verdict': verdict,
        }}))
        manager.unload()
    """),
        encoding="utf-8",
    )
    monkeypatch.setenv("SYNTHETIC_TEST_CREDENTIAL", "never-forward-this-fixture-value")
    allowed = (
        "PATH",
        "LANG",
        "LC_ALL",
        "TZ",
        "PYTHONHASHSEED",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        HOME=str(tmp_path / "os-home"),
        HERMES_HOME=str(home),
        HERMES_BUNDLED_PLUGINS=str(bundled),
        HERMES_ENABLE_PROJECT_PLUGINS="0",
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {
        "safe": mode == "safe",
        "values": [7, 7, 7],
        "plugin_loaded": mode != "safe",
        "tool_registered": mode != "safe",
        "verdict": []
        if mode == "safe"
        else [{"action": "block", "message": "synthetic policy denial"}],
    }
