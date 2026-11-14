"""Private native Gateway and exact committed profile CLI custody."""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon
from test_native_profile_retirement import (
    CONFIG,
    TITLE,
    lock_held,
    seed_chats,
)

REPO = Path(__file__).resolve().parents[2]
SIBLINGS = ("default", "watch")
CREATE = ["profile", "create", "scout", "--no-alias", "--no-skills"]
RENAME_COMMANDS = (
    (["rename", "scout", "renamed"], "renamed"),
    (["rename", "renamed", "scout"], "scout"),
    (["rename", "scout", "renamed", "--preserve-local-sessions"], "renamed"),
)
SEED_ESSENTIAL_SKILLS = (
    "import json; from tools.skills_sync import sync_skills; "
    "r = sync_skills(quiet=True); print(json.dumps(r))"
)


def activate_profile_cli(root, host):
    """Fence service-related side effects in the real CLI child."""
    denied = root / "profile-cli-audit-denied"
    binaries = {name: (root / "bin" / name).resolve(strict=True) for name in ("git", "which")}
    self_check = False

    def block(category):
        if not self_check and not denied.exists():
            denied.write_text(category, encoding="ascii")
        raise PermissionError("Profile CLI fixture operation outside private custody")

    def private_path(value, dir_fd):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        try:
            base = (
                Path.cwd()
                if dir_fd in (-1, None)
                else Path(f"/proc/self/fd/{dir_fd}").resolve(strict=True)
            )
            return (base / os.fsdecode(value)).resolve().is_relative_to(root)
        except OSError:
            return False

    def inspect_operation(event, args):
        if event == "subprocess.Popen":
            executable, command, cwd, child_env = args
            executable = os.fsdecode(executable)
            binary = Path(executable).name
            directory = Path(cwd or Path.cwd()).resolve()
            scout = root / "h/profiles/scout"
            # The native --no-skills action still seeds essential skills locally. Its
            # exact child inherits this guard and may not spawn another skill process.
            if (
                sys.orig_argv[-len(CREATE) :] == CREATE
                and command == [sys.executable, "-c", SEED_ESSENTIAL_SKILLS]
                and Path(executable).resolve() == Path(sys.executable).resolve()
                and directory == host
                and child_env == {**os.environ, "HERMES_HOME": str(scout)}
                and (scout / ".no-bundled-skills").is_file()
            ):
                return
            candidate = root / "bin" / executable
            if binary not in binaries or candidate.resolve() != binaries[binary]:
                block("subprocess")
            # Native startup provenance and alias collision probes are read-only.
            if not (
                binary == "which"
                and any(
                    sys.orig_argv[-len(args) :] == args and command == ["which", target]
                    for args, target in RENAME_COMMANDS
                )
                and directory == host
                and child_env is None
                or binary == "git"
                and directory == host
                and child_env is None
                and command[1:] == ["rev-parse", "HEAD"]
                or binary == "git"
                and directory == host
                and child_env is None
                and command[1:] == ["-C", str(host), "rev-parse", "HEAD"]
            ):
                block("subprocess-arguments")
        elif event == "os.kill":
            if args[1] != 0:
                block("signal")
        elif event in {
            "os.system",
            "os.posix_spawn",
            "os.exec",
            "os.fork",
            "os.forkpty",
            "os.killpg",
        }:
            block("process")
        elif event in {"os.remove", "os.rmdir", "shutil.rmtree"}:
            if not private_path(*args):
                block("remove")
        elif event == "os.mkdir":
            path, _, fd = args
            if not private_path(path, fd):
                block("mkdir")
        elif event == "os.chmod":
            path, _, fd = args
            allowed = private_path("", path) if isinstance(path, int) else private_path(path, fd)
            if not allowed:
                block("chmod")
        elif event == "os.rename":
            source, destination, source_fd, destination_fd = args
            if not private_path(source, source_fd) or not private_path(destination, destination_fd):
                block("rename")
        elif event == "open":
            path, _, flags = args
            writes = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writes and not isinstance(path, int) and not private_path(path, -1):
                block("write")

    sys.addaudithook(inspect_operation)
    self_check = True
    try:
        sys.audit("os.kill", 1, signal.SIGTERM)
    except PermissionError:
        (root / f"profile-cli-audit-ready-{os.getpid()}").touch(mode=0o600, exist_ok=False)
    else:
        raise RuntimeError("Profile CLI fixture CLI guard did not activate")
    finally:
        self_check = False


