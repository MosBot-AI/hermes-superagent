"""Manual evidence of a native same-install Bot reply persisted by the poll lane."""

import asyncio
import hashlib
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from contextlib import closing, contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import test_native_bot_receipt as shared
from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon

NOTICE = "Synthetic Bot poll reply request"
MESSAGE = f"Message from 🤖 Scout Fixture (@scout): {NOTICE}"
SENDER = "fixture-scout-bot"


class HeldRequests(list):
    def __init__(self):
        super().__init__()
        self.observed = threading.Event()
        self.release = threading.Event()

    def append(self, value):
        super().append(value)
        if value == "chat completion":
            self.observed.set()
            if not self.release.wait(35):
                super().append("expired synthetic model gate")
                raise TimeoutError("Synthetic model gate expired")


def send(db):
    from agent.tool_executor import _resolve_sequential_dispatch, _ToolCallRef
    from gateway.session_context import declare_stateless_channel
    from tools.bot_mode_dm import ensure_message_agent_tool

    declare_stateless_channel()
    agent = SimpleNamespace(
        _session_db=db, session_id=SENDER, _bot_mode_protocol=True, tools=[], valid_tool_names=set()
    )
    assert ensure_message_agent_tool(agent)
    assert agent.valid_tool_names == {"message_agent"}
    call = _ToolCallRef(
        "message_agent",
        {"target": "@hermes", "message": NOTICE, "expects_reply": True},
        "fixture-stateless-bot",
        "fixture-poll-call",
        [],
    )
    return json.loads(_resolve_sequential_dispatch(agent, call, []).execute(call.args))


def expected_snapshot(command, cwd, env, scratch):
    from tools.environments.base_session_env import _cwd_marker, _snapshot_bootstrap_script
    from tools.environments.local import _append_dropped_path_entries

    marker = re.search(r"/hermes-snap-([0-9a-f]{12})\.sh\.tmp\.XXXXXXXXXX", command)
    if not marker or cwd != scratch.parent:
        return False
    session = marker.group(1)
    path = scratch / f"hermes-snap-{session}.sh"
    script = _snapshot_bootstrap_script(
        quoted_cwd=shlex.quote(str(cwd)),
        quoted_snap=shlex.quote(str(path)),
        snap_tmp_template=shlex.quote(str(path) + ".tmp.XXXXXXXXXX"),
        excluded_names=(),
        cwd_marker=_cwd_marker(session),
    )
    return command == _append_dropped_path_entries(script, env.get("PATH", ""))


@contextmanager
def guarded_sender_processes(monkeypatch, host, home, scratch, guard, port):
    from tools.environments.local import _append_dropped_path_entries

    root = home.parent
    original_popen = subprocess.Popen
    processes = {}
    denied = set()

    def inspect_popen(argv, *args, **kwargs):
        if not isinstance(argv, list) or len(argv) < 3:
            denied.add("process shape")
            raise PermissionError("Unexpected process in the private Bot fixture")
        binary = Path(os.fsdecode(argv[0])).resolve()
        cwd = Path(kwargs.get("cwd") or Path.cwd()).resolve()
        env = kwargs.get("env") or {}
        if binary == Path("/usr/bin/git").resolve() and (
            argv[1:] == ["rev-parse", "HEAD"]
            and cwd == host
            or argv[1:] == ["-C", str(host), "rev-parse", "HEAD"]
        ):
            return original_popen(argv, *args, **kwargs)
        if (
            binary == Path("/bin/sh").resolve()
            and argv[1:] == [str(host / "hermes_cli/process_supervisor.sh"), str(os.getpgid(0))]
            and kwargs.get("start_new_session") is True
            and kwargs.get("close_fds") is True
            and not env
        ):
            category = "supervisor"
        elif (
            binary == Path("/bin/bash").resolve()
            and argv[1:2] == ["-l"]
            and argv[2:3] == ["-c"]
            and len(argv) == 4
            and expected_snapshot(argv[3], cwd, env, scratch)
        ):
            category = "snapshot"
        elif binary == Path("/bin/bash").resolve() and argv[1:2] == ["-lic"] and len(argv) == 3:
            words = shlex.split(argv[2].splitlines()[-1])
            if (
                len(words) != 12
                or words[:4]
                != [
                    sys.executable,
                    str(host / "tools/bot_mode_dm.py"),
                    "--run-delivery",
                    "--author",
                ]
                or words[5] != "query-file"
                or words[7:9] != ["--profile-home", str(home)]
                or words[-2:] != ["-p", "default"]
                or Path(words[9]).name != "hermes"
                or cwd != host
                or argv[2]
                != "set +m; " + _append_dropped_path_entries(shlex.join(words), env.get("PATH", ""))
            ):
                denied.add("waiter arguments")
                raise PermissionError("Native Bot waiter command did not match the private fixture")
            author = json.loads(words[4])
            payload = Path(words[6])
            if (
                {key: author.get(key) for key in shared.AUTHOR} != shared.AUTHOR
                or set(author) - (set(shared.AUTHOR) | {"hops"})
                or not payload.resolve().is_relative_to(scratch)
                or not payload.is_file()
            ):
                denied.add("waiter payload")
                raise PermissionError("Native Bot waiter input was outside fixture custody")
            category = "waiter"
        else:
            denied.add("snapshot arguments" if binary.name == "bash" else "process")
            raise PermissionError("Unexpected process in the private Bot fixture")

        if category in processes:
            denied.add("duplicate process")
            raise PermissionError("Unexpected duplicate process in the private Bot fixture")
        if category != "supervisor" and (
            env.get("HOME") != str(root / "u")
            or env.get("HERMES_HOME") != str(home)
            or env.get("TMPDIR") != str(scratch)
            or str(guard) not in env.get("PYTHONPATH", "").split(os.pathsep)
            or env.get("HERMES_BOT_ACCEPTANCE_ROOT") != str(root)
            or env.get("HERMES_NATIVE_ACCEPTANCE_DIAL_PORT") != str(port)
            or "OPENAI_API_KEY" in env
            or kwargs.get("start_new_session") is not True
        ):
            denied.add("process environment")
            raise PermissionError("Native Bot process environment was outside fixture custody")
        proc = original_popen(argv, *args, **kwargs)
        processes[category] = proc
        return proc

    with monkeypatch.context() as observer:
        observer.setattr(subprocess, "Popen", inspect_popen)
        try:
            yield processes, denied
        finally:
            supervisor = processes.get("supervisor")
            if supervisor and supervisor.stdin and not supervisor.stdin.closed:
                supervisor.stdin.close()
            for proc in reversed(tuple(processes.values())):
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        with suppress(ProcessLookupError):
                            os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=3)


