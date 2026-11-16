"""Stopped native backup/import of Bot lineage and the runtime epoch floor."""

import argparse
import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing, contextmanager
from types import SimpleNamespace

import pytest
from test_native_profile_lifecycle import profile_lifecycle as profile_lifecycle
from test_native_voice_audio_asgi import run_native_async

PROFILE = "restore-bot"
SUBJECT = "uid:restore-fixture"
TIP = "synthetic-compression-tip"
ARCHIVED_TEXT = "Synthetic backup transcript"


def read_epoch(home):
    uri = (home / "state.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        return conn.execute("SELECT epoch, instance_id FROM runtime_epoch").fetchone()


def test_native_backup_import_fences_held_profile_and_recovers_stopped_bot(
    profile_lifecycle, tmp_path, monkeypatch, capsys
):
    from gateway import session_finite, status
    from gateway.config import GatewayConfig
    from gateway.runtime_ownership import ProfileOwnership
    from gateway.session import SessionStore
    from gateway.session_authority import SessionAuthority, initialize_session_authority
    from gateway.session_contract import SessionActor, SessionRef
    from gateway.session_cron import unbind_owner
    from gateway.session_group_controls import _read_bot_sessions
    from gateway.session_local import create_local_session
    from gateway.session_local_title import title_new_session
    from hermes_cli import backup
    from hermes_cli.install_identity import get_install_id
    from hermes_cli.subcommands.backup import build_backup_parser
    from hermes_cli.subcommands.import_cmd import build_import_cmd_parser
    from hermes_state import SessionDB
    from hermes_state_runtime import (
        RuntimeStoreError,
        admit_session_input,
        begin_runtime_epoch,
        claim_session_input,
        list_session_admissions,
    )

    native = profile_lifecycle
    native.run("create", PROFILE, "--no-alias", "--no-skills")
    source = native.root
    named = native.profiles.get_profile_dir(PROFILE)
    archive = tmp_path / "native-backup.zip"
    restored = tmp_path / "separate-install"
    restored.mkdir(mode=0o700)
    separate_named = restored / "profiles" / PROFILE
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "scratch"))

    service_destinations = []
    monkeypatch.setattr(backup, "_revive_gateway_after_import", service_destinations.append)
    monkeypatch.setattr(status, "publish_runtime_status", lambda **kwargs: 0)
    execution_attempts = []

    def refuse_execution(*args, **kwargs):
        execution_attempts.append("Unexpected scheduling or execution")
        raise AssertionError(execution_attempts[-1])

    monkeypatch.setattr(SessionAuthority, "_schedule", refuse_execution)
    monkeypatch.setattr(session_finite, "execute_finite_admission", refuse_execution)

    parser = argparse.ArgumentParser(prog="hermes")
    subcommands = parser.add_subparsers()
    build_backup_parser(subcommands, cmd_backup=backup.run_backup)
    build_import_cmd_parser(subcommands, cmd_import=backup.run_import)

    def run_backup_command(*args):
        parsed = parser.parse_args(args)
        return parsed.func(parsed)

    @contextmanager
    def reserve(home):
        owner = ProfileOwnership()
        owner.reserve([home])
        try:
            yield owner
        finally:
            owner.close()

    @contextmanager
    def use_store(home):
        with monkeypatch.context() as scope:
            scope.setenv("HERMES_HOME", str(home))
            config = GatewayConfig()
            store = SessionStore(home / "sessions", config)
            runner = SimpleNamespace(
                config=config,
                session_store=store,
                adapters={},
                _draining=False,
                _handle_message=refuse_execution,
            )
            with closing(store._db) as db:
                yield runner, db

    # The named store is bound before publication and carries a real local policy
    # and compression routing receipt. The root store is an independent archive member.
    with closing(SessionDB(source / "state.db")) as default_db:
        default_db.create_session("default-control", source="local")
        default_db.append_message("default-control", "user", "Default backup marker")
    with reserve(named), use_store(named) as (runner, db):
        archived_epoch = begin_runtime_epoch(db, instance_id="before-backup")
        authority = SessionAuthority(
            runner,
            profile_id=str(named),
            instance_id="before-backup",
            db=db,
            epoch=archived_epoch,
        )
        runner.session_authority = authority
        actor = SessionActor(SUBJECT, str(named), frozenset({"session:create"}), "fixture")
        ref = create_local_session(
            authority,
            actor,
            {
                "request_id": "restore-bot",
                "source": "gui",
                "cwd": str(tmp_path),
                "model": "synthetic",
                "toolsets": [],
            },
        )
        root_id = ref.session_id
        title_new_session(authority, ref, "Bot Chat")
        assert db.set_session_hidden(root_id, True)
        holder = "synthetic-compression-owner"
        assert db.try_acquire_compression_lock(root_id, holder)
        try:
            db.publish_compression_child(
                parent_session_id=root_id,
                child_session_id=TIP,
                source="local",
                model="synthetic",
                messages=[{"role": "user", "content": ARCHIVED_TEXT}],
                compression_lock_holder=holder,
            )
        finally:
            db.release_compression_lock(root_id, holder)
        assert db.set_session_title(TIP, "Bot Chat continued")
        assert db.set_session_hidden(TIP, True)
        assert db.get_compression_chain(root_id) == [root_id, TIP]

        def admit(request_id):
            return admit_session_input(
                db,
                epoch=archived_epoch,
                principal_id=SUBJECT,
                session_id=root_id,
                request_id=request_id,
                payload={"text": request_id},
            )

        lost = admit("started-before-backup")
        claimed = claim_session_input(db, epoch=archived_epoch, session_id=root_id)
        assert claimed["admission_id"] == lost["admission_id"] and claimed["status"] == "started"
        follower = admit("queued-before-backup")
        canonical = _read_bot_sessions(db, SUBJECT, operator=False)["canonical_session"]
        assert canonical["id"] == root_id and canonical["resolved_id"] == TIP

    root_runtime = source / "gateway_state.json"
    root_runtime.write_text('{"fixture":"archived runtime marker"}', encoding="utf-8")
    (source / "portable-marker.txt").write_text("archived root marker", encoding="utf-8")
    assert run_backup_command("backup", "--output", str(archive), "--keep", "0") is True
    archive_before = archive.read_bytes()
    with zipfile.ZipFile(archive) as zf:
        members = set(zf.namelist())
        assert {"install_id", "config.yaml", "state.db", "portable-marker.txt"} <= members
        assert {f"profiles/{PROFILE}/state.db", "gateway_state.json"} <= members
        assert json.loads(zf.read(f"profiles/{PROFILE}/gateway.lock"))["hermes_home"] == str(named)
        assert not any(name.endswith((".db-wal", ".db-shm", "gateway.pid")) for name in members)
        assert not any(name.startswith("_external/") for name in members)

    root_runtime.write_text('{"fixture":"destination runtime marker"}', encoding="utf-8")
    marker = source / "portable-marker.txt"
    marker.write_text("newer root marker", encoding="utf-8")
    config = source / "config.yaml"
    archived_config = config.read_bytes()
    config.write_text('{"model":"newer-synthetic"}', encoding="utf-8")
    with closing(SessionDB(source / "state.db")) as default_db:
        default_db.append_message("default-control", "user", "Newer default transcript")
    named_lock = named / "gateway.lock"
    with reserve(named) as held:
        with closing(SessionDB(named / "state.db")) as db:
            later_epoch = begin_runtime_epoch(db, instance_id="after-backup")
            assert later_epoch > archived_epoch
            db.append_message(TIP, "user", "Newer named transcript")
        lock_inode = named_lock.stat().st_ino
        assert not (source / "gateway.pid").exists() and not (named / "gateway.pid").exists()
        protected = (config, marker, root_runtime, source / "state.db", named / "state.db")
        before = {path: path.read_bytes() for path in protected}
        capsys.readouterr()
        with pytest.raises(SystemExit) as refused:
            run_backup_command("import", str(archive), "--force")
        assert refused.value.code == 1
        refusal = capsys.readouterr().out
        assert "Import refused; no files restored" in refusal and str(named) in refusal
        assert {path: path.read_bytes() for path in protected} == before
        assert not service_destinations
        # A rejected multi-home reserve released the root lock it took first.
        with reserve(source) as root_after_refusal:
            assert root_after_refusal.owns(source) and held.owns(named)

    assert run_backup_command("import", str(archive), "--force") is None
    assert config.read_bytes() == archived_config
    assert marker.read_text(encoding="utf-8") == "archived root marker"
    assert root_runtime.read_bytes() == before[root_runtime]
    assert named_lock.stat().st_ino == lock_inode
    assert read_epoch(named) == (later_epoch, "offline-restore")
    assert get_install_id(cache={}) == native.install_id

    with monkeypatch.context() as clone:
        clone.setenv("HERMES_HOME", str(restored))
        assert run_backup_command("import", str(archive), "--force") is None
        assert get_install_id(cache={}) == native.install_id
    assert read_epoch(separate_named) == (archived_epoch, "before-backup")
    assert not (restored / "gateway_state.json").exists()
    assert json.loads((separate_named / "gateway.lock").read_bytes())["hermes_home"] == str(
        separate_named
    )
    assert service_destinations == [source, restored]
    assert archive.read_bytes() == archive_before

    async def verify_startup(runner, db, home, floor, instance, before_start):
        authority = await initialize_session_authority(
            runner, profile_id=str(home), instance_id=instance, db=db
        )
        try:
            assert authority.epoch == floor + 1
            assert db.get_session(root_id)["hidden"]
            assert db.get_compression_chain(root_id) == [root_id, TIP]
            assert [m["content"] for m in db.get_messages(TIP)] == [ARCHIVED_TEXT]
            assert _read_bot_sessions(db, SUBJECT, operator=False)["canonical_session"] == canonical
            actor = SessionActor(
                SUBJECT, str(home), frozenset({"session:submit"}), "restored-fixture"
            )
            restored_ref = SessionRef(str(home), root_id)
            authority.authorize(actor, restored_ref, "session:submit")
            assert authority.physical_target(restored_ref) == TIP
            for epoch, reason in (
                (floor, "stale_epoch"),
                (authority.epoch, "unknown_execution"),
            ):
                with pytest.raises(RuntimeStoreError) as blocked:
                    claim_session_input(db, epoch=epoch, session_id=root_id)
                assert blocked.value.reason == reason
            after_start = list_session_admissions(db, session_id=root_id, pending_only=False)
            assert after_start == [{**before_start[0], "status": "unknown"}, before_start[1]]
        finally:
            unbind_owner(authority)

    for install, home, floor, instance in (
        (source, named, later_epoch, "restored-original"),
        (restored, separate_named, archived_epoch, "restored-separate"),
    ):
        with closing(SessionDB(install / "state.db", read_only=True)) as default_db:
            assert [m["content"] for m in default_db.get_messages("default-control")] == [
                "Default backup marker"
            ]
            assert default_db.get_session(root_id) is None
        with reserve(home), use_store(home) as (runner, db):
            before_start = list_session_admissions(db, session_id=root_id, pending_only=False)
            assert [(r["admission_id"], r["status"]) for r in before_start] == [
                (lost["admission_id"], "started"),
                (follower["admission_id"], "queued"),
            ]

            run_native_async(verify_startup(runner, db, home, floor, instance, before_start))
        assert read_epoch(home) == (floor + 1, instance)
    assert not execution_attempts
