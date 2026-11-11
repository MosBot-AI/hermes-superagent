"""Cold installed-shaped production entrypoint tests, separate from clean-host baseline.

Uses prepared disposable hosts, copied public contract fixtures and synthetic
MockTransport. Never modifies either host, installs anything or calls a provider.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2]
WORKSPACE = SOURCE.parent
HOSTS = {
    "clean": WORKSPACE / "hermes-superagent-test" / "hermes-agent",
    "patched": WORKSPACE / "hermes-text-worker-prototype",
}

EXTRA_TESTS = """
@pytest.mark.parametrize("case", ["off", "missing", "wrong", "unconsented"])
def test_production_gate_keeps_ordinary_features(native, monkeypatch, case):
    from agent.subagent_lifecycle import SubagentLifecycleService
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    entry = config["plugins"]["entries"][PLUGIN_ID]
    entry["settings"].update(local_model_tools=True, plan_worker=case != "off")
    entry["granted_capabilities"] = [] if case == "unconsented" else ["llm.text_worker"]
    if case == "missing":
        monkeypatch.delattr(SubagentLifecycleService, "text_worker_contract", raising=False)
    elif case == "wrong":
        monkeypatch.setattr(SubagentLifecycleService, "text_worker_contract",
                            property(lambda self: "hermes.text-worker.v0"), raising=False)
    (home / "config.yaml").write_text(json.dumps(config))
    def load(manager):
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        assert loaded.error is None, loaded.error
        assert "personal-plan-worker" not in manager._plugin_commands
        assert "personal_task_plan_preview" not in loaded.tools_registered
        assert "personal_tasks_read" in loaded.tools_registered
        assert "personal-tasks" in manager._plugin_commands
    monkeypatch.setattr("test_local_conversation_tasks.load", load)
    active = make_host(home, manager)
    result = command(active, 'add "Ordinary task" --request-id ordinary')
    assert result["status"] == "ok", result
    assert result["data"]["title"] == "Ordinary task"
    assert not (home / "plugin-data" / PLUGIN_ID / "plan-worker").exists()


def test_production_consent_revoked_before_launch(host):
    allow(host)
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["granted_capabilities"] = []
    (host.home / "config.yaml").write_text(json.dumps(config))
    with native_turn(host):
        result = invoke(host)
        assert result["status"] == "error", result
    assert host.requests == []


def test_production_projection_excludes_ungranted_metadata(host, monkeypatch):
    original = host.consumer._task
    def selected(task_id):
        return {**original(task_id), "progress_note": "EXCLUDED_PROGRESS_NOTE",
                "dependencies": [{"title": "EXCLUDED_PREREQUISITE"}],
                "native_progress": {"output": "EXCLUDED_NATIVE_OUTPUT"},
                "future_private_field": "EXCLUDED_FUTURE_FIELD"}
    monkeypatch.setattr(host.consumer, "_task", selected)
    allow(host)
    with native_turn(host):
        assert invoke(host)["status"] == "ok"
        assert wait(host).completed
        assert invoke(host, action="result")["data"]["draft"]
    wire = json.dumps(host.requests)
    for secret in ("EXCLUDED_PROGRESS_NOTE", "EXCLUDED_PREREQUISITE", "EXCLUDED_NATIVE_OUTPUT",
                   "EXCLUDED_FUTURE_FIELD", "EXCLUDED_PARENT_HISTORY"):
        assert secret not in wire
    for field in ("progress_note", "dependencies", "native_progress", "future_private_field"):
        assert field not in wire
    assert "Selected details" in wire


def test_production_unknown_claim_survives_reload_without_duplicate(host, monkeypatch):
    allow(host)
    launch = host.consumer.service.launch_text
    def lose_reply(request):
        handle = launch(request)
        assert host.consumer.service.wait(handle, timeout_seconds=5).completed
        raise RuntimeError("Synthetic response lost after submission")
    monkeypatch.setattr(host.consumer.service, "launch_text", lose_reply)
    with native_turn(host):
        assert invoke(host)["error"]["code"] == "worker_unavailable"
    assert len(host.requests) == 1
    host.manager.discover_and_load(force=True)
    host.consumer = host.manager._plugin_commands["personal-plan-worker"]["handler"].__self__
    assert direct(host, host.consumer)["data"]["state"] == "launch_outcome_unknown"
    assert direct(host, host.consumer, "result")["data"]["state"] == "launch_outcome_unknown"
    assert len(host.requests) == 1


