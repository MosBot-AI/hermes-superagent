"""Fresh pre-import binding; bounded pipe protocol, never a full managed lifecycle."""

import json
import os
import socket
import sqlite3
import sys
from pathlib import Path

from protocol import read_frame


def deny_network(*_args, **_kwargs):
    raise AssertionError("Offline worker cannot connect")


socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
sys.path[:0] = sys.argv[1:3]
from agent.managed_worker import bind_worker_policy  # noqa: E402

safe = sys.argv[3] == "safe"
snapshot = {
    "plugins": {"enabled": ["worker-policy-probe"], "hook_callback_timeout": 0},
    "agent": {"max_turns": 7},
    "delegation": {"backend": "default"},
}
bind_worker_policy(
    {"safe_mode": safe, "ignore_user_config": safe, "policy": {"config_json": json.dumps(snapshot)}}
)
from hermes_cli.config import load_config  # noqa: E402
from hermes_cli.plugins import get_plugin_manager  # noqa: E402
from model_tools import handle_function_call  # noqa: E402
from tools.registry import registry  # noqa: E402

from personal_agent.enrollment import EnrollmentStore  # noqa: E402

# Runtime output is not protocol output. Preserve a dedicated stdout descriptor.
wire = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
sys.stdout = sys.stderr


def emit(value):
    wire.write(json.dumps(value) + "\n")


def receive():
    return read_frame(sys.stdin.fileno(), timeout=20)


manager = get_plugin_manager()
manager.discover_and_load()
loaded = manager._plugins.get("worker-policy-probe")
connection = None
try:
    if safe:
        emit(
            {
                "loaded": loaded is not None,
                "registered": registry.get_entry("worker_policy_probe") is not None,
                "registry": json.loads(registry.dispatch("worker_policy_probe", {})),
                "model": json.loads(handle_function_call("worker_policy_probe", {})),
            }
        )
    else:
        assert loaded and loaded.enabled and loaded.error is None
        probe = loaded.module
        connection = sqlite3.connect(Path(os.environ["HERMES_HOME"]) / "policy.sqlite3", timeout=10)
        probe.STORE = EnrollmentStore(connection)
        probe.STORE.initialize()
        probe.SOURCE = probe.SyntheticSource()
        emit({"ready": True, "pid": os.getpid()})
        while True:
            command = receive()
            if command["op"] == "stop":
                break
            if command["op"] == "issue":
                probe.HOST = probe.SyntheticHost(
                    command.get("revision", 1),
                    command.get("epoch", 0),
                    command.get("enrollment_revision", 1),
                )
                probe.HANDLE = probe.HOST.handle
                emit({"issued": True})
                continue
            if command["op"] == "call":
                if command.get("missing") == "host":
                    probe.HOST = None
                if command.get("missing") == "resource":
                    probe.SOURCE = None
                if command.get("hold"):

                    def hold():
                        emit({"reading": True})
                        assert receive() == {"op": "release"}

                    probe.SOURCE.on_read = hold
                if command.get("trace"):
                    connection.set_trace_callback(
                        lambda sql: emit({"begin": True}) if sql == "BEGIN IMMEDIATE" else None
                    )
                failure = command.get("failure")
                if failure:

                    def authorizer(action, arg1, arg2, database, trigger, failure=failure):
                        refused = (
                            (
                                failure == "audit"
                                and action == sqlite3.SQLITE_INSERT
                                and arg1 == "read_admissions"
                            )
                            or (
                                failure == "storage"
                                and action == sqlite3.SQLITE_READ
                                and arg1 == "enrollments"
                            )
                            or (
                                failure == "commit"
                                and action == sqlite3.SQLITE_TRANSACTION
                                and arg1 == "COMMIT"
                            )
                        )
                        return sqlite3.SQLITE_DENY if refused else sqlite3.SQLITE_OK

                    connection.set_authorizer(authorizer)
                args = {"approved": True, "state": "draft"}
                if command["path"] == "model":
                    result = handle_function_call(
                        "worker_policy_probe", args, tool_call_id="synthetic-attempt"
                    )
                else:
                    result = registry.dispatch("worker_policy_probe", args)
                connection.set_authorizer(None)
                connection.set_trace_callback(None)
                emit(
                    {
                        "result": json.loads(result),
                        "calls": probe.CALLS,
                        "reads": probe.SOURCE.reads if probe.SOURCE else 0,
                        "config": load_config()["agent"]["max_turns"],
                        "transaction": connection.in_transaction,
                        "pid": os.getpid(),
                    }
                )
finally:
    if connection:
        connection.close()
    manager.unload()
    wire.close()