def prepare_cli_source(host, pin, root, guard, env):
    """Use the exact committed CLI source without sharing launcher-maintenance writes."""
    source = root / "cli-source"
    source.mkdir(mode=0o700)
    with tempfile.TemporaryFile(dir=root) as archive:
        subprocess.run(
            ["git", "archive", "--format=tar", pin],
            cwd=host,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=archive,
            check=True,
            timeout=30,
        )
        archive.seek(0)
        with tarfile.open(fileobj=archive) as package:
            package.extractall(source, filter="data")
    assert (source / "hermes_cli/main.py").is_file() and not (source / ".git").exists()
    bin_dir = root / "bin"
    bin_dir.mkdir(mode=0o700)
    for name in ("git", "which"):
        executable = shutil.which(name, path=os.defpath)
        assert executable is not None, f"Missing fixture executable {name}"
        (bin_dir / name).symlink_to(Path(executable).resolve(strict=True))
    return source, env | {
        "PATH": str(bin_dir),
        "PYTHONPATH": os.pathsep.join(
            (str(guard), str(source), str(Path(__file__).resolve().parent))
        ),
        "HERMES_PROFILE_FIXTURE_CLI": "1",
    }


def run_profile_cli(host, home, env, *command):
    for unit_name in ("hermes-gateway", "hermes-gateway-scout", "hermes-gateway-renamed"):
        unit = Path("/etc/systemd/system") / f"{unit_name}.service"
        assert not (unit.exists() or unit.is_symlink()), (
            "Profile CLI fixture found a real system unit"
        )
    assert Path("/proc/1/comm").read_text().strip() != "s6-svscan", (
        "Profile CLI fixture requires an inactive s6 supervisor"
    )
    root = home.parent
    before = set(root.glob("profile-cli-audit-ready-*"))
    # The allowed native essential-skills process inherits this session. If a
    # subprocess timeout occurs, stop its entire owned group before removing home.
    with subprocess.Popen(
        [sys.executable, "-m", "hermes_cli.main", "profile", *command],
        cwd=host,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        umask=0o077,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=45)
        except BaseException:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            pytest.fail("Native profile CLI did not exit under fixture custody", pytrace=False)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    denied = root / "profile-cli-audit-denied"
    if denied.exists():
        category = denied.read_text(encoding="ascii")
        if category not in {
            "chmod",
            "mkdir",
            "process",
            "remove",
            "rename",
            "signal",
            "subprocess",
            "subprocess-arguments",
            "write",
        }:
            category = "unknown"
        pytest.fail(
            f"Native CLI attempted an operation outside the fixture ({category})", pytrace=False
        )
    expected = 2 if command[0] == "create" else 1
    new_markers = set(root.glob("profile-cli-audit-ready-*")) - before
    assert len(new_markers) == expected
    assert all(
        (root / f"socket-guard-{marker.name.removeprefix('profile-cli-audit-ready-')}").is_file()
        for marker in new_markers
    )
    return result


@asynccontextmanager
async def retained_host_client(home, endpoint):
    from hermes_cli.gateway_client import (
        GATEWAY_WS_PROTOCOL,
        GatewayClient,
        _session_ticket,
        gateway_ws_target,
    )
    from websockets.asyncio.client import connect

    ticket = await asyncio.to_thread(_session_ticket, home, endpoint, scope="host")
    url, protocols = gateway_ws_target(endpoint, ticket)
    async with (
        connect(url, subprotocols=protocols, open_timeout=5, close_timeout=2, proxy=None) as socket,
        GatewayClient(socket) as client,
    ):
        assert socket.subprotocol == GATEWAY_WS_PROTOCOL
        yield client


async def lookup(client, profile):
    result = await client.rpc(
        "session.list", profile=profile, title=TITLE, include_hidden=True, _timeout=5
    )
    return [(row["id"], row["resolved_id"]) for row in result["sessions"]]