def assert_waiter_pid(root, host, wrapper):
    import psutil

    shell = psutil.Process(wrapper.pid)
    matches = []
    for process in [shell, *shell.children()]:
        try:
            argv = process.cmdline()
        except psutil.NoSuchProcess, psutil.ZombieProcess:
            continue
        if (
            argv[:3] == [sys.executable, str(host / "tools/bot_mode_dm.py"), "--run-delivery"]
            and os.getpgid(process.pid) == wrapper.pid
            and (root / f"socket-guard-{process.pid}").is_file()
        ):
            matches.append(process)
    return matches[0] if len(matches) == 1 else None


def waiter_settled(tracked, delivery):
    # Inspect the finished buffer without consuming the native completion.
    from tools.ansi_strip import strip_ansi

    with tracked._lock:
        lines = strip_ansi(tracked.output_buffer).splitlines()
    outcomes = []
    for line in lines:
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict) and "delivery_id" in candidate:
            outcomes.append(candidate)
    return len(outcomes) == 1 and (
        outcomes[0].get("status"),
        outcomes[0].get("delivery_id"),
        outcomes[0].get("reply"),
    ) == ("settled", delivery, shared.REPLY)


async def exercise(fixture, endpoint, db, model, monkeypatch):
    from gateway.session_results import admission_result
    from hermes_cli.gateway_client import connect_gateway
    from hermes_state import SessionDB
    from hermes_state_runtime import list_session_admissions
    from tools.process_registry import process_registry

    host, home, scratch, guard = fixture
    root = home.parent
    port = urlsplit(endpoint.api_origin).port
    assert port is not None
    restrict = activate(root, dial_ports=(port,), dial_host="127.0.0.1")
    try:
        async with asyncio.timeout(66), connect_gateway(endpoint=endpoint) as client:
            created = await client.rpc(
                "session.create",
                request_id="fixture-poll-target",
                title="Bot Chat",
                source="gui",
                cwd=str(home),
                hidden=True,
                toolsets=[],
                _timeout=8,
            )
            target = created["session_id"]
            before = db.get_messages(SENDER)
            with monkeypatch.context() as sender:
                sender.setenv("HERMES_BOT_ACCEPTANCE_ROOT", str(root))
                sender.setenv("HERMES_NATIVE_ACCEPTANCE_DIAL_PORT", str(port))
                with guarded_sender_processes(sender, host, home, scratch, guard, port) as (
                    processes,
                    denied,
                ):
                    try:
                        ack = await asyncio.to_thread(send, db)
                        assert not denied, "Private Bot fixture refused a startup operation"
                        assert ack.get("reply_delivery") == "poll"
                        assert ack["status"] in {"queued", "claimed"} and ack["to"] == "@hermes"
                        assert not {"error", "notification_error", "reply"}.intersection(ack)
                        assert set(processes) == {"snapshot", "supervisor", "waiter"}
                        assert processes["snapshot"].poll() == 0
                        assert len(list(scratch.glob("hermes-snap-*.sh"))) == 1
                        delivery = ack["delivery_id"]
                        tracked = process_registry.get(ack["process_id"])
                        assert tracked is not None and tracked.process is processes["waiter"]
                        assert not tracked.notify_on_complete
                        assert await asyncio.to_thread(model.observed.wait, 12)
                        async with asyncio.timeout(10):
                            while not (waiter := assert_waiter_pid(root, host, tracked.process)):
                                await asyncio.sleep(0.05)
                        assert tracked.process.poll() is None
                        assert db.get_messages(SENDER) == before

                        (payload,) = scratch.glob("hermes-dm-*/*.txt")
                        intent = payload.with_suffix(".txt.live.json")
                        assert intent.is_file()
                        assert (
                            hashlib.sha256(str(payload.resolve()).encode()).hexdigest() == delivery
                        )
                        assert json.loads(intent.read_bytes())["delivery_id"] == delivery
                        model.release.set()

                        # Read the sender's DB first. process.wait/log consume the outcome and
                        # could suppress this native durable fallback.
                        async with asyncio.timeout(22):
                            while len(rows := db.get_messages(SENDER)) == len(before):
                                await asyncio.sleep(0.05)
                        assert rows[:-1] == before and len(rows) == len(before) + 1
                        completion = rows[-1]
                        assert completion["role"] == "user"
                        assert completion["display_kind"] == "process_complete"
                        assert (
                            shared.REPLY in completion["content"]
                            and delivery in completion["content"]
                        )
                        assert ack["process_id"] in completion["content"]
                        assert not process_registry.is_completion_consumed(tracked.id)
                        assert tracked.process.poll() == 0 and tracked._completion_event.is_set()
                        assert waiter_settled(tracked, delivery), "Unexpected native waiter result"
                        assert (
                            not waiter.is_running() and not payload.exists() and not intent.exists()
                        )
                    finally:
                        model.release.set()

            (receipt_path,) = (home / "runtime/bot_live_delivery").glob("*.json")
            receipt = json.loads(receipt_path.read_bytes())
            assert receipt["delivery_id"] == delivery and receipt["session_id"] == target
            assert receipt["profile_home"] == str(home) and receipt["message"] == MESSAGE
            assert receipt["principal_id"] == f"uid:{os.getuid()}"
            assert receipt["status"] == "settled" and receipt["reply"] == shared.REPLY
            assert {key: receipt["author"].get(key) for key in shared.AUTHOR} == shared.AUTHOR
            with closing(SessionDB(home / "state.db", read_only=True)) as target_db:
                (admission,) = list_session_admissions(
                    target_db, session_id=target, pending_only=False
                )
                with target_db._read_ctx() as conn:
                    assert (
                        conn.execute("SELECT COUNT(*) FROM session_admissions").fetchone()[0] == 1
                    )
                assert admission["admission_id"] == receipt["admission_id"]
                assert admission["request_id"] == f"bot:{delivery}"
                assert (admission["status"], admission["outcome"]) == ("terminal", "completed")
                assert admission["payload"]["text"] == MESSAGE
                author = admission["payload"]["local_automation_v1"]["turn_author"]
                assert {key: author.get(key) for key in shared.AUTHOR} == shared.AUTHOR
                assert (
                    admission_result(target_db, admission["admission_id"])["result"][
                        "final_response"
                    ]
                    == shared.REPLY
                )
            public = await client.rpc(
                "prompt.receipt",
                session_id=target,
                admission_id=admission["admission_id"],
                include_result=True,
                _timeout=6,
            )
            assert public["ref"] == {"profile_id": str(home), "session_id": target}
            assert public["admission_id"] == admission["admission_id"]
            assert (public["status"], public["outcome"]) == ("terminal", "completed")
            assert public["result"]["final_response"] == shared.REPLY
            assert model == ["chat completion"] and db.get_messages(SENDER) == rows
    finally:
        restrict()


