"""Actual pinned RPC server and generated client over an in-memory wire only.

No socket is opened and no execute_code sandbox is launched. Token admission,
allow-list/budget, default nested model dispatch, hooks, logs and generated client
retry are native code. Effects are the real loaded fixture's in-memory records.
"""

import json
import threading

import pytest
from test_enforcement_boundaries import TOOL_NAME
from test_enforcement_boundaries import probe as probe

TOKEN = "synthetic-rpc-token-not-a-credential"


class WireConnection:
    """The transport boundary only: fixed incoming bytes and observed responses."""

    def __init__(self, incoming):
        self.chunks = [incoming[:3], incoming[3:9], incoming[9:]]
        self.sent = []
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self, _size):
        return self.chunks.pop(0) if self.chunks else b""

    def sendall(self, payload):
        self.sent.append(payload)

    def close(self):
        self.closed = True


class WireListener:
    def __init__(self, connection):
        self.connection = connection
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def accept(self):
        return self.connection, "synthetic-peer"


def packet(*, token=TOKEN, tool=TOOL_NAME, args=None):
    return {"token": token, "tool": tool, "args": args or {}}


def serve(requests, *, token=TOKEN, allowed=None, limit=10, counter=None, log=None):
    from tools.code_execution_rpc import _rpc_server_loop

    wire = (
        b"\n".join(
            item if isinstance(item, bytes) else json.dumps(item).encode() for item in requests
        )
        + b"\n"
    )
    connection = WireConnection(wire)
    listener = WireListener(connection)
    counter = [0] if counter is None else counter
    log = [] if log is None else log
    # Deliberately omit the optional dispatch override: test the real default.
    _rpc_server_loop(
        listener,
        "synthetic-rpc-task",
        log,
        counter,
        limit,
        frozenset({TOOL_NAME} if allowed is None else allowed),
        threading.Event(),
        token,
    )
    assert listener.timeout == 0.05
    assert connection.timeout == 300
    assert connection.closed
    return [json.loads(response) for response in connection.sent], counter, log


@pytest.mark.parametrize("token", ["", "wrong-token", "非ASCII令牌"])
def test_rpc_invalid_tokens_never_reach_default_dispatch(probe, token):
    results, count, log = serve([packet(token=token)])
    assert results == [{"error": "Unauthorized RPC request"}]
    assert count == [0] and log == []
    assert probe.HOOK_CALLS == probe.MIDDLEWARE_CALLS == probe.HANDLER_CALLS == []


def test_rpc_empty_server_token_fails_closed(probe):
    results, count, log = serve([packet(token="")], token="")
    assert results == [{"error": "Unauthorized RPC request"}]
    assert count == [0] and log == []
    assert probe.HANDLER_CALLS == []


def test_rpc_framing_allowlist_and_budget_refuse_before_dispatch(probe):
    results, count, log = serve(
        [b"{broken json", packet(tool="not_available"), packet(), packet()], limit=1
    )
    assert "Invalid RPC request" in results[0]["error"]
    assert "not available in execute_code" in results[1]["error"]
    assert results[2] == {"ran": 1}
    assert "Tool call limit reached (1)" in results[3]["error"]
    assert count == [1] and len(log) == 1
    assert probe.HOOK_CALLS == probe.MIDDLEWARE_CALLS == probe.HANDLER_CALLS == [{}]
    assert TOKEN not in json.dumps(log)


@pytest.mark.parametrize("mode", ["block", "exception", "system_exit"])
def test_rpc_default_dispatch_honors_plugin_denial_and_callback_failure(probe, mode):
    from tools.code_execution_rpc import tool_errors_since

    probe.HOOK_MODE = mode
    results, count, log = serve([packet()])
    assert "error" in results[0]
    assert "synthetic policy" in results[0]["error"]
    # Native budget measures dispatched attempts, including hook denials.
    assert count == [1] and len(log) == 1
    assert tool_errors_since(log) == [{"tool": TOOL_NAME, "error": results[0]["error"]}]
    assert probe.HOOK_CALLS == [{}]
    assert probe.MIDDLEWARE_CALLS == probe.HANDLER_CALLS == []


def test_rpc_outer_dispatcher_failure_still_reaches_nested_handler(probe, monkeypatch):
    import hermes_cli.plugins as plugins

    probe.HOOK_MODE = "block"

    def broken_dispatcher(*_args, **_kwargs):
        raise RuntimeError("synthetic outer dispatcher failure")

    monkeypatch.setattr(plugins, "_dispatch_pre_tool_call_hooks", broken_dispatcher)
    results, count, log = serve([packet()])
    assert results == [{"ran": 1}]
    assert count == [1] and "error" not in log[0]
    assert probe.HOOK_CALLS == []
    assert probe.HANDLER_CALLS == [{}]


def test_rpc_identical_authenticated_requests_are_not_deduplicated(probe):
    request = packet(args={"operation": "same-synthetic-effect"})
    results, count, log = serve([request, request])
    assert results == [{"ran": 1}, {"ran": 2}]
    assert count == [2] and len(log) == 2
    assert (
        probe.HOOK_CALLS
        == probe.MIDDLEWARE_CALLS
        == probe.HANDLER_CALLS
        == [
            request["args"],
            request["args"],
        ]
    )


@pytest.mark.parametrize("persistent", [False, True], ids=["one-shot", "persistent"])
def test_generated_rpc_client_response_loss_can_replay_an_effect(probe, monkeypatch, persistent):
    """Counterexample: persistent reconnect retries after server-side completion.

    Both executions traverse the real RPC server and default dispatch. Only
    connection setup and a post-dispatch dropped response are transport doubles.
    This does not emulate the session-kernel authority-rebinding dispatcher.
    """
    from tools.code_execution_tool import _UDS_TRANSPORT_HEADER

    namespace = {}
    exec(_UDS_TRANSPORT_HEADER, namespace)
    monkeypatch.setenv("HERMES_RPC_TOKEN", TOKEN)
    monkeypatch.setenv("HERMES_RPC_PERSISTENT", "1" if persistent else "0")
    counter, log, requests, connections = [0], [], [], []

    class ClientConnection:
        def __init__(self, lose_response):
            self.lose_response = lose_response
            self.response = b""
            self.closed = False

        def sendall(self, payload):
            request = json.loads(payload)
            requests.append(request)
            results, _, _ = serve([request], counter=counter, log=log)
            self.response = json.dumps(results[0]).encode() + b"\n"

        def recv(self, _size):
            response, self.response = self.response, b""
            return b"" if self.lose_response else response

        def close(self):
            self.closed = True

    def connect():
        connection = ClientConnection(lose_response=not connections)
        connections.append(connection)
        namespace["_sock"] = connection
        return connection

    namespace["_connect"] = connect
    if persistent:
        assert namespace["_call"](TOOL_NAME, {}) == {"ran": 2}
    else:
        with pytest.raises(RuntimeError, match="Agent process disconnected"):
            namespace["_call"](TOOL_NAME, {})
    attempts = 2 if persistent else 1
    assert counter == [attempts] and len(log) == attempts
    assert probe.HOOK_CALLS == probe.HANDLER_CALLS == [{}] * attempts
    assert requests == [packet()] * attempts
    assert connections[0].closed
