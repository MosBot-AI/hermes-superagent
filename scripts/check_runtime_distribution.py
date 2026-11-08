#!/usr/bin/env python3
"""Verify and cold-load an already-built runtime; never install or contact a provider."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "runtime_distribution_builder", Path(__file__).with_name("build_runtime_distribution.py")
)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


# Runs with -I -B and a disposable cwd/environment. Neither source nor plugin is
# on sys.path. The real host loader alone supplies the installed package namespace.
CHILD = r"""
import argparse, contextlib, dataclasses, importlib.abc, io, json, os, socket, sys
from pathlib import Path
stage, host, plugin, source, output = sys.argv[1:]
host, plugin, source, output = map(Path, (host, plugin, source, output))
assert sys.version_info[:2] == (3, 14), "prepared Python 3.14 required"
assert all(Path(p or ".").resolve() != source for p in sys.path)
sys.path.insert(0, str(host))
class NoGlobalPackage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "personal_agent" or fullname.startswith("personal_agent."):
            raise AssertionError("global personal_agent import forbidden")
sys.meta_path.insert(0, NoGlobalPackage())
def deny(*args, **kwargs):
    raise AssertionError("network/listeners forbidden in runtime acceptance")
for name in ("connect", "connect_ex", "bind", "listen", "sendto", "sendmsg"):
    if hasattr(socket.socket, name):
        setattr(socket.socket, name, deny)
socket.create_connection = deny
scan_git = ["git", "-c", "core.fsmonitor=false", "-C", str(plugin),
            "ls-files", "-z", "--", "*.pyc", "*.pyo"]
def audit(event, args):
    if event == "subprocess.Popen":
        if stage == "scan" and args[1] == scan_git:
            return
        deny()
    if event in ("os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty",
                 "socket.connect", "socket.bind", "socket.getaddrinfo",
                 "socket.sendto", "socket.sendmsg"):
        deny()
sys.addaudithook(audit)
if stage == "scan":
    from tools.plugin_guard import PLUGIN_SCANNER_VERSION, scan_plugin
    result = dataclasses.asdict(scan_plugin(plugin, source="verified-committed-runtime"))
    result["scanner_version"] = PLUGIN_SCANNER_VERSION
    output.write_text(json.dumps(result, sort_keys=True))