@pytest.mark.parametrize("fail_on_read", [1, 4])
@pytest.mark.parametrize("state", ["pending", "completed"])
def test_production_config_backend_outage_fails_closed(host, monkeypatch, fail_on_read, state):
    from hermes_cli import plugins
    from hermes_cli.config_backend import ConfigBackendUnavailable
    allow(host)
    if state == "completed":
        with native_turn(host):
            assert invoke(host)["status"] == "ok"
            assert wait(host).completed
            assert invoke(host, action="result")["data"]["draft"]
    original = plugins.load_config_readonly
    reads = []
    def unavailable():
        reads.append(1)
        if len(reads) == fail_on_read:
            raise ConfigBackendUnavailable("synthetic-private-outage")
        return original()
    monkeypatch.setattr(plugins, "load_config_readonly", unavailable)
    # Call the installed-shaped consumer directly: the upstream dispatcher has
    # independent config reads before this candidate can receive the operation.
    result = direct(host, host.consumer, "launch" if state == "pending" else "result")
    assert result["status"] == "error" and result["data"] is None
    assert result["error"]["code"] == "worker_unavailable"
    assert "synthetic-private-outage" not in json.dumps(result)
    monkeypatch.setattr(plugins, "load_config_readonly", original)
    if state == "pending":
        assert all(grant.state == "revoked" for grant in host.consumer.grants.values())
        assert direct(host, host.consumer)["data"]["state"] == "revoked"
        host.manager.discover_and_load(force=True)
        host.consumer = host.manager._plugin_commands["personal-plan-worker"]["handler"].__self__
        assert direct(host, host.consumer)["data"]["state"] == "revoked"
    else:
        assert direct(host, host.consumer, "result")["data"]["draft"]
    assert len(host.requests) == (state == "completed")


