"""Stopped native profile lifecycle with synthetic install and conversation state."""

import argparse
import json
import socket
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

INSTALL_ID = "89abcdef0123456789abcdef01234567"
LABEL = "Fixture Bot"


@pytest.fixture
def profile_lifecycle(tmp_path, monkeypatch):
    root = tmp_path / "install"
    user = tmp_path / "user"
    bundled = tmp_path / "empty-bundled"
    scratch = tmp_path / "scratch"
    for path in (root, user, bundled, scratch):
        path.mkdir()
    (root / "config.yaml").write_text('{"model":"synthetic"}', encoding="utf-8")
    install_path = root / "install_id"
    install_path.write_text(f"{INSTALL_ID}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    # Hermes respects an explicit temp directory and skips its detached pruner.
    monkeypatch.setenv("TMPDIR", str(scratch))
    monkeypatch.delenv("HERMES_SCRATCH_DIR", raising=False)

    import pm
    from hermes_cli import env_loader

    forbidden = []

    def refuse(*args, **kwargs):
        forbidden.append("Unexpected profile lifecycle network, subprocess or SDK call")
        raise AssertionError(forbidden[-1])

    bind = socket.socket.bind

    def bind_ipv6_probe(sock, address):
        # urllib3's import-time local IPv6 probe never listens or connects.
        if (
            sock.family == socket.AF_INET6
            and sock.type == socket.SOCK_STREAM
            and address == ("::1", 0)
        ):
            return bind(sock, address)
        return refuse()

    monkeypatch.setattr(pm, "ensure_import", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "bind", bind_ipv6_probe)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket.socket, "listen", refuse)
    with monkeypatch.context() as startup:
        startup.setattr(env_loader, "load_hermes_dotenv", lambda *args, **kwargs: [])
        startup.setattr(env_loader, "apply_config_bootstrap_env", lambda *args, **kwargs: None)
        from hermes_cli import profile_cmd, profiles
        from hermes_cli.install_identity import get_install_id
        from hermes_cli.subcommands.profile import build_profile_parser
        from hermes_constants import get_default_hermes_root

    # Keep profile publication, rekey, purge and maintenance locks native.
    # These hooks address the service manager or live processes outside them.
    monkeypatch.setattr(profiles, "_cleanup_gateway_service", lambda *args: False)
    monkeypatch.setattr(profiles, "_stop_gateway_process", refuse)
    for name in (
        "_maybe_register_gateway_service",
        "_maybe_unregister_gateway_service",
        "_notify_multiplexer",
        "_stop_profile_backends",
        "_stop_bot_desktop",
    ):
        monkeypatch.setattr(profiles, name, lambda *args: None)
    monkeypatch.setattr(
        profiles, "check_alias_collision", lambda name: "fixture skips shell wrappers"
    )

    def skip_skill_sync(home):
        # The CLI invokes a child skill-sync process even for an opt-out profile.
        assert (home / profiles.NO_BUNDLED_SKILLS_MARKER).is_file()
        return {"skipped_opt_out": True}

    monkeypatch.setattr(profiles, "seed_profile_skills", skip_skill_sync)
    parser = argparse.ArgumentParser(prog="hermes")
    build_profile_parser(parser.add_subparsers(), cmd_profile=profile_cmd.cmd_profile)

    def run(*args):
        parsed = parser.parse_args(["profile", *args])
        return parsed.func(parsed)

    assert get_default_hermes_root() == root
    assert get_install_id(cache={}) == INSTALL_ID
    try:
        yield SimpleNamespace(root=root, profiles=profiles, run=run, install_id=INSTALL_ID)
    finally:
        assert install_path.read_text(encoding="utf-8") == f"{INSTALL_ID}\n"
        assert not (root / ".install_id.lock").exists()
        assert not forbidden