elif stage == "conversation":

    import asyncio
    from dataclasses import replace
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from hermes_cli.plugins import get_plugin_manager, _reset_plugin_managers_for_tests
    from hermes_state_runtime import RuntimeStoreError
    home = Path(os.environ["HERMES_HOME"])
    plugin_id = "hermes-personal-agent"
    (home / "config.yaml").write_text(json.dumps({
        "plugins": {"enabled": [plugin_id], "entries": {plugin_id: {"settings": {
            "mode": "local_tasks", "local_conversation": True}}}},
        "delegation": {"backend": "default"},
    }))
    config_bytes = (home / "config.yaml").read_bytes()
    def make_host(home, manager):
        from gateway.config import GatewayConfig, Platform
        from gateway.run import GatewayRunner
        from gateway.run_inbound_hooks import GatewayInboundHooksMixin
        from gateway.session import SessionEntry
        from gateway.session_authority import LiveSession, SessionAuthority
        from gateway.session_contract import SessionActor, SessionRef
        from gateway.session_local import LocalSessionAdapter
        from gateway.session_local_recovery import local_source

        now = datetime.now(UTC)
        sid = "synthetic-native-session"
        route = "agent:main:local:" + sid
        entry = SessionEntry(route, sid, now, now)

        class Runner(GatewayInboundHooksMixin):
            # Real host binding; only executor and unstarted transport plumbing differ.
            _set_session_env = GatewayRunner._set_session_env
            _clear_session_env = GatewayRunner._clear_session_env
            _session_env_scope = GatewayRunner._session_env_scope

            def _adapters_for_profile(self, profile):
                return self.adapters if profile in (None, "default") else {}

            def _adapter_for_source(self, source):
                return self._adapters_for_profile(source.profile).get(source.platform)

            def _session_key_for_source(self, source):
                return route

            async def _run_in_executor_with_context(self, call):
                return await asyncio.to_thread(call)

        runner = Runner()
        runner.config = GatewayConfig()
        runner._draining = False
        runner.session_store = SimpleNamespace(
            lookup_by_session_key=lambda key: entry if key == route else None
        )
        authority = SessionAuthority(
            runner, profile_id=str(home), instance_id="synthetic-runtime", db=None, epoch=1
        )
        runner.session_authority = authority
        adapter = LocalSessionAdapter(authority)
        runner.adapters = {Platform.LOCAL: adapter}
        source = local_source(authority, sid, "synthetic-owner")
        live = LiveSession(source=source, route=route)
        authority.sessions[sid] = live
        adapter.register_source(source)
        adapter.policies[sid] = SimpleNamespace(cwd=str(home), terminal_json="{}")
        actor = SessionActor(
            "synthetic-owner",
            str(home),
            frozenset({"session:read", "session:control"}),
            "synthetic-transport",
        )
        connection = SimpleNamespace(authority=authority, actor=actor, subscriptions={})
        return SimpleNamespace(
            home=home,
            manager=manager,
            runner=runner,
            authority=authority,
            adapter=adapter,
            source=source,
            live=live,
            connection=connection,
            ref=SessionRef(str(home), sid),
        )


    def command(host, text, **extra):
        from gateway.session_commands import execute_command

        result = asyncio.run(
            execute_command(
                host.connection, host.ref, {"command": "personal-tasks --json " + text, **extra}
            )
        )
        assert result["type"] == "exec"
        return json.loads(result["output"])


    def load_conversation():
        _reset_plugin_managers_for_tests()
        manager = get_plugin_manager()
        manager.discover_and_load()
        loaded = manager._plugins[plugin_id]
        assert loaded.enabled and loaded.error is None, loaded.error
        assert loaded.tools_registered == ["personal_agent_status"]
        assert "personal-tasks" in manager._plugin_commands
        assert not loaded.hooks_registered and not loaded.middleware_registered
        assert not manager._platform_handler_factories
        prefix = loaded.module.__name__
        for name, module in list(sys.modules.items()):
            if name == prefix or name.startswith(prefix + "."):
                filename = getattr(module, "__file__", None)
                if filename:
                    assert Path(filename).resolve().is_relative_to(plugin)
        return make_host(home, manager)

    native = load_conversation()
    actor = native.connection.actor
    for capabilities in (frozenset({"session:read"}), frozenset({"session:control"})):
        native.connection.actor = replace(actor, capabilities=capabilities)
        try:
            command(native, 'add "Forbidden task" --request-id denied-conversation')
        except RuntimeStoreError as error:
            assert error.reason == "permission_denied"
        else:
            raise AssertionError("unprivileged native command admitted")
    native.connection.actor = actor
    before = command(native, "list")["data"]["items"]
    assert all(item["title"] != "Forbidden task" for item in before)
    args = 'add "Synthetic conversation task" --request-id artifact-conversation'
    captured = command(native, args)
    assert captured["status"] == "ok" and not captured["replayed"]
    task_id = captured["data"]["id"]
    assert command(native, f"show {task_id}")["data"] == captured["data"]
    native = load_conversation()
    replayed = command(native, args)
    assert replayed["replayed"] and replayed["data"] == captured["data"]
    items = command(native, "list")["data"]["items"]
    assert len(items) == len(before) + 1
    assert sum(item["id"] == task_id for item in items) == 1
    assert (home / "config.yaml").read_bytes() == config_bytes
    _reset_plugin_managers_for_tests()
    assert "personal_agent" not in sys.modules
    output.write_text(json.dumps({
        "native_local_dispatch": True, "capture_read_reload_replay": True,
        "missing_read_control_denied": True, "artifact_module_origins": True,
        "network_and_subprocesses_blocked": True,
        "transport": "authenticated_in_memory_fixture",
        "installed_or_live_verified": False,
    }, sort_keys=True))
