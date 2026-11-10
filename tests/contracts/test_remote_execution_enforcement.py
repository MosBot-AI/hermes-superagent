"""Native remote RPC/fallback boundaries over inert transport and kernel endpoints.

No shell, remote filesystem, sandbox or model is used. Synthetic handler records
are the effect oracle; these tests do not establish exactly-once remote effects.
"""

import json
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from test_enforcement_boundaries import TOOL_NAME
from test_enforcement_boundaries import probe as probe
from test_nested_rpc_enforcement import TOKEN, packet


def poll(monkeypatch, requests, *, limit=10, fail_first_write=False):
    from tools import code_execution_rpc as rpc

    stop = threading.Event()
    files = {f"/synthetic/rpc/req_{i:06d}": raw for i, raw in enumerate(requests)}
    writes, commands, attempts, count, log = [], [], [], [0], []

    def execute(command, **_kwargs):
        commands.append(command)
        assert len(commands) < 50, "poll loop did not terminate"
        if command.startswith("ls "):
            if not files:
                stop.set()
            return {"output": "\n".join(files)}
        if command.startswith("cat "):
            raw = files[command[4:]]
            return {"output": raw if isinstance(raw, str) else json.dumps(raw)}
        assert command.startswith("rm -f ")
        files.pop(command[6:])
        return {"output": ""}

    def write(_env, path, result, **kwargs):
        attempts.append(path)
        assert kwargs == {"atomic": True, "timeout": 60}
        if fail_first_write and len(attempts) == 1:
            raise OSError("synthetic response transport failure")
        writes.append((path, json.loads(result)))

    monkeypatch.setattr(rpc, "_remote_write", write)
    rpc._rpc_poll_loop(
        SimpleNamespace(execute=execute),
        "/synthetic/rpc",
        "remote-task",
        log,
        count,
        limit,
        frozenset({TOOL_NAME}),
        stop,
        TOKEN,
    )
    assert files == {}
    return writes, count, log, attempts


@pytest.mark.parametrize(
    "raw_request", ["{broken", packet(token="wrong"), {**packet(), "seq": "1"}]
)
def test_remote_poll_invalid_requests_removed_without_effect(probe, monkeypatch, raw_request):
    writes, count, log, attempts = poll(monkeypatch, [raw_request])
    assert writes == attempts == log == [] and count == [0]
    assert probe.HOOK_CALLS == probe.MIDDLEWARE_CALLS == probe.HANDLER_CALLS == []


def test_remote_poll_allowlist_budget_and_success(probe, monkeypatch):
    requests = [
        {**packet(tool="not_available"), "seq": 0},
        {**packet(), "seq": 1},
        {**packet(), "seq": 2},
    ]
    writes, count, log, _ = poll(monkeypatch, requests, limit=1)
    assert "not available in execute_code" in writes[0][1]["error"]
    assert writes[1] == ("/synthetic/rpc/res_000001", {"ran": 1})
    assert "Tool call limit reached (1)" in writes[2][1]["error"]
    assert count == [1] and len(log) == 1
    assert probe.HANDLER_CALLS == [{}]
    assert TOKEN not in json.dumps(log)


@pytest.mark.parametrize("mode", ["block", "exception", "system_exit"])
def test_remote_poll_plugin_denial_prevents_effect(probe, monkeypatch, mode):
    probe.HOOK_MODE = mode
    writes, count, log, _ = poll(monkeypatch, [{**packet(), "seq": 1}])
    assert "synthetic policy" in writes[0][1]["error"]
    assert count == [1] and len(log) == 1
    assert probe.HOOK_CALLS == [{}]
    assert probe.HANDLER_CALLS == probe.MIDDLEWARE_CALLS == []


def test_remote_response_failure_can_replay_effect(probe, monkeypatch):
    writes, count, log, attempts = poll(
        monkeypatch,
        [{**packet(), "seq": 1}],
        fail_first_write=True,
    )
    assert attempts == ["/synthetic/rpc/res_000001"] * 2
    assert writes == [("/synthetic/rpc/res_000001", {"ran": 2})]
    assert count == [2] and len(log) == 2
    assert probe.HANDLER_CALLS == [{}, {}]


@pytest.mark.parametrize("outcome", ["success", "error", "unavailable", "raise", "no-python"])
def test_remote_kernel_fallback_selection(monkeypatch, outcome):
    from tools import code_execution_tool as code
    from tools import code_kernel_remote as kernel
    from tools import terminal_tool, terminal_tool_lifecycle

    kernel_calls, fallback_calls, commands = [], [], []

    def execute(command, **_kwargs):
        commands.append(command)
        return {"output": "" if outcome == "no-python" else "OK"}

    env = SimpleNamespace(execute=execute)
    monkeypatch.setattr(code, "_load_config", lambda: {"timeout": 7, "max_tool_calls": 3})
    monkeypatch.setattr(code, "_get_or_create_env", lambda _task: (env, "synthetic"))
    monkeypatch.setattr(code, "_sandbox_tools_for", lambda _tools: frozenset({TOOL_NAME}))
    monkeypatch.setattr(terminal_tool, "_resolve_container_task_id", lambda task: task)
    monkeypatch.setattr(terminal_tool_lifecycle, "_call_in_flight", lambda _task: nullcontext())

    def run_kernel(source, **kwargs):
        kernel_calls.append((source, kwargs))
        if outcome == "raise":
            raise RuntimeError("synthetic kernel failure")
        if outcome == "unavailable":
            return None
        return {"status": outcome, "output": "synthetic cell", "tool_calls_made": 0}

    def run_fallback(*args, **kwargs):
        fallback_calls.append((args, kwargs))
        return json.dumps({"status": "synthetic-fallback"})

    monkeypatch.setattr(kernel, "execute_in_remote_kernel", run_kernel)
    monkeypatch.setattr(code, "_run_remote_per_call", run_fallback)
    result = json.loads(code._execute_remote("synthetic source", "remote-task", [TOOL_NAME], True))
    assert len(commands) == 1
    if outcome == "no-python":
        assert "Python 3 is not available" in result["error"]
        assert kernel_calls == fallback_calls == []
        return
    assert len(kernel_calls) == 1
    args = kernel_calls[0][1]
    assert args["task_env_id"] == "remote-task" and args["reset"] is True
    assert args["sandbox_tools"] == frozenset({TOOL_NAME})
    assert args["timeout"] == 7 and args["max_tool_calls"] == 3
    if outcome in {"raise", "unavailable"}:
        assert result["status"] == "synthetic-fallback" and len(fallback_calls) == 1
        assert fallback_calls[0][0] == (
            env,
            "synthetic",
            "synthetic source",
            "remote-task",
            frozenset({TOOL_NAME}),
        )
        assert fallback_calls[0][1]["timeout"] == 7
        assert fallback_calls[0][1]["max_tool_calls"] == 3
    else:
        assert result["status"] == outcome and fallback_calls == []