def test_isolated_plugin_remote_facade_remains_unsupported(host):
    import importlib
    from hermes_cli.plugin_host_child import RemotePluginContext
    consumer = importlib.import_module(type(host.consumer).__module__)
    plugin = importlib.import_module(consumer.__package__ + ".plugin")
    calls = []
    class Runtime:
        def facade_call(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("Static host-contract refusal must precede RPC")
    remote = RemotePluginContext(Runtime(), PLUGIN_ID, {"plugin_id": PLUGIN_ID})
    service = remote.subagent_lifecycle
    with pytest.raises(consumer.TaskError, match="plan_worker_host_unsupported"):
        consumer.require_host_contract(service)
    assert plugin.plan_worker_host_status(remote) == "unsupported_host"
    assert not calls


def test_clean_host_explicit_opt_in_never_registers(native, monkeypatch):
    from agent.subagent_lifecycle import SubagentLifecycleService
    assert not hasattr(SubagentLifecycleService, "text_worker_contract")
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    entry = config["plugins"]["entries"][PLUGIN_ID]
    entry["settings"].update(local_model_tools=True, plan_worker=True)
    entry["granted_capabilities"] = ["llm.text_worker"]
    (home / "config.yaml").write_text(json.dumps(config))
    def load(manager):
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        assert loaded.error is None, loaded.error
        assert "personal-plan-worker" not in manager._plugin_commands
        assert "personal_task_plan_preview" not in loaded.tools_registered
        assert "personal_tasks_read" in loaded.tools_registered
    monkeypatch.setattr("test_local_conversation_tasks.load", load)
    make_host(home, manager)


def test_production_module_origins(host):
    import importlib
    consumer = importlib.import_module(type(host.consumer).__module__)
    ledger = importlib.import_module(type(host.consumer.ledger).__module__)
    assert consumer.__name__.endswith(".personal_agent.task_plan_worker")
    assert ledger.__name__.endswith(".personal_agent.task_worker_ledger")
    tasks = importlib.import_module(consumer.__package__ + ".tasks")
    assert consumer.TaskError is ledger.TaskError is tasks.TaskError
    root = host.home / "plugins" / PLUGIN_ID
    for module in (consumer, ledger, tasks):
        assert Path(module.__file__).resolve().is_relative_to(root.resolve())
    assert not (root / "worker_consumer.py").exists()
"""

BOOTSTRAP = """
import importlib.abc, pathlib, socket, sys
host, harness, source, lane = sys.argv[1:]
source = pathlib.Path(source)
sys.path[:0] = [host, harness]
assert not any(pathlib.Path(p or ".").resolve() == source for p in sys.path)
class NoGlobalPackage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "personal_agent" or fullname.startswith("personal_agent."):
            raise AssertionError("Production package cannot borrow global repository imports")
sys.meta_path.insert(0, NoGlobalPackage())
def deny(*args, **kwargs):
    raise AssertionError("No socket, provider or Gateway I/O")
for name in ("connect", "connect_ex", "bind", "listen", "sendto", "sendmsg"):
    if hasattr(socket.socket, name): setattr(socket.socket, name, deny)
socket.getaddrinfo = deny
import pytest
selection = "test_production_gate_keeps_ordinary_features"
if lane == "clean":
    selection += " or test_clean_host_explicit_opt_in_never_registers"
if lane == "patched":
    selection += (" or test_production_module_origins"
      " or test_isolated_plugin_remote_facade_remains_unsupported"
      " or test_production_config_backend_outage_fails_closed"
      " or test_production_consent_revoked_before_launch"
      " or test_production_projection_excludes_ungranted_metadata"
      " or test_production_unknown_claim_survives_reload_without_duplicate"
      " or test_native_task_grant_to_real_host_worker_and_draft_without_task_mutation"
      " or test_observed_draft_survives_plugin_reload"
      " or test_no_native_grant_means_no_worker"
      " or test_grant_does_not_cross_native_turn_boundary"
      " or test_host_route_refusal_before_claim_sends_no_data"
      " or test_configuration_revoke_prevents_task_dispatch"
      " or test_unload_revokes_retained_consumer"
      " or test_live_and_persisted_drafts_never_cross_changed_model_route")
result = pytest.main([str(pathlib.Path(harness)/"test_production_flow.py"),
                     "-q", "--tb=short", "-k", selection])
assert "personal_agent" not in sys.modules
assert not any(pathlib.Path(p or ".").resolve() == source for p in sys.path)
raise SystemExit(result)
"""


@pytest.mark.parametrize("lane", ["clean", "patched"])
def test_cold_production_entrypoint(tmp_path, lane):
    host = Path(os.environ.get("HERMES_" + lane.upper() + "_TEST_HOST", HOSTS[lane]))
    assert (host / "hermes_cli/plugins.py").is_file(), (
        "Prepared host required; no install attempted"
    )
    harness = tmp_path / "harness"
    harness.mkdir()
    for name in ("test_local_task_cli", "test_local_conversation_tasks", "test_session_task_tools"):
        content = (SOURCE / "tests/contracts" / (name + ".py")).read_text()
        if name == "test_local_task_cli":
            content = content.replace(
                "PLUGIN_ROOT = Path(__file__).resolve().parents[2]",
                "PLUGIN_ROOT = Path(" + repr(str(SOURCE)) + ")",
            )
        (harness / (name + ".py")).write_text(content)
    content = (SOURCE / "experiments/text-worker/test_task_worker.py").read_text()
    start = content.index('    plugin = home / "plugins" / PLUGIN_ID\n')
    end = content.index("    def load(manager):", start)
    # Remove all experimental payload copies and appended registration. The actual
    # shipped __init__/plugin.py must be sufficient; only synthetic config differs.
    content = content[:start] + content[end:]
    content = content.replace(
        "return type(old)(service=old.service, bound_home=old.bound_home, "
        "read_config=old.read_config)",
        "return type(old)(service=old.service, bound_home=old.bound_home, "
        "read_config=old.read_config, check_capability=old.check_capability)",
    )
    content = content.replace("experimental_text_worker", "plan_worker")
    content = content.replace("experimental_worker_disabled", "plan_worker_disabled")
    (harness / "test_production_flow.py").write_text(content + EXTRA_TESTS)
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(tmp_path / "home"),
        "HERMES_HOME": str(tmp_path / "profile"),
        "HERMES_RUNTIME_DIR": str(tmp_path / "runtime"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", BOOTSTRAP, str(host), str(harness), str(SOURCE), lane],
        cwd=harness,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(f"{lane} isolated production lane:\n{result.stdout}")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout and "skipped" not in result.stdout
