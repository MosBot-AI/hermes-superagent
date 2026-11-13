"""Manual evidence of native same-install Bot reply persistence and consumption."""

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
from test_packaged_gateway_bot import (
    ADD,
    TASK,
    command,
    confirm_task,
    verify_install,
    verify_saved_state,
)

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
            if binary.name == "bash":
                denied.add("snapshot arguments")
                if len(argv) == 4:
                    if cwd != root:
                        denied.add("snapshot cwd")
                    if str(scratch) not in argv[3]:
                        denied.add("snapshot scratch")
            else:
                denied.add("process")
            raise PermissionError("Unexpected process in the private Bot fixture")

        if category in processes:
            denied.add("duplicate process")
            raise PermissionError("Unexpected duplicate process in the private Bot fixture")
        if category != "supervisor":
            expected_env = {
                "HOME": str(root / "u"),
                "HERMES_HOME": str(home),
                "TMPDIR": str(scratch),
                "HERMES_BOT_ACCEPTANCE_ROOT": str(root),
                "HERMES_NATIVE_ACCEPTANCE_DIAL_PORT": str(port),
            }
            mismatched = {key for key, value in expected_env.items() if env.get(key) != value}
            if str(guard) not in env.get("PYTHONPATH", "").split(os.pathsep):
                mismatched.add("PYTHONPATH")
            if "OPENAI_API_KEY" in env or kwargs.get("start_new_session") is not True:
                mismatched.add("process custody")
            if mismatched:
                denied.update(mismatched)
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


def assert_settled_output(output, delivery):
    from tools.ansi_strip import strip_ansi

    outcomes = []
    for line in strip_ansi(output).splitlines():
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict) and "delivery_id" in candidate:
            outcomes.append(candidate)
    assert len(outcomes) == 1 and (
        outcomes[0].get("status"),
        outcomes[0].get("delivery_id"),
        outcomes[0].get("reply"),
    ) == ("settled", delivery, shared.REPLY)


async def consume_before_persistence(tracked, delivery, model, monkeypatch):
    from gateway.session_context import declare_stateless_channel
    from tools.process_registry import process_registry
    from tools.registry import registry

    proc_id = tracked.id
    (fallback,) = [
        thread
        for thread in threading.enumerate()
        if thread.name == f"message-agent-reply-{proc_id}"
    ]
    at_decision, resume_decision = threading.Event(), threading.Event()
    observed = []
    native_check = process_registry.is_completion_consumed

    def check(session_id):
        if threading.current_thread() is not fallback or session_id != proc_id:
            return native_check(session_id)
        # Order the real fallback after the caller reads the real tool result.
        at_decision.set()
        if not resume_decision.wait(20):
            observed.append(None)
            return native_check(session_id)
        consumed = native_check(session_id)
        observed.append(consumed)
        return consumed

    def wait(timeout):
        declare_stateless_channel()
        args = {"action": "wait", "session_id": proc_id, "timeout": timeout}
        return json.loads(registry.dispatch("process_manage", args, task_id=tracked.task_id))

    with monkeypatch.context() as ordered:
        ordered.setattr(process_registry, "is_completion_consumed", check)
        try:
            pending = await asyncio.to_thread(wait, 1)
            assert pending["status"] == "timeout" and pending["process_running"] is True
            assert not native_check(proc_id) and not at_decision.is_set()
            assert not tracked.notify_on_complete
            model.release.set()
            completed = await asyncio.to_thread(wait, 14)
            assert completed["status"] == "exited" and completed["exit_code"] == 0
            assert "output_cut" not in completed
            assert_settled_output(completed["output"], delivery)
            assert native_check(proc_id)
            assert await asyncio.to_thread(at_decision.wait, 4)
        finally:
            model.release.set()
            resume_decision.set()
            await asyncio.to_thread(fallback.join, 5)
    assert not fallback.is_alive() and observed == [True]


async def exercise(fixture, endpoint, db, model, monkeypatch, *, installed, consume):
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
            if installed:
                await client.rpc("session.resume", session_id=target, _timeout=8)
                task = (await command(client, target, ADD))["data"]
                assert task["title"] == TASK and task["revision"] == 1
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
                        if consume:
                            await consume_before_persistence(tracked, delivery, model, sender)
                            rows = db.get_messages(SENDER)
                            assert rows == before
                        else:
                            model.release.set()
                            async with asyncio.timeout(22):
                                while len(rows := db.get_messages(SENDER)) == len(before):
                                    await asyncio.sleep(0.05)
                            assert rows[:-1] == before and len(rows) == len(before) + 1
                            completion = rows[-1]
                            assert completion["role"] == "user"
                            assert completion["display_kind"] == "process_complete"
                            assert all(
                                value in completion["content"]
                                for value in (shared.REPLY, delivery, tracked.id)
                            )
                            assert not process_registry.is_completion_consumed(tracked.id)
                            with tracked._lock:
                                assert_settled_output(tracked.output_buffer, delivery)
                        assert tracked.process.poll() == 0 and tracked._completion_event.is_set()
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
            if installed:
                await confirm_task(client, target, task)
                return target, task["id"]
    finally:
        restrict()