def test_rename_clone_and_recreate_keep_profile_name_separate_from_session_lineage(
    profile_lifecycle, capsys
):
    from hermes_cli.install_identity import get_install_id
    from hermes_constants import named_profile_is_deleted
    from hermes_state import SessionDB

    native = profile_lifecycle
    old, moved = "old-bot", "renamed-bot"
    old_home = native.profiles.get_profile_dir(old)
    moved_home = native.profiles.get_profile_dir(moved)
    root_id, tip_id = "local-lifecycle-root", "lifecycle-tip"
    route, moved_route = (f"agent:{name}:feishu:dm:lifecycle" for name in (old, moved))
    unrelated = "agent:other-bot:feishu:dm:control"
    scope = str(native.root / "sessions")
    marker = Path("plugin-data/lifecycle-fixture/marker.txt")

    native.run("create", old, "--no-alias", "--no-skills")
    native.run("use", old)
    native.profiles.write_profile_meta(old_home, display_name=LABEL)
    (old_home / marker).parent.mkdir(parents=True)
    (old_home / marker).write_text("Synthetic profile data\n", encoding="utf-8")
    (old_home / "cron" / "jobs.json").write_text('{"jobs":[]}', encoding="utf-8")
    with closing(SessionDB(old_home / "state.db")) as db:
        db.create_session(root_id, source="local", chat_id=root_id, profile_name=old)
        assert db.set_session_title(root_id, "Bot Chat")
        db.end_session(root_id, "compression")
        db.create_session(tip_id, source="local", parent_session_id=root_id)
        assert db.set_session_title(tip_id, "Bot Chat continued")
        assert db.set_session_hidden(root_id, True)
        db.append_message(tip_id, "user", "Synthetic conversation marker")
        assert db.get_compression_tip(root_id) == tip_id

    with closing(SessionDB(native.root / "state.db")) as db:
        db.save_gateway_routing_entry(
            route,
            json.dumps({"session_key": route, "session_id": root_id, "origin": {"profile": old}}),
            scope=scope,
        )
        control = json.dumps({"session_key": unrelated})
        db.save_gateway_routing_entry(unrelated, control, scope=scope)
        assert set(db.load_gateway_routing_entries(scope=scope)) == {route, unrelated}

    native.run("rename", old, moved)

    assert not old_home.exists()
    with pytest.raises(FileNotFoundError, match="does not exist"):
        native.profiles.resolve_profile_env(old)
    assert Path(native.profiles.resolve_profile_env(moved)) == moved_home
    assert native.profiles.get_active_profile() == moved
    info = next(profile for profile in native.profiles.list_profiles() if profile.name == moved)
    assert (info.display_name, info.previous_names) == (LABEL, [old])
    with closing(SessionDB(moved_home / "state.db")) as db:
        canonical = db.get_session_by_title("Bot Chat")
        assert canonical["id"] == root_id and canonical["hidden"]
        assert canonical["profile_name"] == moved
        assert db.get_compression_tip(root_id) == tip_id
        assert db.get_session(tip_id)["profile_name"] == moved
        assert [message["content"] for message in db.get_messages(tip_id)] == [
            "Synthetic conversation marker"
        ]
    with closing(SessionDB(native.root / "state.db")) as db:
        entries = db.load_gateway_routing_entries(scope=scope)
        assert set(entries) == {moved_route, unrelated}
        assert entries[unrelated] == control
        assert json.loads(entries[moved_route]) == {
            "session_key": moved_route,
            "session_id": root_id,
            "origin": {"profile": moved},
        }

    native.run("create", old, "--clone-from", moved, "--clone-all", "--no-alias")

    listed = {profile.name: profile for profile in native.profiles.list_profiles()}
    assert Path(native.profiles.resolve_profile_env(old)) == old_home
    assert listed[old].display_name == listed[moved].display_name == LABEL
    assert listed[old].previous_names == listed[moved].previous_names == [old]
    assert (old_home / marker).read_text(encoding="utf-8") == "Synthetic profile data\n"
    assert not (old_home / "state.db").exists()
    assert not (old_home / "cron" / "jobs.json").exists()
    assert (moved_home / "state.db").is_file()

    capsys.readouterr()
    # The tombstone blocks reopening the removed profile's store. The root
    # routing purge succeeds, but the CLI reports the local settlement pending.
    with pytest.raises(SystemExit) as pending:
        native.run("delete", moved, "--yes")
    assert pending.value.code == 1
    deletion = capsys.readouterr()
    assert f"identity purge failed for {moved_home / 'state.db'}: FileNotFoundError" in deletion.err
    assert f"hermes profile purge-identity {moved}" in deletion.out

    assert not moved_home.exists()
    assert named_profile_is_deleted(moved_home)
    assert not native.profiles.profile_exists(moved)
    assert native.profiles.get_active_profile() == "default"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        native.profiles.resolve_profile_env(moved)
    with closing(SessionDB(native.root / "state.db")) as db:
        assert db.load_gateway_routing_entries(scope=scope) == {unrelated: control}

    native.run("purge-identity", moved)
    assert "Session/routing identity purged" in capsys.readouterr().out

    native.run("create", moved, "--no-alias", "--no-skills")

    assert Path(native.profiles.resolve_profile_env(moved)) == moved_home
    assert not named_profile_is_deleted(moved_home)
    listed = {profile.name: profile for profile in native.profiles.list_profiles()}
    assert listed[old].previous_names == [old]
    assert listed[moved].previous_names == []
    assert not (moved_home / marker).exists()
    assert not (moved_home / "state.db").exists()
    with closing(SessionDB(moved_home / "state.db")) as db:
        assert db.get_session_by_title("Bot Chat") is None
        assert db.get_session(root_id) is None and db.get_session(tip_id) is None
    assert get_install_id(cache={}) == native.install_id