else:
    from hermes_cli.plugins import PluginManager
    home = Path(os.environ["HERMES_HOME"])
    plugin_id = "hermes-personal-agent"
    def configure(mode=None):
        entry = {} if mode is None else {"settings": {"mode": mode}}
        (home / "config.yaml").write_text(json.dumps({
            "plugins": {"enabled": [plugin_id], "entries": {plugin_id: entry}},
            "delegation": {"backend": "default"},
        }))
    def load():
        config_bytes = (home / "config.yaml").read_bytes()
        manager = PluginManager()
        manager.discover_and_load()
        loaded = manager._plugins[plugin_id]
        assert loaded.enabled and loaded.error is None, loaded.error
        assert loaded.tools_registered == ["personal_agent_status"]
        assert not loaded.hooks_registered and not loaded.middleware_registered
        assert set(manager._plugin_commands) == {"personal-access"}
        assert not manager._platform_handler_factories
        prefix = loaded.module.__name__
        for name, module in list(sys.modules.items()):
            if name == prefix or name.startswith(prefix + "."):
                filename = getattr(module, "__file__", None)
                if filename:
                    assert Path(filename).resolve().is_relative_to(plugin)
        assert (home / "config.yaml").read_bytes() == config_bytes
        return manager
    def cli(manager, *args, expected=None):
        config_bytes = (home / "config.yaml").read_bytes()
        command = manager._cli_commands["personal-agent"]
        parser = argparse.ArgumentParser()
        command["setup_fn"](parser)
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            code = command["handler_fn"](parser.parse_args(args))
        assert (home / "config.yaml").read_bytes() == config_bytes
        assert code == expected, (code, stream.getvalue())
        return json.loads(stream.getvalue())
    configure()
    manager = load()
    status = cli(manager, "status")
    assert status["mode"] == "read_only"
    assert not status["capabilities"]["personal_data_storage"]
    assert not status["capabilities"]["worker_model_routing"]
    assert not (home / "plugin-data").exists()
    manager.unload()
    configure("local_tasks")
    manager = load()
    capture_args = ("tasks", "capture", "--title", "Synthetic distribution task",
                    "--request-id", "distribution-capture")
    captured = cli(manager, *capture_args, expected=0)
    assert captured["status"] == "ok" and not captured["replayed"]
    task_id = captured["data"]["id"]
    update_args = ("tasks", "update", task_id, "--expected-revision", "1",
                   "--title", "Updated synthetic task", "--request-id", "distribution-update")
    updated = cli(manager, *update_args, expected=0)
    assert updated["data"]["revision"] == 2 and not updated["replayed"]
    backup = cli(manager, "task-backup", "create", "--name", "distribution", expected=0)
    assert backup["data"]["counts"]["tasks"] == 1
    assert backup["data"]["integrity"] == "ok"
    manager.unload()
    manager = load()
    inspected = cli(manager, "task-backup", "inspect", "--name", "distribution", expected=0)
    assert inspected == backup
    recovered = cli(manager, "task-backup", "tasks", "--name", "distribution",
                    "--sha256", backup["data"]["sha256"], expected=0)
    assert recovered["data"]["historical_tasks"]["items"][0]["id"] == task_id
    recovered_task = cli(manager, "task-backup", "show", "--name", "distribution",
                         "--sha256", backup["data"]["sha256"], "--task-id", task_id, expected=0)
    assert recovered_task["data"]["historical_tasks"]["task"]["title"] == "Updated synthetic task"
    assert recovered_task["data"]["automatic_restore"] is False
    changed = cli(manager, "task-backup", "tasks", "--name", "distribution",
                  "--sha256", "0" * 64, expected=1)
    assert changed["error"]["code"] == "backup_changed" and changed["data"] is None
    duplicate = cli(manager, "task-backup", "create", "--name", "distribution", expected=1)
    assert duplicate["error"]["code"] == "backup_exists"
    shown = cli(manager, "tasks", "show", task_id, expected=0)
    assert shown["data"]["revision"] == 2
    assert shown["data"]["title"] == "Updated synthetic task"
    replay = cli(manager, *update_args, expected=0)
    assert replay["replayed"] and replay["data"] == updated["data"]
    original_replay = cli(manager, *capture_args, expected=0)
    assert original_replay["replayed"] and original_replay["data"] == captured["data"]
    listing = cli(manager, "tasks", "list", expected=0)
    assert len(listing["data"]["items"]) == 1
    assert listing["data"]["items"][0]["revision"] == 2
    manager.unload()
    assert "personal_agent" not in sys.modules
    assert all(Path(p or ".").resolve() != source for p in sys.path)
    output.write_text(json.dumps({
        "default_read_only": True, "default_no_storage": True,
        "no_worker_registration": True, "native_cli_capture_update": True,
        "reload_and_idempotent_replay": True, "installed_module_origins": True,
        "global_personal_agent_import_blocked": True, "network_blocked": True,
        "python": sys.version.split()[0], "subprocesses_blocked": True,
        "synthetic_configuration_preserved": True, "task_backup_reload_no_overwrite": True,
        "task_backup_historical_recovery_reads": True,
    }, sort_keys=True))
