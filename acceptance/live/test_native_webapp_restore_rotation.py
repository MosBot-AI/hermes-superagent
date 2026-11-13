"""Manual evidence of target-only Webapp credential rotation after a native restore."""

import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon

ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = Path("webapp") / "session-token"
CONFIG = {
    "gateway": {"multiplex_profiles": False},
    "webapp": {"enabled": False},
    "model": {
        "provider": "custom",
        "default": "unused-fixture",
        "base_url": "http://127.0.0.1:9/v1",
    },
    "platform_toolsets": {"gui": []},
    "telemetry": {"shared_metrics": {"enabled": False}},
}


def private_file(path):
    info = path.lstat()
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and (stat.S_IMODE(info.st_mode) == 0o600)
    )


def credential_matches(first, second):
    # Keep bytes out of assertion locals and failure reports.
    return hmac.compare_digest(first.read_bytes(), second.read_bytes())


def valid_credential_file(path):
    return private_file(path) and bool(
        re.fullmatch(rb"[A-Za-z0-9_-]{43}", path.read_bytes().strip())
    )


def archive_matches(archive, source):
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if Path(name).parts[-2:] == TOKEN_PATH.parts]
        return len(members) == 1 and hmac.compare_digest(
            bundle.read(members[0]), source.read_bytes()
        )


def unchanged_check(path):
    def digest():
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").digest()

    before = digest()
    return lambda: hmac.compare_digest(digest(), before)


def verify_restore_and_rotation(host, root, env):
    source, target = root / "src", root / "dst"
    for path in (source, target):
        path.mkdir(mode=0o700)
        assert len(os.fsencode(path / "gateway.sock")) <= 100, "Fixture socket path too long"

    from gateway.webapp_listener import browser_session_token
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_cli.gateway_runtime_discovery import query_identify
    from hermes_constants import _get_platform_default_hermes_home
    from hermes_state import SessionDB

    # The native import leaves service management alone for a non-default restore when
    # a default installation already exists. Use a marker in the fresh account home.
    default_home = _get_platform_default_hermes_home()
    assert default_home.is_relative_to(root)
    default_home.mkdir(mode=0o700)
    (default_home / "config.yaml").write_text("{}\n", encoding="utf-8")

    assert Path(discover_gateway_endpoint.__code__.co_filename).resolve().is_relative_to(host)
    (source / "config.yaml").write_text(json.dumps(CONFIG), encoding="utf-8")
    (source / "models_dev_cache.json").write_text(
        '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
        encoding="utf-8",
    )
    with SessionDB(source / "state.db") as db:
        db.create_session("fixture-archive-row", source="cli")
        db.append_message("fixture-archive-row", "user", "Synthetic archive marker")

    def for_home(home):
        return env | {
            "HERMES_HOME": str(home),
            "HERMES_RUNTIME_DIR": str(root / f"{home.name}-rt"),
        }

    def cli(home, *args, expect=()):
        result = subprocess.run(
            [sys.executable, "-m", "hermes_cli.main", *args],
            cwd=host,
            env=for_home(home),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=35,
            umask=0o077,
        )
        if result.returncode:
            raise AssertionError(f"Native {args[0]} fixture command failed")
        if not all(text in result.stdout for text in expect):
            raise AssertionError(f"Native {args[0]} fixture command did not confirm the operation")

    # Use the normal native file generator without opening a Webapp or using the credential.
    browser_session_token(source)
    source_file, target_file = source / TOKEN_PATH, target / TOKEN_PATH
    assert valid_credential_file(source_file)
    assert not (target / TOKEN_PATH).exists()
    assert not (target / "config.yaml").exists()
    assert not (target / "state.db").exists()
    assert discover_gateway_endpoint(source, timeout=2).state == "absent"
    assert discover_gateway_endpoint(target, timeout=2).state == "absent"

    archive = root / "archive.zip"
    cli(source, "backup", "--output", str(archive), "--keep", "0")
    assert private_file(archive)
    assert archive_matches(archive, source_file)
    archive_unchanged = unchanged_check(archive)

    cli(target, "import", str(archive), expect=("leaving the gateway service alone",))
    assert valid_credential_file(target_file)
    assert credential_matches(source_file, target_file)
    assert discover_gateway_endpoint(source, timeout=2).state == "absent"
    assert discover_gateway_endpoint(target, timeout=2).state == "absent"

    target_env = for_home(target)
    with gateway_daemon(host, target, target_env, "restore-rotation") as endpoint:
        identity = query_identify(target, timeout=2)
        assert identity["instance_id"] == endpoint.instance_id
        cli(target, "webapp", "--status", expect=("The Webapp is off.",))
        assert credential_matches(source_file, target_file)

        # This message is the native Unix handler's running-but-not-serving response.
        cli(
            target,
            "webapp",
            "--sign-out",
            expect=(
                "The gateway is not serving the Webapp",
                "Replaced its stored browser credential",
            ),
        )
        cli(target, "webapp", "--status", expect=("The Webapp is off.",))
        current = query_identify(target, timeout=2)
        assert (current["pid"], current["instance_id"]) == (
            identity["pid"],
            identity["instance_id"],
        )

        assert valid_credential_file(target_file)
        assert not credential_matches(source_file, target_file)
        assert private_file(source_file)
        assert archive_matches(archive, source_file)
        assert archive_unchanged()
        assert discover_gateway_endpoint(source, timeout=2).state == "absent"


def test_native_webapp_restore_rotates_only_the_selected_target(tmp_path_factory, monkeypatch):
    assert sys.platform == "linux", "This acceptance uses the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((ROOT / "compatibility.json").read_bytes())["hermes_commit"]
    with (
        tempfile.TemporaryDirectory(prefix="wr-", dir=tmp_path_factory.getbasetemp()) as private,
        monkeypatch.context() as isolated,
    ):
        root = Path(private)
        user, scratch, runtime, xdg, bundled, guard = (
            root / name for name in ("user", "tmp", "dst-rt", "xdg", "bundled", "guard")
        )
        for directory in (user, scratch, runtime, xdg, bundled, guard):
            directory.mkdir(mode=0o700)
        (guard / "sitecustomize.py").write_text(
            "from native_bot_socket_guard import activate_child\nactivate_child()\n",
            encoding="utf-8",
        )
        env = {name: os.environ[name] for name in ("PATH", "LANG", "TZ") if name in os.environ}
        absent_bus = f"unix:path={xdg}/absent"
        env.update(
            HOME=str(user),
            USERPROFILE=str(user),
            HERMES_HOME=str(root / "dst"),
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
            DBUS_SESSION_BUS_ADDRESS=absent_bus,
            DBUS_SYSTEM_BUS_ADDRESS=absent_bus,
            PYTHONPATH=os.pathsep.join(
                (str(guard), str(host), str(Path(__file__).resolve().parent))
            ),
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            HERMES_BOT_ACCEPTANCE_ROOT=str(root),
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
            verify_restore_and_rotation(host, root, env)
        finally:
            deactivate()
