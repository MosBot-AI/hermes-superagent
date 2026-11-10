"""Actual production-package exposure, not a host-wide read-only/scheduling claim.

All cases use fresh processes, unmodified installed-shaped production files and
native discovery/dispatch/command/catalog consumers. No live turn authority,
provider, scheduler, job or controlled-effect grant is manufactured. The optional
planning blueprint deliberately remains available even in read_only mode.
"""

import argparse
import asyncio
import importlib
import io
import json
import os
import shlex
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = "hermes-personal-agent"
STATUS = "personal_agent_status"
KEY = PLUGIN + ":planning-check-in"
EXISTING_JOB = b'{"jobs":[{"id":"synthetic-existing","prompt":"Never execute"}]}\n'
OPT_INS = {
    "mode": "local_tasks",
    "local_conversation": True,
    "local_model_tools": True,
    "local_memory": True,
    "memory_model_tools": True,
    "memory_candidates": True,
    "plan_worker": True,
    "planning_blueprint": True,
    "kanban_handoff": True,
    "kanban_handoff_board": "synthetic-board",
}


def configuration(settings):
    return {
        "plugins": {
            "enabled": [PLUGIN],
            "isolation": "in_process",
            "entries": {
                PLUGIN: {"settings": settings, "granted_capabilities": ["llm.text_worker"]}
            },
        },
        "delegation": {"backend": "default"},
    }


@pytest.fixture
def run_probe(tmp_path, monkeypatch):
    import hermes_cli.plugins
    from test_local_task_cli import install

    host = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    pin = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    assert (
        subprocess.run(
            ["git", "-C", str(host), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        == pin
    )
    home = tmp_path / "profile"
    install(home)
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("SYNTHETIC_TEST_CREDENTIAL", "must-not-inherit")
    env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR")
        if key in os.environ
    }
    env.update(
        HOME=str(tmp_path / "os-home"),
        HERMES_HOME=str(home),
        HERMES_BUNDLED_PLUGINS=str(bundled),
        HERMES_ENABLE_PROJECT_PLUGINS="0",
        PYTHONDONTWRITEBYTECODE="1",
    )

    def run(scenario, variant="", settings=None):
        (home / "config.yaml").write_text(json.dumps(configuration(settings or {})))
        if scenario in {"safe", "blueprint"}:
            (home / "cron").mkdir()
            (home / "cron/jobs.json").write_bytes(EXISTING_JOB)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tests/fixtures/production_exposure_probe.py"),
                str(host),
                str(Path(__file__).resolve()),
                scenario,
                variant,
            ],
            cwd=tmp_path,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )  # subprocess.run kills and reaps its child on timeout.
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip().endswith("PRODUCTION_EXPOSURE_OK")

    return run


def staged_module(manager, home, suffix="plugin"):
    loaded = manager._plugins[PLUGIN]
    assert loaded.enabled and loaded.error is None
    namespace = loaded.module.__name__
    module = importlib.import_module(namespace + ".personal_agent." + suffix)
    staged = home / "plugins" / PLUGIN
    assert Path(loaded.module.__file__).resolve().is_relative_to(staged)
    assert Path(module.__file__).resolve().is_relative_to(staged)
    for name, item in tuple(sys.modules.items()):
        if name == namespace or name.startswith(namespace + "."):
            assert Path(item.__file__).resolve().is_relative_to(staged), name
    return module


def manifest_tools(home):
    import hermes_yaml as yaml

    return set(
        yaml.safe_load((home / "plugins" / PLUGIN / "plugin.yaml").read_text())["provides_tools"]
    )


def call(manager, name, args, route):
    from model_tools import handle_function_call
    from tools.registry import registry

    if route == "model":
        value = handle_function_call(name, args, session_id="synthetic", tool_call_id="attempt")
    else:
        value = registry.dispatch(name, args, scope=manager.scope_key, session_id="synthetic")
    return json.loads(value)