"""


def safe_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("path must not traverse symlinks")
    return path


def verify_host(host, expected):
    host = safe_path(host)
    if builder.git(host, "rev-parse", "HEAD").decode().strip() != expected:
        raise ValueError("host must match the distribution's pinned commit")
    if builder.git(host, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("host checkout must be clean")
    return host


def materialize_host(host, commit, destination):
    """Export regular files from Git objects, never index/worktree/bytecode caches."""
    entries = []
    for record in builder.git(host, "ls-tree", "-rz", commit).split(b"\0"):
        if not record:
            continue
        header, name = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        relative = name.decode()
        path = Path(relative)
        if (
            mode not in ("100644", "100755")
            or kind != "blob"
            or path.is_absolute()
            or ".." in path.parts
            or relative != path.as_posix()
            or path.suffix in (".pyc", ".pyo")
        ):
            raise ValueError("unsafe file in committed host tree")
        entries.append((relative, mode, oid))
    # --batch reads object IDs, not pathspecs or export attributes. One subprocess
    # avoids tens of thousands of git invocations for a complete native checkout.
    packed = builder.git(
        host,
        "cat-file",
        "--batch",
        input="".join(oid + "\n" for _, _, oid in entries).encode("ascii"),
    )
    destination.mkdir()
    offset = 0
    for relative, mode, expected_oid in entries:
        end = packed.index(b"\n", offset)
        oid, kind, size = packed[offset:end].decode().split()
        if oid != expected_oid or kind != "blob":
            raise ValueError("host object response mismatch")
        start, size = end + 1, int(size)
        content = packed[start : start + size]
        if len(content) != size or packed[start + size : start + size + 1] != b"\n":
            raise ValueError("truncated host object")
        offset = start + size + 1
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
        target.chmod(0o755 if mode == "100755" else 0o644)
    if offset != len(packed):
        raise ValueError("unexpected host object data")
    return builder.git(host, "rev-parse", f"{commit}^{{tree}}").decode().strip()


def run_stage(stage, host, plugin, repo, interpreter, work):
    output = work / (stage + ".json")
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(work / "home"),
        "HERMES_HOME": str(plugin.parent.parent),
        "HERMES_RUNTIME_DIR": str(work / "runtime"),
        "HERMES_BUNDLED_PLUGINS": str(work / "empty-bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    completed = subprocess.run(
        [
            str(interpreter),
            "-I",
            "-B",
            "-c",
            CHILD,
            stage,
            str(host),
            str(plugin),
            str(repo),
            str(output),
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode:
        print(completed.stdout + completed.stderr, file=sys.stderr)
        raise ValueError(f"{stage} subprocess failed")
    return json.loads(output.read_text())


def check(repo, commit, distribution, host, interpreter, report):
    """Populate report before refusing a scan; no package imports before both gates."""
    repo, distribution = safe_path(repo), safe_path(distribution)
    builder.verify(repo, commit, distribution)
    provenance = json.loads((distribution / "PROVENANCE.json").read_text())
    report.update(
        source_commit=commit,
        provenance=provenance,
        integrity="verified",
        provenance_sha256=builder.digest((distribution / "PROVENANCE.json").read_bytes()),
    )
    host = verify_host(host, provenance["compatibility"]["hermes_commit"])
    report["hermes_commit"] = provenance["compatibility"]["hermes_commit"]
    interpreter = Path(interpreter).absolute()  # Preserve the prepared venv path.
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError("existing executable prepared interpreter required")
    with tempfile.TemporaryDirectory(prefix="runtime-acceptance-") as temporary:
        work = Path(temporary)
        for name in ("home", "runtime", "empty-bundled"):
            (work / name).mkdir()
        snapshot = work / "committed-host"
        report["hermes_source_tree"] = materialize_host(host, report["hermes_commit"], snapshot)
        report["hermes_execution_source"] = "fresh_committed_git_objects"
        plugin = work / "profile" / "plugins" / "hermes-personal-agent"
        shutil.copytree(distribution, plugin)
        builder.verify(repo, commit, plugin)
        scan = run_stage("scan", snapshot, plugin, repo, interpreter, work)
        encoded_scan = json.dumps(scan, sort_keys=True)
        if any(str(path) in encoded_scan for path in (work, repo, host, interpreter)):
            raise ValueError("scanner report contains a machine path")
        report["plugin_guard"] = scan  # Entire unchanged result, including medium findings.
        if scan.get("verdict") != "safe":
            raise ValueError("official plugin_guard verdict is not safe; runtime was not loaded")
        # Recheck after scan and immediately before loading the package.
        builder.verify(repo, commit, plugin)
        verify_host(host, report["hermes_commit"])
        report["acceptance"] = run_stage("runtime", snapshot, plugin, repo, interpreter, work)
        builder.verify(repo, commit, plugin)
        report["conversation_acceptance"] = run_stage(
            "conversation", snapshot, plugin, repo, interpreter, work
        )
        builder.verify(repo, commit, plugin)
    builder.verify(repo, commit, distribution)
    verify_host(host, report["hermes_commit"])
    report["status"] = "passed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--hermes-python", type=Path, required=True)
    parser.add_argument(
        "--report", type=Path, required=True, help="New JSON file outside input trees"
    )
    args = parser.parse_args(argv)
    report_path = safe_path(args.report)
    for root in (args.repo, args.package, args.hermes):
        if report_path.is_relative_to(Path(root).resolve()):
            parser.error("report must be outside source, distribution and host trees")
    report = {
        "schema_version": 1,
        "status": "failed",
        "scope": "offline-runtime-distribution",
        "installation_performed": False,
        "user_profile_activation_performed": False,
        "live_model_calls": False,
    }
    # Exclusive creation prevents replacing user files, including on validation failure.
    with report_path.open("x") as stream:
        try:
            check(
                args.repo,
                args.source_commit,
                args.package,
                args.hermes,
                args.hermes_python,
                report,
            )
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            print(str(error), file=sys.stderr)
            report["error"] = "validation_failed"
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "report": str(report_path)}, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
