"""Fresh owner interpreter, native plugin host and scripted inference boundary."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

PLUGIN = "subagent-provenance-fixture"
TOOL = "fixture_subagent_provenance"
SAFE_TOOL = "fixture_child_noop"
OWNER = "fixture-parent"
OTHER = "fixture-other-parent"
GOAL = "Synthetic provenance child goal"
CHILD_REPLY = "Synthetic child result."
PARENT_REPLY = "Synthetic parent result."

PLUGIN_SOURCE = """
import json
import os
from collections.abc import Mapping

GOAL = "Synthetic provenance child goal"
TOOL = "fixture_subagent_provenance"
SAFE_TOOL = "fixture_child_noop"


def register(ctx):
    handle = None

    def provenance(args, **kw):
        nonlocal handle
        service = ctx.subagent_lifecycle
        op = args["operation"]
        result = {"operation": op, "pid": os.getpid()}
        if op == "state":
            marker = f"{ctx.profile_name}-only"
            assert ctx.state.get("scope-marker") is None, "profile state started empty"
            ctx.state.set("scope-marker", marker)
            assert ctx.state.get("scope-marker") == marker, "profile marker round-tripped"
            result["marker"] = marker
        elif op == "outside":
            assert kw["session_id"] == "fixture-parent", "dispatch metadata reached the tool"
            try:
                service.launch({"goal": GOAL})
            except ValueError as exc:
                assert "No active Hermes parent session" in str(exc), "missing parent denial"
                result["refused"] = True
        elif op == "own":
            request = {
                "goal": GOAL, "allowed_toolsets": [SAFE_TOOL], "correlation_id": "fixture-run"
            }
            try:
                service.launch(dict(request, parent_session_id="fixture-wrong-parent"))
            except ValueError as exc:
                assert "does not match the active session" in str(exc), "wrong parent denial"
                result["wrong_parent_refused"] = True
            handle_value = service.launch(request)
            handle = (dict(handle_value) if isinstance(handle_value, Mapping)
                      else handle_value.to_dict())
            assert handle["parent_session_id"] == kw["session_id"], "handle owner matches"
            assert handle["correlation_id"] == "fixture-run", "handle correlation matches request"
            assert handle["depth"] == 1 and handle["role"] == "leaf", "native child identity"
            forged = dict(handle, capability="invalid-synthetic-capability")
            denied = service.status(forged)
            assert (denied.state, denied.diagnostic) == ("UNKNOWN", "UNKNOWN_HANDLE"), "forgery"
            terminal = service.wait(handle, timeout_seconds=18)
            assert terminal.completed and terminal.state == "SUCCEEDED", "child completed"
            first, second = service.result(handle), service.result(handle)
            assert first.ready and first.terminal_state == "SUCCEEDED", "child result available"
            assert first.result_hash == second.result_hash, "stable result"
            assert len(first.result_hash) == 64, "result hash length"
            assert service.reconnect(handle).connected, "own handle reconnects"
            result.update(
                owner=handle["parent_session_id"], summary=first.summary, forged_refused=True
            )
        elif op == "foreign":
            assert handle is not None and handle["parent_session_id"] != kw["session_id"]
            status = service.status(handle)
            outcome = service.result(handle)
            reconnect = service.reconnect(handle)
            assert (status.state, status.diagnostic) == ("UNKNOWN", "UNKNOWN_HANDLE")
            assert not outcome.ready and outcome.error_classification == "UNKNOWN_HANDLE"
            assert not reconnect.connected and reconnect.diagnostic == "RECONNECT_UNAVAILABLE"
            result["refused"] = True
        return json.dumps(result)

    ctx.register_tool(
        name=TOOL, toolset=TOOL, handler=provenance,
        schema={"name": TOOL, "description": "Synthetic provenance probe.",
                "parameters": {"type": "object", "properties": {"operation": {
                    "type": "string", "enum": ["own", "foreign", "outside", "state"]}},
                    "required": ["operation"], "additionalProperties": False}})
    ctx.register_tool(
        name=SAFE_TOOL, toolset=SAFE_TOOL, handler=lambda *_args, **_kw: '{"ok":true}',
        schema={"name": SAFE_TOOL, "description": "Synthetic no-op.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False}})
"""


def install_fence():
    """Installed via sitecustomize in both the owner and its native plugin host."""
    home = os.environ["HERMES_HOME"]
    guard = Path(os.environ["HERMES_PROVENANCE_FENCE"])
    hosted = os.environ.get("HERMES_PLUGIN_HOST_PROCESS") == "1"
    allow_host = os.environ["HERMES_PROVENANCE_MODE"] == "host" and not hosted
    argv = [sys.executable, "-m", "hermes_cli.plugin_host_child"]
    profile_env = {
        name: os.environ[name]
        for name in ("HOME", "HERMES_HOME", "HERMES_RUNTIME_DIR", "HERMES_PROVENANCE_FENCE")
    }
    import_roots = {str(guard), str(Path(__file__).resolve().parent)}

    def fence(event, args):
        if event in {
            "socket.bind",
            "socket.connect",
            "socket.getaddrinfo",
            "socket.gethostbyaddr",
            "socket.gethostbyname",
            "socket.sendto",
        }:
            raise PermissionError("Provenance fixture disables sockets and DNS")
        if event == "subprocess.Popen":
            executable, arguments, cwd, env = args
            if (
                allow_host
                and executable == argv[0]
                and arguments == argv
                and cwd == home
                and isinstance(env, dict)
                and env.get("HERMES_PLUGIN_HOST_PROCESS") == "1"
                and all(env.get(key) == value for key, value in profile_env.items())
                and import_roots.issubset(env.get("PYTHONPATH", "").split(os.pathsep))
            ):
                return
            raise PermissionError("Provenance fixture only starts its native plugin host")
        if event in {"os.exec", "os.fork", "os.forkpty", "os.posix_spawn", "os.spawn", "os.system"}:
            raise PermissionError("Provenance fixture disables other process entry points")

    sys.addaudithook(fence)
    try:
        sys.audit("socket.getaddrinfo", "blocked.invalid")
    except PermissionError:
        (guard / f"active-{os.getpid()}").touch(mode=0o600)
    else:
        raise RuntimeError("Provenance fixture fence failed activation")


def stage_plugin(home, mode):
    plugin = home / "plugins" / PLUGIN
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        f"name: {PLUGIN}\nversion: 0.1.0\ndescription: Synthetic lifecycle provenance\n",
        encoding="utf-8",
    )
    (plugin / "__init__.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    config = {
        "plugins": {"enabled": [PLUGIN], "isolation": mode},
        "model": {
            "provider": "custom",
            "default": "fixture-model",
            "base_url": "http://127.0.0.1:9/v1",
            "streaming": False,
            "context_length": 64000,
        },
        "delegation": {
            "orchestrator_enabled": False,
            "inherit_mcp_toolsets": False,
            "worktree_isolation": False,
        },
        "auxiliary": {"title_generation": {"enabled": False}},
        "agent": {"api_max_retries": 1},
        "telemetry": {"shared_metrics": {"enabled": False}},
        "tools": {"tool_search": {"enabled": "off"}},
    }
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
    (home / "models_dev_cache.json").write_text(
        '{"fixture-offline":{"id":"fixture-offline","env":[],"models":{}}}', encoding="utf-8"
    )


def completion(text=None, operation=None):
    from openai.types.chat import ChatCompletion

    message = {"role": "assistant", "content": text}
    finish = "stop"
    if operation is not None:
        finish = "tool_calls"
        message["tool_calls"] = [
            {
                "id": f"fixture-{operation}",
                "type": "function",
                "function": {"name": TOOL, "arguments": json.dumps({"operation": operation})},
            }
        ]
    return ChatCompletion.model_validate(
        {
            "id": "fixture-response",
            "object": "chat.completion",
            "created": 0,
            "model": "fixture-model",
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
        }
    )


def dispatch(manager, operation):
    from tools.registry import registry

    response = registry.dispatch(
        TOOL, {"operation": operation}, scope=manager.scope_key, session_id=OWNER
    )
    return json.loads(response)


def run_turns(home, plugin_pid, manager):
    from agent.relay_runtime import resolve_plugin_sources
    from agent.subagent_lifecycle import get_active_subagent_parent
    from hermes_state import SessionDB
    from run_agent import AIAgent

    relay_config = Path(os.environ["HERMES_NEMO_RELAY_PLUGINS_TOML"]).resolve()
    sources = resolve_plugin_sources()
    assert (
        not sources.enabled
        and not sources.errors
        and {Path(path).resolve() for path in sources.config_paths} == {relay_config}
    ), "only the inactive test-owned Relay configuration may apply"

    own_result = {
        "operation": "own",
        "pid": plugin_pid,
        "owner": OWNER,
        "summary": CHILD_REPLY,
        "forged_refused": True,
        "wrong_parent_refused": True,
    }
    foreign_result = {"operation": "foreign", "pid": plugin_pid, "refused": True}
    responses = []

    def scripted(agent, api_kwargs, *, make_client):
        assert isinstance(agent, AIAgent), "the model boundary belongs to a real AIAgent"
        assert get_active_subagent_parent() is agent, "model boundary is inside the active turn"
        messages = api_kwargs["messages"]
        names = {item["function"]["name"] for item in api_kwargs.get("tools", [])}
        if agent.platform == "subagent":
            assert GOAL in str(messages[-1]["content"]), "child received the fixture goal"
            assert SAFE_TOOL in names and TOOL not in names, "selected child toolset is narrowed"
            responses.append(("child", agent.session_id, os.getpid()))
            return completion(text=CHILD_REPLY)
        assert agent.session_id in {OWNER, OTHER}, "expected an owned fixture parent"
        assert TOOL in names and SAFE_TOOL in names, "parent retained its registered tools"
        expected, operation = (
            (own_result, "own") if agent.session_id == OWNER else (foreign_result, "foreign")
        )
        if messages[-1]["role"] == "tool":
            assert json.loads(messages[-1]["content"]) == expected, "plugin returned expected proof"
            responses.append(("tool-result", agent.session_id, os.getpid()))
            return completion(text=PARENT_REPLY)
        assert messages[-1]["role"] == "user", "expected the parent prompt"
        responses.append(("parent", agent.session_id, os.getpid()))
        return completion(operation=operation)

    with (
        SessionDB(home / "state.db") as db,
        patch("agent.chat_completion_helpers._dispatch_nonstreaming_api_request", scripted),
    ):
        for sid in (OWNER, OTHER):
            agent = AIAgent(
                api_key="fixture-only",
                base_url="http://127.0.0.1:9/v1",
                provider="custom",
                api_mode="chat_completions",
                model="fixture-model",
                platform="cli",
                session_id=sid,
                session_db=db,
                enabled_toolsets=[TOOL, SAFE_TOOL],
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
                skip_background_review=True,
                cwd=os.getcwd(),
                max_iterations=5,
            )
            try:
                result = agent.run_conversation("Synthetic parent prompt.", task_id=f"task-{sid}")
                assert result.get("final_response") == PARENT_REPLY, "parent turn completed"
            finally:
                agent.close()
        assert get_active_subagent_parent() is None, "the active parent was cleared"
        assert dispatch(manager, "outside") == {
            "operation": "outside",
            "pid": plugin_pid,
            "refused": True,
        }, "tool dispatch metadata cannot stand in for a live parent"
        calls = [kind for kind, _, _ in responses]
        assert calls == ["parent", "child", "tool-result", "parent", "tool-result"], (
            "exact turn sequence"
        )
        assert all(pid == os.getpid() for _, _, pid in responses), (
            "native child executed in the owner process"
        )
        child_id = responses[1][1]
        children = db._read_all(
            "SELECT id, parent_session_id FROM sessions WHERE source = 'subagent'"
        )
        assert len(children) == 1, "only the successful operation created a native child"
        assert children[0]["id"] == child_id and children[0]["parent_session_id"] == OWNER, (
            "durable child parent"
        )
        transcript = db.get_messages(child_id)
        assert any(
            row["role"] == "assistant" and row["content"] == CHILD_REPLY for row in transcript
        ), "durable child result"


def main():
    from hermes_cli.plugins import get_plugin_manager

    home = Path(os.environ["HERMES_HOME"])
    mode = os.environ["HERMES_PROVENANCE_MODE"]
    scenario = sys.argv[1]
    guard = Path(os.environ["HERMES_PROVENANCE_FENCE"])
    assert (guard / f"active-{os.getpid()}").is_file(), "owner fence active"
    stage_plugin(home, mode)
    manager = get_plugin_manager()
    host = None
    try:
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN]
        assert loaded.enabled and loaded.error is None, "native plugin registered"
        if mode == "host":
            host = manager._running_plugin_host()
            assert host is not None and host.pid != os.getpid(), (
                "plugin process separate from owner"
            )
            plugin_pid = host.pid
            assert (guard / f"active-{plugin_pid}").is_file(), "plugin host fence active"
            assert loaded.module is None, "hosted plugin did not import in the owner"
        else:
            plugin_pid = os.getpid()
            assert manager._running_plugin_host() is None, "in-process mode uses no plugin host"
            assert loaded.module is not None, "in-process plugin imported in the owner"
        assert dispatch(manager, "state") == {
            "operation": "state",
            "pid": plugin_pid,
            "marker": f"{home.name}-only",
        }, "native profile state round-trip"
        if scenario == "turn":
            run_turns(home, plugin_pid, manager)
    finally:
        host = host or manager._running_plugin_host()
        try:
            manager.unload()
        finally:
            if host is not None:
                process = host._proc
                host.shutdown()
                assert process is not None and process.poll() is not None, "plugin host reaped"


if __name__ == "__main__":
    main()
