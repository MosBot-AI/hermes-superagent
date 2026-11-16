"""Manual evidence of an ordinary named-profile Gateway-managed worker."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon

REPO = Path(__file__).resolve().parents[2]
MODEL = "fixture-managed-model"
MODEL_KEY = "synthetic-loopback-only"
TEXT = "Synthetic managed worker turn"
REPLY = "Synthetic bounded worker response"
INPUT = "fixture-managed-input"
METADATA_PATHS = {
    "/api/v1/models",
    "/api/tags",
    "/v1/props",
    "/props",
    "/version",
    "/v1/models",
    "/models",
}


class ScriptedModel(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path not in METADATA_PATHS:
            self.server.unexpected += 1
        self.send_error(404)

    def completion_request(self):
        self.connection.settimeout(5)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("invalid model request length")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("invalid model request body")
        except ValueError, OSError:
            self.server.unexpected += 1
            self.send_error(400)
            return None
        if self.path == "/api/show" and body == {"name": MODEL}:
            self.send_error(404)
            return None
        return body

    def do_POST(self):
        body = self.completion_request()
        if body is None:
            return

        messages = body.get("messages", [])
        users = [
            row.get("content")
            for row in messages
            if isinstance(row, dict) and row.get("role") == "user"
        ]
        turn = users[-1] if users else None
        first = users == [TEXT]
        follower = self.server.follower is not None and turn == self.server.follower
        expected_key = MODEL_KEY if self.server.follower is None else "no-key-required"
        if (
            self.path != "/v1/chat/completions"
            or self.headers.get("Authorization") != f"Bearer {expected_key}"
            or body.get("model") != MODEL
            or not (first or follower)
            or body.get("tools")
        ):
            self.server.unexpected += 1
            self.send_error(400)
            return
        self.server.completions += 1
        self.server.turns.append(turn)
        observed, release = (
            (self.server.observed, self.server.release)
            if first
            else (self.server.follower_observed, self.server.follower_release)
        )
        observed.set()
        if not release.wait(35 if self.server.follower is not None else 12):
            self.server.unexpected += 1
            with suppress(BrokenPipeError, ConnectionResetError):
                self.send_error(500)
            return
        self.send_completion(body, {"role": "assistant", "content": REPLY})

    def send_completion(self, body, message):
        calls = message.get("tool_calls", [])
        choice = {"index": 0, "finish_reason": "tool_calls" if calls else "stop"}
        reply = {
            "id": "fixture",
            "model": MODEL,
            "choices": [choice],
        }
        if body.get("stream"):
            choice["delta"] = message
            for index, call in enumerate(calls):
                call["index"] = index
            content = ("data: " + json.dumps(reply) + "\n\ndata: [DONE]\n\n").encode()
            content_type = "text/event-stream"
        else:
            choice["message"] = message
            content = json.dumps(reply).encode()
            content_type = "application/json"
        with suppress(BrokenPipeError, ConnectionResetError):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)


@contextmanager
def scripted_model(*, follower=None, handler=ScriptedModel):
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        server.completions = server.unexpected = 0
        server.observed, server.release = threading.Event(), threading.Event()
        server.follower_observed, server.follower_release = threading.Event(), threading.Event()
        server.follower, server.turns = follower, []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.release.set()
            server.follower_release.set()
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def seed_profiles(home, scout, watch, url):
    from hermes_state import SessionDB

    for label, path in (("default", home), ("scout", scout), ("watch", watch)):
        config = {
            "gateway": {"multiplex_profiles": True, "managed_workers": path == scout},
            "webapp": {"enabled": False},
            "model": {"provider": "custom", "default": MODEL, "base_url": url},
            "auxiliary": {"title_generation": {"enabled": False}},
            "platform_toolsets": {"cli": []},
            "telemetry": {"shared_metrics": {"enabled": False}},
        }
        (path / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
        (path / "models_dev_cache.json").write_text(
            '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
            encoding="utf-8",
        )
        if path != scout:
            with SessionDB(path / "state.db") as db:
                session_id = f"fixture-{label}"
                db.create_session(session_id, source="cli")
                db.append_message(session_id, "user", "Synthetic sibling control")


def query(path, statement, *args):
    uri = (path / "state.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(statement, args).fetchall()


def sibling_snapshot(path):
    return (
        query(path, "SELECT id,title,profile_name FROM sessions ORDER BY id"),
        query(path, "SELECT session_id,role,content FROM messages ORDER BY id"),
        query(path, "SELECT count(*) FROM session_admissions"),
        query(path, "SELECT count(*) FROM worker_executions"),
        query(path, "SELECT count(*) FROM worker_receipts"),
    )


def admission_rows(path):
    return query(
        path,
        "SELECT admission_id,target_session_id,principal_id,owner_epoch,generation,status,outcome,"
        "request_id FROM session_admissions ORDER BY seq",
    )


def worker_rows(path):
    # Deliberately exclude the worker's private adoption and receipt digests.
    return query(
        path,
        "SELECT execution_id,session_id,kind,owner_epoch,generation,status,last_sequence "
        "FROM worker_executions",
    )


def managed_children(owner):
    import psutil

    matches = []
    for child in psutil.Process(owner).children(recursive=True):
        try:
            if child.cmdline()[-2:] == ["-m", "agent.managed_worker"]:
                matches.append(child)
        except psutil.NoSuchProcess, psutil.ZombieProcess:
            continue
    return matches


async def verify_worker(root, scout, endpoint, owner, model, url, controls):
    from gateway.owner_identity import host_owner_subject
    from hermes_cli.gateway_client import GatewayRPCError, connect_gateway

    async with asyncio.timeout(55), connect_gateway(endpoint=endpoint) as client:
        created = await client.rpc(
            "session.create",
            request_id="fixture-managed-launch",
            source="cli",
            title="Bot Chat",
            hidden=True,
            cwd=str(scout),
            model=MODEL,
            provider="custom",
            base_url=url,
            api_key=MODEL_KEY,
            toolsets=[],
            ignore_rules=True,
            _timeout=10,
        )
        sid = created["session_id"]
        params = {"session_id": sid, "input_id": INPUT, "text": TEXT}
        submitted = await client.rpc("prompt.submit", **params, _timeout=8)
        aid = submitted["admission_id"]
        try:
            assert await asyncio.to_thread(model.observed.wait, 15), (
                "No scripted completion request"
            )
            (child,) = managed_children(owner)
            assert child.pid != owner and child.ppid() == owner
            assert (root / f"socket-guard-{child.pid}").is_file()
            (running,) = admission_rows(scout)
            (execution,) = worker_rows(scout)
            assert running[:3] == (aid, sid, host_owner_subject()) and running[5] == "started"
            assert running[7] == INPUT
            assert execution[:6] == (
                "admission-worker:" + aid,
                sid,
                "compute",
                running[3],
                running[4],
                "running",
            )
            assert query(scout, "SELECT epoch FROM runtime_epoch") == [(running[3],)]
            assert all(sibling_snapshot(path) == before for path, before in controls.items())
        finally:
            model.release.set()

        async with asyncio.timeout(15):
            while (settled := admission_rows(scout))[0][5] != "terminal":
                await asyncio.sleep(0.05)
        assert settled == [running[:5] + ("terminal", "completed", INPUT)]
        (terminal,) = worker_rows(scout)
        assert terminal[:6] == execution[:5] + ("terminal",)
        sequences = query(
            scout,
            "SELECT sequence FROM worker_receipts WHERE execution_id=? ORDER BY sequence",
            terminal[0],
        )
        assert sequences and sequences == [(index,) for index in range(1, terminal[6] + 1)]
        receipt = await client.rpc(
            "prompt.receipt",
            session_id=sid,
            admission_id=aid,
            include_result=True,
            _timeout=6,
        )
        assert receipt["ref"] == {"session_id": sid, "profile_id": str(scout)}
        assert receipt["admission_id"] == aid
        assert (receipt["status"], receipt["outcome"]) == ("terminal", "completed")
        assert (receipt["authority_epoch"], receipt["execution_generation"]) == running[3:5]
        assert receipt["result"]["final_response"] == REPLY

        resumed = await client.rpc("session.resume", session_id=sid, _timeout=6)
        assert resumed["session_id"] == sid
        assert [(item["role"], item["content"]) for item in resumed["messages"]] == [
            ("user", TEXT),
            ("assistant", REPLY),
        ]
        repeated = await client.rpc("prompt.submit", **params, _timeout=6)
        assert repeated["admission_id"] == aid
        assert (repeated["status"], repeated["outcome"]) == ("terminal", "completed")
        try:
            await client.rpc(
                "prompt.submit", **(params | {"text": "Synthetic changed input"}), _timeout=6
            )
        except GatewayRPCError as exc:
            assert (exc.code, exc.data["reason"]) == (4001, "admission_conflict")
        else:
            raise AssertionError("Changed content under the same input ID must be refused")
        assert admission_rows(scout) == settled and worker_rows(scout) == [terminal]
        assert (
            query(
                scout,
                "SELECT sequence FROM worker_receipts WHERE execution_id=? ORDER BY sequence",
                terminal[0],
            )
            == sequences
        )
        assert (model.completions, model.unexpected) == (1, 0)
        assert all(sibling_snapshot(path) == before for path, before in controls.items())
        async with asyncio.timeout(8):
            while child.is_running() or managed_children(owner):
                await asyncio.sleep(0.05)


@dataclass
class ManagedFixture:
    root: Path
    host: Path
    home: Path
    scout: Path
    child_env: dict[str, str]
    model: ThreadingHTTPServer
    url: str
    controls: dict


@contextmanager
def managed_fixture(tmp_path_factory, monkeypatch, *, follower=None, handler=ScriptedModel):
    assert sys.platform == "linux", "This acceptance uses the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((REPO / "compatibility.json").read_bytes())["hermes_commit"]
    with (
        tempfile.TemporaryDirectory(prefix="mw-", dir=tmp_path_factory.getbasetemp()) as private,
        monkeypatch.context() as isolated,
    ):
        root = Path(private)
        home, user, runtime, xdg, scratch, bundled, guard = (
            root / name for name in ("h", "u", "rt", "xdg", "tmp", "bundled", "guard")
        )
        scout, watch = (home / "profiles" / name for name in ("scout", "watch"))
        for directory in (home, scout, watch, user, runtime, xdg, scratch, bundled, guard):
            directory.mkdir(mode=0o700, parents=True)
        assert len(os.fsencode(home / "gateway.sock")) <= 100, "Fixture socket path too long"
        (guard / "sitecustomize.py").write_text(
            "try:\n"
            "    from native_managed_worker_guard import activate_managed_child\n"
            "    activate_managed_child()\n"
            "except Exception:\n"
            "    raise SystemExit('Could not load the managed-worker socket audit') from None\n",
            encoding="utf-8",
        )
        env = {name: os.environ[name] for name in ("PATH", "LANG", "TZ") if name in os.environ}
        bus = f"unix:path={xdg}/absent"
        env.update(
            HOME=str(user),
            USERPROFILE=str(user),
            HERMES_HOME=str(home),
            HERMES_RUNTIME_DIR=str(runtime),
            HERMES_BUNDLED_PLUGINS=str(bundled),
            HERMES_ENABLE_PROJECT_PLUGINS="0",
            HERMES_DISABLE_LAZY_INSTALLS="1",
            TMPDIR=str(scratch),
            XDG_RUNTIME_DIR=str(xdg),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_CACHE_HOME=str(root / "cache"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            DBUS_SESSION_BUS_ADDRESS=bus,
            DBUS_SYSTEM_BUS_ADDRESS=bus,
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=os.pathsep.join(
                (str(guard), str(host), str(Path(__file__).resolve().parent))
            ),
            HERMES_MANAGED_FIXTURE_ROOT=str(root),
        )
        for command, expected in (
            (["rev-parse", "HEAD"], pin),
            (["status", "--porcelain", "--untracked-files=no"], ""),
        ):
            output = subprocess.check_output(
                ["git", *command],
                cwd=host,
                env=env,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            assert output.strip() == expected
        for key in tuple(os.environ):
            if key not in env:
                isolated.delenv(key)
        for key, value in env.items():
            isolated.setenv(key, value)
        isolated.syspath_prepend(str(host))
        isolated.setattr(tempfile, "tempdir", str(scratch))
        deactivate = activate(root)
        try:
            from hermes_cli import gateway_client

            assert Path(gateway_client.__file__).resolve().is_relative_to(host)
            with scripted_model(follower=follower, handler=handler) as model:
                url = f"http://127.0.0.1:{model.server_port}/v1"
                seed_profiles(home, scout, watch, url)
                child_env = env | {"HERMES_MANAGED_FIXTURE_MODEL_PORT": str(model.server_port)}
                controls = {path: sibling_snapshot(path) for path in (home, watch)}
                assert all(before[2:] == ([(0,)], [(0,)], [(0,)]) for before in controls.values())
                yield ManagedFixture(root, host, home, scout, child_env, model, url, controls)
        finally:
            deactivate()


@contextmanager
def scout_connection(fixture, gateway):
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_cli.gateway_runtime_discovery import query_identify

    identity = query_identify(fixture.home, timeout=2)
    assert identity["instance_id"] == gateway.instance_id
    observed = discover_gateway_endpoint(fixture.scout, timeout=2)
    assert observed.state == "ready" and observed.endpoint is not None
    endpoint = observed.endpoint
    assert endpoint.profile_id == str(fixture.scout)
    assert (endpoint.instance_id, endpoint.api_origin) == (gateway.instance_id, gateway.api_origin)
    owner_port = urlsplit(gateway.api_origin).port
    assert owner_port is not None
    port_file = fixture.root / "gateway-port"
    with port_file.open("x", encoding="ascii") as stream:
        stream.write(str(owner_port))
    restrict = activate(fixture.root, dial_ports=(owner_port,), dial_host="127.0.0.1")
    try:
        yield endpoint, identity["pid"]
    finally:
        restrict()
        port_file.unlink()


def test_native_named_profile_runs_and_settles_an_ordinary_managed_worker(
    tmp_path_factory, monkeypatch
):
    with (
        managed_fixture(tmp_path_factory, monkeypatch) as fixture,
        gateway_daemon(fixture.host, fixture.home, fixture.child_env, "managed-worker") as gateway,
        scout_connection(fixture, gateway) as (endpoint, owner),
    ):
        from hermes_cli.gateway_runtime_discovery import query_identify

        try:
            asyncio.run(
                verify_worker(
                    fixture.root,
                    fixture.scout,
                    endpoint,
                    owner,
                    fixture.model,
                    fixture.url,
                    fixture.controls,
                )
            )
        except BaseException:
            # Retain custody of fixture descendants before the generic daemon
            # cleanup reaps their parent. psutil guards against PID reuse.
            import psutil

            with suppress(psutil.NoSuchProcess):
                for worker in managed_children(owner):
                    with suppress(psutil.NoSuchProcess):
                        worker.kill()
                        worker.wait(timeout=4)
            raise
        current = query_identify(fixture.home, timeout=2)
        assert (current["pid"], current["instance_id"]) == (owner, gateway.instance_id)