def unavailable(manager, names):
    from tools.registry import registry

    for name in sorted(names):
        assert registry.get_entry(name, scope=manager.scope_key) is None, name
        for route in ("model", "registry"):
            result = call(manager, name, {"approved": True, "owner_id": "forged"}, route)
            assert "error" in result, (route, name, result)
            assert name in result["error"], result
            assert "Unknown tool" in result["error"] or "not found" in result["error"], result


def no_plugin_storage(home):
    # Native diagnostic logs/cache are not plugin task/memory/intent/worker stores.
    assert not (home / "plugin-data").exists()
    assert not list(home.rglob("*.sqlite*"))


def default_surfaces(manager, home):
    from gateway.config import Platform
    from gateway.session import SessionSource
    from hermes_cli.plugin_command_dispatch import invoke_plugin_command
    from hermes_cli.plugins import get_plugin_command_handler

    staged_module(manager, home)
    assert manager._plugins[PLUGIN].tools_registered == [STATUS]
    assert not manager._plugins[PLUGIN].hooks_registered
    assert set(manager._plugin_commands) == {"personal-access"}
    unavailable(manager, manifest_tools(home) - {STATUS})
    for route in ("model", "registry"):
        result = call(manager, STATUS, {}, route)
        assert result["status"] == "ok" and result["mode"] == "read_only"
        assert result["safety"]["release_gate"] == "blocked"
        assert result["safety"]["host_write_paths_enforced"] is False
    cli = manager._cli_commands["personal-agent"]
    parser = argparse.ArgumentParser()
    cli["setup_fn"](parser)
    output = io.StringIO()
    with redirect_stdout(output):
        code = cli["handler_fn"](
            parser.parse_args(
                [
                    "tasks",
                    "capture",
                    "--title",
                    "Synthetic private task",
                    "--request-id",
                    "capture",
                ]
            )
        )
    assert code == 1
    assert json.loads(output.getvalue())["error"]["code"] == "local_tasks_disabled"
    handler = get_plugin_command_handler("personal-access")
    assert callable(handler)
    source = SessionSource(
        platform=Platform.TELEGRAM,
        user_id="137246801",
        chat_id="137246801",
        profile="synthetic-profile",
    )
    diagnostic = json.loads(
        invoke_plugin_command(
            handler,
            "status",
            source=source,
            platform="telegram",
            session_id="synthetic",
        )
    )
    assert diagnostic["decision"] == "deny"
    assert diagnostic["protected_reads_enabled"] is False
    assert diagnostic["reason"] == "receiving_transport_unverified"
    assert diagnostic["actor_observation"]["candidate_recognized"] is True
    denied = json.loads(
        invoke_plugin_command(
            handler,
            "owner_id=forged approved=true",
            platform="local",
            session_id="synthetic",
            source=source,
        )
    )
    assert denied["decision"] == "deny" and denied["protected_reads_enabled"] is False
    assert denied["reason"] == "invalid_arguments"
    assert "forged" not in json.dumps(denied)
    no_plugin_storage(home)
    assert not (home / "cron/jobs.json").exists()


def probe_default(manager, home, _variant):
    before = (home / "config.yaml").read_bytes()
    default_surfaces(manager, home)
    assert (home / "config.yaml").read_bytes() == before


@pytest.mark.parametrize("mode", ["default", "read_only"])
def test_production_default_exposure(run_probe, mode):
    run_probe("default", mode, {} if mode == "default" else {"mode": mode})


