"""Pinned persistent-kernel authority over synthetic wire/process endpoints.

No subprocess, socket or code sandbox is launched. CellAuthority, native RPC
parsing/admission/dispatch, plugin policy, cell result handling and retirement
remain native. This is not remote-kernel or complete execute_code containment.
"""

import json
import threading
import time
from types import SimpleNamespace

import pytest
from test_enforcement_boundaries import TOOL_NAME
from test_enforcement_boundaries import probe as probe
from test_nested_rpc_enforcement import TOKEN, WireConnection, WireListener, packet


def serve_kernel(kernel, requests, after_response=None):
    from tools.code_kernel import _rpc_forever

    class Connection(WireConnection):
        def sendall(self, payload):
            super().sendall(payload)
            if after_response:
                after_response(len(self.sent))

        def close(self):
            super().close()
            kernel.stop_event.set()

    connection = Connection(b"\n".join(json.dumps(p).encode() for p in requests) + b"\n")
    kernel.server_sock = WireListener(connection)
    kernel.rpc_token = TOKEN
    kernel.stop_event.clear()
    _rpc_forever(kernel, 20, frozenset({TOOL_NAME}))
    assert connection.closed
    return [json.loads(payload) for payload in connection.sent]


def new_kernel():
    from tools.code_kernel import SessionKernel

    return SessionKernel(("synthetic-owner",))


def test_persistent_rpc_current_authority_and_retirement(probe):
    from tools.code_kernel import CellAuthority

    kernel = new_kernel()
    token = probe.CELL_CONTEXT.set("cell-one")
    first = CellAuthority("task-one")
    probe.CELL_CONTEXT.set("cell-two")
    second = CellAuthority("task-two")
    probe.CELL_CONTEXT.reset(token)
    assert probe.CELL_CONTEXT.get() == "unbound"

    def advance(index):
        if index == 1:
            kernel.cell_authority = first
        elif index == 2:
            first.retire()
        elif index == 3:
            kernel.cell_authority = second
        elif index == 4:
            second.retire()

    results = serve_kernel(kernel, [packet()] * 5, advance)
    assert "no cell authority installed" in results[0]["error"]
    assert results[1] == {"ran": 1}
    assert "retired" in results[2]["error"]
    assert results[3] == {"ran": 2}
    assert "retired" in results[4]["error"]
    assert probe.HANDLER_CALLS == [{}, {}]
    assert probe.HANDLER_CONTEXTS == [("cell-one", "task-one"), ("cell-two", "task-two")]
    assert probe.CELL_CONTEXT.get() == "unbound"
    assert kernel.tool_call_counter == [5]


@pytest.mark.parametrize("mode", ["block", "exception", "system_exit"])
def test_current_cell_rpc_preserves_plugin_veto(probe, mode):
    from tools.code_kernel import CellAuthority

    kernel = new_kernel()
    kernel.cell_authority = CellAuthority("synthetic-task")
    probe.HOOK_MODE = mode
    result = serve_kernel(kernel, [packet()])[0]
    assert "synthetic policy" in result["error"]
    assert probe.HOOK_CALLS == [{}]
    assert probe.HANDLER_CALLS == probe.MIDDLEWARE_CALLS == []


@pytest.mark.parametrize(
    "outcome", ["success", "cell-error", "wire-error", "timeout", "interrupted"]
)
def test_run_cell_retires_authority_on_normal_and_error_exit(probe, monkeypatch, outcome):
    from tools.code_kernel import _run_cell

    kernel = new_kernel()
    entered_authorities = []

    class Stdin:
        def write(self, payload):
            assert json.loads(payload)["code"] == "synthetic code, never executed"
            entered_authorities.append(kernel.cell_authority)
            assert serve_kernel(kernel, [packet()]) == [{"ran": 1}]
            if outcome == "wire-error":
                raise OSError("synthetic stdin failure")
            if outcome not in {"timeout", "interrupted"}:
                kernel.response_q.put(
                    {"status": "error" if outcome == "cell-error" else "ok", "stdout": ""}
                )

        def flush(self):
            pass

    # Inert process boundary, deliberately already spawned; no _spawn is called.
    kernel.proc = SimpleNamespace(stdin=Stdin())
    teardown = []
    monkeypatch.setattr(kernel, "teardown", lambda: teardown.append(True))
    result = json.loads(
        _run_cell(
            kernel,
            kernel.key,
            "synthetic code, never executed",
            task_id="cell-task",
            child_python="unused",
            child_cwd="unused",
            sandbox_tools=frozenset({TOOL_NAME}),
            timeout=1,
            max_tool_calls=20,
            is_interrupted=lambda: outcome == "interrupted",
            exec_start=time.monotonic(),
            state_reset=False,
        )
    )
    expected = outcome if outcome in {"success", "timeout", "interrupted"} else "error"
    assert result["status"] == expected
    assert len(entered_authorities) == 1
    assert not entered_authorities[0].active
    assert "retired" in serve_kernel(kernel, [packet()])[0]["error"]
    assert probe.HANDLER_CALLS == [{}]
    assert probe.HANDLER_CONTEXTS == [("unbound", "cell-task")]
    assert teardown == ([True] if outcome in {"wire-error", "timeout", "interrupted"} else [])


def test_cell_captures_calling_context_and_restores_rpc_thread_callbacks(probe):
    from tools.code_kernel import CellAuthority
    from tools.terminal_tool import _get_approval_callback, set_approval_callback

    def caller_callback(*_args, **_kwargs):
        return False

    def worker_callback(*_args, **_kwargs):
        return False

    previous = _get_approval_callback()
    token = probe.CELL_CONTEXT.set("calling-thread")
    try:
        set_approval_callback(caller_callback)
        authority = CellAuthority("calling-task")
    finally:
        set_approval_callback(previous)
        probe.CELL_CONTEXT.reset(token)
    observed = []
    failures = []

    def rpc_thread():
        prior = _get_approval_callback()
        context_token = probe.CELL_CONTEXT.set("rpc-thread")
        try:
            set_approval_callback(worker_callback)
            observed.append(json.loads(authority.dispatch(TOOL_NAME, {})))
            observed.append(_get_approval_callback() is worker_callback)
            observed.append(probe.CELL_CONTEXT.get())
        except BaseException as exc:
            failures.append(exc)
        finally:
            set_approval_callback(prior)
            probe.CELL_CONTEXT.reset(context_token)

    worker = threading.Thread(target=rpc_thread)
    worker.start()
    worker.join(10)
    assert not worker.is_alive() and not failures
    assert observed == [{"ran": 1}, True, "rpc-thread"]
    assert probe.HANDLER_CONTEXTS == [("calling-thread", "calling-task")]
    assert probe.HANDLER_APPROVAL_CALLBACKS == [caller_callback]
    assert _get_approval_callback() is previous
    assert probe.CELL_CONTEXT.get() == "unbound"
    authority.retire()