async def roster(client):
    result = await client.rpc("profiles.list", _timeout=5)
    return {row["name"]: row for row in result["profiles"]}


async def assert_siblings(client):
    for profile in SIBLINGS:
        sid = f"fixture-retained-{profile}"
        assert await lookup(client, profile) == [(sid, sid)]


async def create_canonical(client, profile, workspace, request_id):
    result = await client.rpc(
        "session.create",
        profile=profile,
        request_id=request_id,
        source="cli",
        title=TITLE,
        hidden=True,
        cwd=str(workspace),
        toolsets=[],
        ignore_rules=True,
        _timeout=8,
    )
    return result["session_id"]


@contextmanager
def profile_cli_installation(tmp_path_factory, monkeypatch, *, proposal=None):
    assert sys.platform == "linux", "Profile CLI fixture requires the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((REPO / "compatibility.json").read_bytes())["hermes_commit"]
    with (
        tempfile.TemporaryDirectory(prefix="pf-", dir=tmp_path_factory.getbasetemp()) as private,
        monkeypatch.context() as isolated,
    ):
        root = Path(private)
        home, user, runtime, xdg, scratch, bundled, guard, workspace = (
            root / name for name in ("h", "u", "rt", "xdg", "tmp", "bundled", "guard", "workspace")
        )
        for directory in (home, user, runtime, xdg, scratch, bundled, guard, workspace):
            directory.mkdir(mode=0o700)
        assert len(os.fsencode(home / "gateway.sock")) <= 100, "Fixture socket path too long"
        (guard / "sitecustomize.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "try:\n"
            "    from native_bot_socket_guard import activate_child\n"
            "    activate_child()\n"
            "    if os.environ.get('HERMES_PROFILE_FIXTURE_CLI') == '1':\n"
            "        from importlib.util import find_spec\n"
            "        from native_profile_cli_fixture import activate_profile_cli\n"
            "        root = Path(os.environ['HERMES_BOT_ACCEPTANCE_ROOT'])\n"
            "        if Path(find_spec('hermes_cli').origin).parent.parent != Path.cwd():\n"
            "            raise RuntimeError('CLI source mismatch')\n"
            "        activate_profile_cli(root, Path.cwd())\n"
            "except Exception:\n"
            "    raise SystemExit('Could not load the profile CLI fixture audit') from None\n",
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
            HERMES_BOT_ACCEPTANCE_ROOT=str(root),
        )
        commit = pin
        if proposal is not None:
            from acceptance.live.run_desktop_profile_routing import verify_proposal

            commit = verify_proposal(host, pin, env, proposal)
        for command, expected in (
            (["rev-parse", "HEAD"], commit),
            (["status", "--porcelain", "--untracked-files=no"], ""),
        ):
            actual = subprocess.check_output(
                ["git", *command],
                cwd=host,
                env=env,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            assert actual.strip() == expected
        cli_source, cli_env = prepare_cli_source(host, commit, root, guard, env)
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
            homes = {"default": home, "watch": home / "profiles/watch"}
            seed_chats(homes)
            scout = homes["scout"] = home / "profiles/scout"
            scout.mkdir(mode=0o700)
            (scout / "config.yaml").write_text(json.dumps(CONFIG), encoding="utf-8")
            (scout / "models_dev_cache.json").write_bytes(
                (home / "models_dev_cache.json").read_bytes()
            )

            @contextmanager
            def serve(label):
                with gateway_daemon(host, home, env, label) as endpoint:
                    port = urlsplit(endpoint.api_origin).port
                    restrict = activate(root, dial_ports=(port,), dial_host="127.0.0.1")
                    try:
                        yield endpoint
                    finally:
                        restrict()
                assert all(not lock_held(profile) for profile in homes.values())

            yield cli_source, cli_env, homes, workspace, serve
        finally:
            deactivate()


@contextmanager
def profile_cli_gateway(tmp_path_factory, monkeypatch, label):
    with (
        profile_cli_installation(tmp_path_factory, monkeypatch) as (
            cli_source,
            cli_env,
            homes,
            workspace,
            serve,
        ),
        serve(label) as endpoint,
    ):
        yield cli_source, cli_env, homes, workspace, endpoint