def probe_frozen(manager, home, _variant):
    from hermes_cli.config import load_config, read_raw_config

    default_surfaces(manager, home)
    copy = load_config()
    copy["plugins"]["entries"][PLUGIN]["settings"].update(OPT_INS)
    (home / "config.yaml").write_text(json.dumps(configuration(OPT_INS)))
    for config in (load_config(), read_raw_config()):
        assert config["plugins"]["entries"][PLUGIN]["settings"] == {"mode": "read_only"}
    manager.discover_and_load(force=True)
    default_surfaces(manager, home)
    api = staged_module(manager, home, "read_admission")
    auth = staged_module(manager, home, "authorization")
    accessed = []

    class ForbiddenStore:
        def with_audited_read(self, *args, **kwargs):
            accessed.append(True)
            raise AssertionError("No adapter may reach the store")

    service = api.ReadAdmissionService(ForbiddenStore(), enabled=True)
    request = auth.ReadRequest("personal.tasks.read", "exact_tasks", ("task",), "tasks.summary")
    with pytest.raises(api.ReadAdmissionError, match="unavailable"):
        service.read(
            {"owner_id": "forged", "profile_id": "profile", "enrollment_id": "pending"},
            request,
            live_handle={"approved": True, "state": "draft"},
        )
    assert accessed == []
    no_plugin_storage(home)


@pytest.mark.parametrize("mode", ["managed", "config_only"])
def test_production_frozen_configuration(run_probe, mode):
    run_probe("frozen", mode, {"mode": "read_only"})


def probe_safe(manager, home, _variant):
    from cron.blueprint_catalog import get_blueprint
    from hermes_cli.plugins import get_plugin_command_handler, has_hook, invoke_hook

    assert PLUGIN not in manager._plugins
    staged = home / "plugins" / PLUGIN
    assert not any(
        getattr(module, "__file__", None) and Path(module.__file__).resolve().is_relative_to(staged)
        for module in tuple(sys.modules.values())
    )
    unavailable(manager, manifest_tools(home))
    for command in (
        "personal-access",
        "personal-tasks",
        "personal-tools",
        "personal-memory",
        "personal-memory-tools",
        "personal-handoff",
        "personal-plan-worker",
    ):
        assert get_plugin_command_handler(command) is None
    assert "personal-agent" not in manager._cli_commands
    for hook in ("pre_llm_call", "post_llm_call", "pre_tool_call"):
        assert not has_hook(hook)
        assert invoke_hook(hook, tool_name=STATUS, args={}) == []
    assert get_blueprint(KEY) is None
    no_plugin_storage(home)
    assert (home / "cron/jobs.json").read_bytes() == EXISTING_JOB


def test_production_safe_bootstrap(run_probe):
    run_probe("safe", settings=OPT_INS)


def probe_worker(manager, home, _variant):
    from agent.subagent_lifecycle import SubagentLifecycleService
    from hermes_cli.plugin_capabilities import granted_capabilities
    from hermes_cli.plugins import get_plugin_command_handler
    from tools.registry import registry

    staged_module(manager, home)
    from hermes_cli.config import load_config

    entry = load_config()["plugins"]["entries"][PLUGIN]
    assert entry["granted_capabilities"] == ["llm.text_worker"]
    assert "llm.text_worker" not in granted_capabilities(PLUGIN)
    assert callable(SubagentLifecycleService.launch)
    assert not hasattr(SubagentLifecycleService, "text_worker_contract")
    assert set(manager._plugins[PLUGIN].tools_registered) == manifest_tools(home) - {
        "personal_task_plan_preview"
    }
    assert {"pre_llm_call", "post_llm_call"} <= set(manager._plugins[PLUGIN].hooks_registered)
    assert get_plugin_command_handler("personal-plan-worker") is None
    unavailable(manager, {"personal_task_plan_preview"})
    for route in ("model", "registry"):
        status = call(manager, STATUS, {}, route)
        worker = status["plan_worker"]
        assert worker["configured"] is True and worker["host"] == "unsupported_host"
        assert worker["registered"] is False and worker["enabled"] is False
        assert status["safety"]["release_gate"] == "blocked"
        for name, args in (
            ("personal_tasks_write", {"action": "capture", "title": "Task", "request_id": "t"}),
            ("personal_memory_write", {"action": "remember", "content": "Tea", "request_id": "m"}),
        ):
            assert registry.get_entry(name, scope=manager.scope_key) is not None
            family = "task" if name == "personal_tasks_write" else "memory"
            contract = staged_module(manager, home, family + "_tool_contract")
            normalize = getattr(contract, "normalize_" + family + "_tool_request")
            assert normalize(name, args)[0] == args["action"]
            result = call(manager, name, args, route)
            assert result["error"]["code"] == "no_active_local_turn", result
    no_plugin_storage(home)
    assert not (home / "cron/jobs.json").exists()