@contextmanager
def isolated_reply_fixture(tmp_path_factory, monkeypatch, *, activate_hook):
    assert sys.platform == "linux" and os.environ.get("HERMES_BOT_POLL_NAMESPACE") == "1"
    assert sys.version_info[:2] == (3, 14)
    assert [name for _, name in socket.if_nameindex()] == ["lo"]
    for path in map(Path, ("/etc/profile", "/etc/bash.bashrc", "/etc/bash.bash_logout")):
        assert not path.exists() or path.stat().st_size == 0
    profiles = Path("/etc/profile.d")
    assert not profiles.exists() or not any(profiles.iterdir())
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((shared.ROOT / "compatibility.json").read_bytes())["hermes_commit"]
    prepared = os.environ.get("HERMES_BOT_POLL_INSTALLED")
    root = Path(prepared).resolve(strict=True) if prepared else tmp_path_factory.mktemp("bp")
    root.chmod(0o700)
    home, user, runtime, scratch, xdg, bundled, guard = (
        root / name for name in ("h", "u", "rt", "tmp", "xdg", "bundled", "guard")
    )
    for directory in (home, user, runtime, scratch, xdg, bundled, guard):
        directory.mkdir(mode=0o700, exist_ok=bool(prepared))
    if prepared:
        source = (root / "source-commit").read_text(encoding="ascii")
        verify_install(home, root / "package", source)
    assert len(os.fsencode(home / "gateway.sock")) <= 100
    sender_home = home / "profiles/scout"
    sender_home.mkdir(parents=True, mode=0o700)
    (sender_home / "profile.yaml").write_text(
        '{"ui_meta":{"hermes-bots":{"title":"Scout Fixture"}}}', encoding="utf-8"
    )
    module, function = activate_hook.split(":")
    (guard / "sitecustomize.py").write_text(
        "try:\n"
        f"    from {module} import {function}\n"
        f"    {function}()\n"
        "except Exception:\n"
        "    raise SystemExit('Private Bot reply socket audit could not start') from None\n",
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
    checks = [(["rev-parse", "HEAD"], pin)]
    if os.environ.get("HERMES_BOT_REVIEW_RECOVERY") == "1":
        experiment = shared.ROOT / "experiments/bot-sender-recovery"
        proposal = json.loads((experiment / "manifest.json").read_bytes())
        patch = experiment / "bot-sender-recovery.patch"
        assert proposal["status"] == "review_only" and proposal["hermes_base"] == pin
        assert hashlib.sha256(patch.read_bytes()).hexdigest() == proposal["patch_sha256"]
        checks = [
            (["show", "-s", "--format=%P", "HEAD"], pin),
            (["rev-parse", "HEAD^{tree}"], proposal["proposal_tree"]),
        ]
    checks.append((["status", "--porcelain", "--untracked-files=all"], ""))
    for argv, expected in checks:
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
        deactivate = activate(root)
        try:
            yield isolated, (host, home, scratch, guard), sender_home, env, bool(prepared)
        finally:
            deactivate()


def run_reply(tmp_path_factory, monkeypatch, *, consume):
    with isolated_reply_fixture(
        tmp_path_factory, monkeypatch, activate_hook="native_bot_socket_guard:activate_child"
    ) as (isolated, fixture, sender_home, env, prepared):
        host, home, scratch, guard = fixture
        root = home.parent
        (sender_home / "config.yaml").write_text(
            '{"telemetry":{"shared_metrics":{"enabled":false}}}', encoding="utf-8"
        )
        isolated.setattr(shared, "MESSAGE", MESSAGE)
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
            if prepared:
                from ruamel.yaml import YAML

                yaml = YAML()
                config_path = home / "config.yaml"
                installed_config = yaml.load(config_path)
                installed_config.update(config)
                yaml.dump(installed_config, config_path)
            else:
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
                saved = asyncio.run(
                    exercise(
                        (host, home, scratch, guard),
                        gateway,
                        db,
                        model,
                        isolated,
                        installed=bool(prepared),
                        consume=consume,
                    )
                )
            if prepared:
                target, task_id = saved
                verify_saved_state(
                    home,
                    target,
                    task_id,
                    messages=(("user", MESSAGE), ("assistant", shared.REPLY)),
                    admission_count=1,
                )


def test_native_stateless_bot_poll_reply_persists_unconsumed_completion(
    tmp_path_factory, monkeypatch
):
    run_reply(tmp_path_factory, monkeypatch, consume=False)


def test_native_stateless_bot_wait_consumes_reply_before_fallback(tmp_path_factory, monkeypatch):
    run_reply(tmp_path_factory, monkeypatch, consume=True)