def test_native_stateless_bot_poll_reply_persists_unconsumed_completion(
    tmp_path_factory, monkeypatch
):
    assert sys.platform == "linux" and os.environ.get("HERMES_BOT_POLL_NAMESPACE") == "1"
    assert sys.version_info[:2] == (3, 14)
    assert [name for _, name in socket.if_nameindex()] == ["lo"]
    for path in map(Path, ("/etc/profile", "/etc/bash.bashrc")):
        assert not path.exists() or path.stat().st_size == 0
    profiles = Path("/etc/profile.d")
    assert not profiles.exists() or not any(profiles.iterdir())
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((shared.ROOT / "compatibility.json").read_bytes())["hermes_commit"]
    root = tmp_path_factory.mktemp("bp")
    root.chmod(0o700)
    home, user, runtime, scratch, xdg, bundled, guard = (
        root / name for name in ("h", "u", "rt", "tmp", "xdg", "bundled", "guard")
    )
    for directory in (home, user, runtime, scratch, xdg, bundled, guard):
        directory.mkdir(mode=0o700)
    assert len(os.fsencode(home / "gateway.sock")) <= 100
    sender_home = home / "profiles/scout"
    sender_home.mkdir(parents=True, mode=0o700)
    (sender_home / "config.yaml").write_text(
        '{"telemetry":{"shared_metrics":{"enabled":false}}}', encoding="utf-8"
    )
    (sender_home / "profile.yaml").write_text(
        '{"ui_meta":{"hermes-bots":{"title":"Scout Fixture"}}}', encoding="utf-8"
    )
    (guard / "sitecustomize.py").write_text(
        "try:\n"
        "    from native_bot_socket_guard import activate_child\n"
        "    activate_child()\n"
        "except Exception:\n"
        "    raise SystemExit('Private Bot poll socket audit could not start') from None\n",
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
        TERMINAL_CWD=str(root),
        XDG_RUNTIME_DIR=str(xdg),
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_CACHE_HOME=str(root / "cache"),
        XDG_DATA_HOME=str(root / "data"),
        XDG_STATE_HOME=str(root / "state"),
        DBUS_SESSION_BUS_ADDRESS=bus,
        DBUS_SYSTEM_BUS_ADDRESS=bus,
        SHELL="/bin/bash",
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join((str(guard), str(host), str(Path(__file__).resolve().parent))),
    )
    for argv, expected in (
        (["rev-parse", "HEAD"], pin),
        (["status", "--porcelain", "--untracked-files=no"], ""),
    ):
        assert (
            subprocess.check_output(
                ["git", *argv], cwd=host, env=env, stdin=subprocess.DEVNULL, text=True, timeout=10
            ).strip()
            == expected
        )

    with monkeypatch.context() as isolated:
        for key in tuple(os.environ):
            if key not in env:
                isolated.delenv(key)
        for key, value in env.items():
            isolated.setenv(key, value)
        isolated.syspath_prepend(str(host))
        isolated.chdir(root)
        isolated.setattr(tempfile, "tempdir", str(scratch))
        isolated.setattr(shared, "MESSAGE", MESSAGE)
        deactivate = activate(root)
        try:
            from hermes_cli import gateway_client
            from hermes_state import SessionDB

            assert Path(gateway_client.__file__).resolve().is_relative_to(host)
            with (
                shared.synthetic_model() as peer,
                closing(SessionDB(sender_home / "state.db")) as db,
            ):
                model = peer.requests = HeldRequests()
                base = f"http://127.0.0.1:{peer.server_port}/v1"
                config = {
                    "gateway": {"multiplex_profiles": False},
                    "webapp": {"enabled": False},
                    "model": {"provider": "custom", "default": shared.MODEL, "base_url": base},
                    "auxiliary": {"title_generation": {"enabled": False}},
                    "terminal": {"backend": "local", "cwd": str(root), "auto_source_bashrc": False},
                    "platform_toolsets": {"gui": []},
                    "telemetry": {"shared_metrics": {"enabled": False}},
                }
                (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
                for directory in (home, sender_home):
                    (directory / "models_dev_cache.json").write_text(
                        '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
                        encoding="utf-8",
                    )
                db.create_session(SENDER, source="local", user_id="synthetic-scout-owner")
                assert db.set_session_title(SENDER, "Bot Chat")
                assert db.set_session_hidden(SENDER, True)
                db.append_message(SENDER, "user", "Synthetic original sender marker")
                child_env = env | {
                    "OPENAI_API_KEY": shared.MODEL_KEY,
                    "OPENAI_BASE_URL": base,
                    "HERMES_BOT_ACCEPTANCE_ROOT": str(root),
                    "HERMES_BOT_ACCEPTANCE_MODEL_PORT": str(peer.server_port),
                }
                with gateway_daemon(host, home, child_env, "bot-poll") as gateway:
                    asyncio.run(
                        exercise((host, home, scratch, guard), gateway, db, model, isolated)
                    )
        finally:
            deactivate()