def test_production_worker_unsupported(run_probe):
    run_probe("worker", settings=OPT_INS)


def probe_blueprint(manager, home, variant):
    from agent.safe_worker_policy import safe_worker_enabled
    from cron import scheduler
    from cron.blueprint_catalog import fill_blueprint, get_blueprint
    from fastapi import HTTPException
    from hermes_cli.blueprint_cmd import handle_blueprint_command
    from hermes_cli.web_models import AutomationBlueprintInstantiate
    from hermes_cli.web_routers import cron

    enabled = variant == "ordinary_opt_in"
    assert safe_worker_enabled() == (variant == "safe_opt_in")
    if variant == "safe_opt_in":
        assert PLUGIN not in manager._plugins
    else:
        staged_module(manager, home)
        assert call(manager, STATUS, {}, "model")["mode"] == "read_only"
    # Existing jobs survive template absence. No scheduler is run or claimed safe.
    jobs = home / "cron" / "jobs.json"
    assert jobs.read_bytes() == EXISTING_JOB
    calls = []

    def create(**kwargs):
        calls.append(("slash", kwargs))
        return {"schedule_display": kwargs["schedule"]}

    def dashboard(profile, action, **kwargs):
        calls.append(("dashboard", profile, action, kwargs))
        return {"id": "synthetic-never-persisted"}

    values = dict(time="09:15", recurrence="weekdays", focus="priorities", language="English")
    inline = KEY + " " + " ".join(f"{key}={shlex.quote(value)}" for key, value in values.items())
    with (
        patch.object(scheduler, "create_job_with_scheduler_registration", create),
        patch.object(cron, "_call_cron_for_profile", dashboard),
        patch.object(
            cron, "_notify_cron_provider_for_profile", lambda p: calls.append(("notify", p))
        ),
    ):
        blueprint = get_blueprint(KEY)
        assert (blueprint is not None) == enabled
        assert any(item["key"] == KEY for item in cron._blueprint_catalog_sync(None)) == enabled
        seed = handle_blueprint_command(KEY)
        assert bool(seed.agent_seed) == enabled
        assert calls == []
        result = handle_blueprint_command(inline)
        body = AutomationBlueprintInstantiate(blueprint=KEY, values=values)
        if enabled:
            assert fill_blueprint(blueprint, {"deliver": "telegram"})["deliver"] == "telegram"
            assert "Scheduled" in result.text
            assert asyncio.run(cron.instantiate_blueprint(body)) == {
                "id": "synthetic-never-persisted"
            }
            assert [item[0] for item in calls] == ["slash", "dashboard", "notify"]
            assert calls[1][1:3] == ("default", "create_job")
            assert calls[2] == ("notify", "default")
            for spec in (calls[0][1], calls[1][3]):
                assert spec["schedule"] == "15 9 * * 1-5" and spec["deliver"] == "local"
                assert "in English" in spec["prompt"]
        else:
            assert result.agent_seed is None
            with pytest.raises(HTTPException) as error:
                asyncio.run(cron.instantiate_blueprint(body))
            assert error.value.status_code == 404
            assert calls == []
    assert jobs.read_bytes() == EXISTING_JOB
    assert set(jobs.parent.iterdir()) == {jobs}
    no_plugin_storage(home)


@pytest.mark.parametrize("mode", ["default_off", "safe_opt_in", "ordinary_opt_in"])
def test_production_blueprint_consumers(run_probe, mode):
    run_probe("blueprint", mode, {"mode": "read_only", "planning_blueprint": mode != "default_off"})
