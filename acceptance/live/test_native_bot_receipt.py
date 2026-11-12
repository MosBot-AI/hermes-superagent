"""Manual acceptance of a native Bot reply across an owned Gateway restart."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon

ROOT = Path(__file__).resolve().parents[2]
NOTICE = "Synthetic Bot restart receipt"
MESSAGE = f"Message from 🤖 Scout Fixture (@scout): [no reply needed] {NOTICE}"
AUTHOR = {"id": "bot:scout", "name": "scout", "is_bot": True}
REPLY = "Synthetic loopback Bot result."
MODEL = "local-wire-stub"
MODEL_KEY = "loopback-only"
MODEL_METADATA_PATHS = {
    "/api/v1/models",
    "/api/tags",
    "/v1/props",
    "/props",
    "/version",
    "/v1/models",
    "/models",
}


class SyntheticModel(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if (
            self.path not in MODEL_METADATA_PATHS
            or self.headers.get("Content-Length") not in (None, "0")
            or self.headers.get("Authorization") not in (None, f"Bearer {MODEL_KEY}")
        ):
            self.server.requests.append("unexpected GET")
        self.send_error(404)

    def send_error(self, code, *args):
        if code == 501:
            self.server.requests.append("unsupported model HTTP method")
        super().send_error(code, *args)

    def do_POST(self):
        self.connection.settimeout(5)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError
            body = json.loads(self.rfile.read(length))
        except ValueError, OSError:
            self.server.requests.append("malformed POST")
            self.send_error(400)
            return

        authorization = self.headers.get("Authorization")
        if (
            self.path == "/api/show"
            and body == {"name": MODEL}
            and authorization in (None, f"Bearer {MODEL_KEY}")
        ):
            self.send_error(404)
            return
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list):
            messages = []
        last_user = next(
            (
                message.get("content")
                for message in reversed(messages)
                if isinstance(message, dict) and message.get("role") == "user"
            ),
            "",
        )
        is_completion = (
            self.path == "/v1/chat/completions"
            and bool(messages)
            and body.get("model") == MODEL
            and "input" not in body
            and authorization == f"Bearer {MODEL_KEY}"
            and MESSAGE in json.dumps(last_user, ensure_ascii=False)
        )
        if not is_completion:
            self.server.requests.append("unexpected POST")
            self.send_error(400)
            return
        self.server.requests.append("chat completion")
        reply = {"role": "assistant", "content": REPLY}
        choice = {"index": 0, "message": reply, "finish_reason": "stop"}
        frame = {"id": "synthetic", "model": MODEL, "choices": [choice]}
        content_type = "application/json"
        if body.get("stream"):
            choice["delta"] = choice.pop("message")
            payload = ("data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n").encode()
            content_type = "text/event-stream"
        else:
            payload = json.dumps(frame).encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def synthetic_model():
    with ThreadingHTTPServer(("127.0.0.1", 0), SyntheticModel) as server:
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def notify(sender_home):
    from agent.tool_executor import _resolve_sequential_dispatch, _ToolCallRef
    from hermes_state import SessionDB
    from tools.bot_mode_dm import ensure_message_agent_tool

    with closing(SessionDB(sender_home / "state.db")) as db:
        db.create_session("scout-bot", source="local", user_id="synthetic-scout-owner")
        assert db.set_session_title("scout-bot", "Bot Chat")
        agent = SimpleNamespace(
            _session_db=db,
            session_id="scout-bot",
            _bot_mode_protocol=True,
            tools=[],
            valid_tool_names=set(),
        )
        assert ensure_message_agent_tool(agent)
        call = _ToolCallRef(
            "message_agent",
            {"target": "@hermes", "message": NOTICE, "expects_reply": False},
            "synthetic-bot-task",
            "bot-call",
            [],
        )
        return json.loads(_resolve_sequential_dispatch(agent, call, []).execute(call.args))


async def create_and_send(endpoint, home, sender_home):
    from hermes_cli.gateway_client import connect_gateway
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    url = endpoint.api_origin.replace("http:", "ws:", 1) + "/api/ws"
    with pytest.raises(InvalidStatus):
        async with connect(url, open_timeout=8, proxy=None):
            pass
    async with asyncio.timeout(15), connect_gateway(endpoint=endpoint) as client:
        created = await client.rpc(
            "session.create",
            request_id="native-bot-receipt",
            title="Bot Chat",
            source="gui",
            cwd=str(home),
            hidden=True,
            toolsets=[],
        )
    accepted = await asyncio.to_thread(notify, sender_home)
    assert accepted["status"] in {"queued", "claimed", "settled"}
    assert accepted["to"] == "@hermes" and accepted["expects_reply"] is False
    assert not {"error", "notification_error", "process_id", "reply"}.intersection(accepted)
    return {
        "id": accepted["delivery_id"],
        "profile": "default",
        "session_id": created["session_id"],
        "message": MESSAGE,
        "author": AUTHOR,
    }


def settled_receipt(home, params):
    from gateway.session_results import admission_result
    from hermes_state import SessionDB
    from hermes_state_runtime import list_session_admissions

    path = home / "runtime" / "bot_live_delivery" / f"{params['id']}.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if path.is_file():
            receipt = json.loads(path.read_bytes())
            if receipt["status"] in {"settled", "failed", "ambiguous", "cancelled"}:
                # A pin can be briefly ambiguous before its admission id is committed.
                if receipt["status"] != "ambiguous" or receipt.get("admission_id"):
                    break
        time.sleep(0.1)
    else:
        pytest.fail("No committed Bot receipt within the deadline", pytrace=False)
    assert receipt["status"] == "settled"
    assert receipt["delivery_id"] == params["id"] and receipt["session_id"] == params["session_id"]
    assert receipt["profile_home"] == str(home) and receipt["principal_id"] == f"uid:{os.getuid()}"
    assert receipt["message"] == MESSAGE and receipt["author"] == AUTHOR
    assert receipt["reply"] == REPLY and "retry_admission_id" not in receipt
    assert list(path.parent.glob("*.json")) == [path]
    with closing(SessionDB(home / "state.db", read_only=True)) as db:
        (row,) = list_session_admissions(db, session_id=params["session_id"], pending_only=False)
        assert (row["admission_id"], row["request_id"], row["status"], row["outcome"]) == (
            receipt["admission_id"],
            f"bot:{params['id']}",
            "terminal",
            "completed",
        )
        assert row["payload"]["local_automation_v1"]["turn_author"] == AUTHOR
        assert row["payload"]["text"] == MESSAGE
        saved = admission_result(db, row["admission_id"])["result"]
        assert saved["final_response"] == REPLY
        assert db.get_session(params["session_id"])["hidden"]
        with db._read_ctx() as conn:
            assert conn.execute("SELECT COUNT(*) FROM session_admissions").fetchone()[0] == 1
    return path, receipt, row


def refuse_old_instance(home, instance_id):
    from hermes_cli.gateway_client import private_control_query

    request = {
        "protocol": 1,
        "id": 1,
        "verb": "session-ticket",
        "params": {
            "profile_id": str(home),
            "instance_id": instance_id,
            "purpose": "interactive",
        },
    }
    refusal = json.loads(
        private_control_query(home, json.dumps(request).encode() + b"\n", timeout=3)
    )
    assert refusal["ok"] is False and not refusal.get("result")
    assert refusal["error"] == "PermissionError: stale runtime instance"


async def replay(endpoint, params, admission_id):
    from hermes_cli.gateway_client import GatewayRPCError, connect_gateway

    async with asyncio.timeout(15), connect_gateway(endpoint=endpoint) as client:
        result = await client.rpc("bot_relay.deliver", **params)
        assert result["status"] == "settled" and result["admission_id"] == admission_id
        assert result["delivery_id"] == params["id"] and result["reply"] == REPLY
        with pytest.raises(GatewayRPCError, match="^admission_conflict$"):
            await client.rpc(
                "bot_relay.deliver", **(params | {"message": "Changed synthetic notice"})
            )


def test_native_named_bot_reply_repairs_stale_receipt_on_restart(tmp_path_factory, monkeypatch):
    assert sys.platform == "linux", "This acceptance lane uses the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((ROOT / "compatibility.json").read_bytes())["hermes_commit"]
    root = tmp_path_factory.mktemp("bot")
    root.chmod(0o700)
    home, user, scratch, runtime, xdg, bundled, guard = (
        root / name for name in ("home", "user", "tmp", "runtime", "xdg", "bundled", "guard")
    )
    for directory in (home, user, scratch, runtime, xdg, bundled, guard):
        directory.mkdir(mode=0o700)
    assert len(os.fsencode(home / "gateway.sock")) <= 100, "The fixture socket path is too long"
    (guard / "sitecustomize.py").write_text(
        "from native_bot_socket_guard import activate_child\nactivate_child()\n", encoding="utf-8"
    )
    sender_home = home / "profiles" / "scout"
    sender_home.mkdir(parents=True)
    (sender_home / "config.yaml").write_text(
        '{"telemetry":{"shared_metrics":{"enabled":false}}}', encoding="utf-8"
    )
    (sender_home / "profile.yaml").write_text(
        '{"ui_meta":{"hermes-bots":{"title":"Scout Fixture"}}}', encoding="utf-8"
    )

    env = {name: os.environ[name] for name in ("PATH", "LANG", "TZ") if name in os.environ}
    env.update(
        HOME=str(user),
        USERPROFILE=str(user),
        HERMES_HOME=str(home),
        HERMES_RUNTIME_DIR=str(runtime),
        HERMES_BUNDLED_PLUGINS=str(bundled),
        HERMES_ENABLE_PROJECT_PLUGINS="0",
        TMPDIR=str(scratch),
        XDG_RUNTIME_DIR=str(xdg),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
    )
    for command, expected in (
        (["rev-parse", "HEAD"], pin),
        (["status", "--porcelain", "--untracked-files=no"], ""),
    ):
        output = subprocess.check_output(
            ["git", *command], cwd=host, env=env, text=True, timeout=10, stdin=subprocess.DEVNULL
        )
        assert output.strip() == expected

    with monkeypatch.context() as isolated:
        for key in tuple(os.environ):
            if key not in env:
                isolated.delenv(key)
        for key, value in env.items():
            isolated.setenv(key, value)
        isolated.syspath_prepend(str(host))
        isolated.setattr(tempfile, "tempdir", str(scratch))
        deactivate = activate(root)
        try:
            with pytest.raises(PermissionError, match="DNS is disabled"):
                sys.audit("socket.getaddrinfo", "blocked.invalid")
            from hermes_cli import gateway_client

            assert Path(gateway_client.__file__).resolve().is_relative_to(host)
            with synthetic_model() as model:
                base = f"http://127.0.0.1:{model.server_port}/v1"
                config = {
                    "gateway": {"multiplex_profiles": False},
                    "webapp": {"enabled": False},
                    "model": {"provider": "custom", "default": MODEL, "base_url": base},
                    "auxiliary": {"title_generation": {"enabled": False}},
                    "platform_toolsets": {"gui": []},
                    "telemetry": {"shared_metrics": {"enabled": False}},
                }
                (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
                # A cold capability lookup must stay offline, as in upstream's
                # tests/gateway/fixtures/local_recovery_probe.py.
                offline_registry = (
                    '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}'
                )
                for profile_home in (home, sender_home):
                    (profile_home / "models_dev_cache.json").write_text(
                        offline_registry, encoding="utf-8"
                    )
                child_env = env | {
                    "PYTHONPATH": os.pathsep.join(
                        (str(guard), str(host), str(Path(__file__).resolve().parent))
                    ),
                    "OPENAI_API_KEY": MODEL_KEY,
                    "OPENAI_BASE_URL": base,
                    "HERMES_BOT_ACCEPTANCE_ROOT": str(root),
                    "HERMES_BOT_ACCEPTANCE_MODEL_PORT": str(model.server_port),
                }
                with gateway_daemon(host, home, child_env, "first") as first:
                    params = asyncio.run(create_and_send(first, home, sender_home))
                    receipt_path, receipt, row = settled_receipt(home, params)
                    assert model.requests == ["chat completion"]

                # Inject a stale derivative while the owner is stopped. The authoritative SQLite
                # result and every immutable delivery field stay untouched.
                assert receipt_path.is_file()
                stale = receipt_path.with_suffix(".fixture-tmp")
                stale.write_text(
                    json.dumps(receipt | {"status": "queued", "reply": ""}), encoding="utf-8"
                )
                stale.chmod(0o600)
                stale.replace(receipt_path)
                assert json.loads(receipt_path.read_bytes())["status"] == "queued"

                with gateway_daemon(host, home, child_env, "restart") as second:
                    assert second.instance_id != first.instance_id
                    assert second.authority_epoch > first.authority_epoch
                    # Read immediately after READY and before a ticket or replay can repair it.
                    assert json.loads(receipt_path.read_bytes()) == receipt
                    refuse_old_instance(home, first.instance_id)
                    asyncio.run(replay(second, params, row["admission_id"]))
                    _, replayed_receipt, replayed_row = settled_receipt(home, params)
                    assert replayed_receipt == receipt and replayed_row == row
                    assert model.requests == ["chat completion"]
                assert model.requests == ["chat completion"]
        finally:
            deactivate()
