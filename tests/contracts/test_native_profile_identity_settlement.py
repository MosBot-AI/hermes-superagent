"""Native profile filesystem changes and durable identity settlement can finish separately."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_native_profile_lifecycle import profile_lifecycle as profile_lifecycle


def read_durable_state(db_path, scope):
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as conn:
        return {
            "routes": dict(
                conn.execute(
                    "SELECT session_key, entry_json FROM gateway_routing WHERE scope = ?", (scope,)
                )
            ),
            "heartbeats": conn.execute(
                "SELECT backend_id, profile FROM gateway_heartbeats ORDER BY backend_id"
            ).fetchall(),
            "sessions": conn.execute("SELECT * FROM sessions ORDER BY id").fetchall(),
            "messages": conn.execute("SELECT * FROM messages ORDER BY id").fetchall(),
        }


def test_removed_profile_reports_pending_identity_and_native_retry_settles_only_its_routing(
    profile_lifecycle, monkeypatch, capsys
):
    from gateway import control_socket
    from hermes_constants import named_profile_is_deleted
    from hermes_state import SessionDB

    native = profile_lifecycle
    name = "settlement-bot"
    neighbor = "settlement-bot-neighbor"
    native.run("create", name, "--no-alias", "--no-skills")
    home = native.profiles.get_profile_dir(name)
    db_path = native.root / "state.db"
    scope = str(native.root / "sessions")
    old_key = f"agent:{name}:feishu:dm:fixture"
    neighbor_key = f"agent:{neighbor}:feishu:dm:fixture"
    with closing(SessionDB(db_path)) as db:
        db.create_session("root-history", source="feishu", session_key=old_key, profile_name=name)
        db.append_message("root-history", "user", "Synthetic retained history")
        for key, profile, backend_id in (
            (old_key, name, "fixture-old"),
            (neighbor_key, neighbor, "fixture-neighbor"),
        ):
            entry = json.dumps({"session_key": key, "origin": {"profile": profile}})
            db.save_gateway_routing_entry(key, entry, scope=scope)
            db.register_backend_heartbeat(
                backend_id=backend_id, pid=1, started_at=1.0, profile=profile, host="synthetic"
            )
    before = read_durable_state(db_path, scope)
    assert set(before["routes"]) == {old_key, neighbor_key}
    assert before["heartbeats"] == [("fixture-neighbor", neighbor), ("fixture-old", name)]
    assert before["sessions"] and before["messages"]

    owner_calls = []

    def refuse_purge(root, profile):
        owner_calls.append((root, profile, home.is_dir(), named_profile_is_deleted(home)))
        return {"ok": False, "error": "synthetic settlement refusal"}

    capsys.readouterr()
    with monkeypatch.context() as live:
        live.setattr(native.profiles, "_live_default_multiplexer", lambda: True)
        live.setattr(control_socket, "purge_gateway_profile_identity", refuse_purge)
        with pytest.raises(native.profiles.ProfileIdentitySettlementPending) as caught:
            native.profiles.delete_profile(name, yes=True)

    assert owner_calls == [(native.root, name, True, True)]
    assert caught.value.profile == name and caught.value.path == home
    assert caught.value.retry_command == f"hermes profile purge-identity {name}"
    assert caught.value.retry_command in capsys.readouterr().err
    assert not home.exists() and named_profile_is_deleted(home)
    assert not native.profiles.profile_exists(name)
    assert read_durable_state(db_path, scope) == before

    native.run("purge-identity", name)
    settled = read_durable_state(db_path, scope)
    assert settled == {
        **before,
        "routes": {neighbor_key: before["routes"][neighbor_key]},
        "heartbeats": [("fixture-neighbor", neighbor)],
    }
    native.run("purge-identity", name)
    assert read_durable_state(db_path, scope) == settled
    assert not home.exists() and named_profile_is_deleted(home)

    native.run("create", name, "--no-alias", "--no-skills")
    assert native.profiles.profile_exists(name) and not named_profile_is_deleted(home)
    new_entry = json.dumps({"session_key": old_key, "session_id": "fresh-fixture-chat"})
    with closing(SessionDB(db_path)) as db:
        db.save_gateway_routing_entry(old_key, new_entry, scope=scope)
    capsys.readouterr()
    with pytest.raises(SystemExit) as refusal:
        native.run("purge-identity", name)
    assert refusal.value.code == 1
    assert "exists; purge-identity only settles" in capsys.readouterr().out
    assert read_durable_state(db_path, scope) == {
        **settled,
        "routes": {**settled["routes"], old_key: new_entry},
    }


def test_rename_replays_durable_rekey_after_a_real_profile_store_collision(
    profile_lifecycle, capsys
):
    from hermes_state import SessionDB

    native = profile_lifecycle
    old, new = "rekey-old", "rekey-new"
    native.run("create", old, "--no-alias", "--no-skills")
    old_home, new_home = (native.profiles.get_profile_dir(name) for name in (old, new))
    root_path = native.root / "state.db"
    scope = str(native.root / "sessions")
    old_key, new_key = (f"agent:{name}:feishu:dm:fixture" for name in (old, new))
    root_id, tip_id = "local-rekey-root", "local-rekey-tip"
    old_entry = {"session_key": old_key, "session_id": root_id, "origin": {"profile": old}}
    expected_entry = {"session_key": new_key, "session_id": root_id, "origin": {"profile": new}}
    with closing(SessionDB(root_path)) as db:
        db.save_gateway_routing_entry(old_key, json.dumps(old_entry), scope=scope)
    with closing(SessionDB(old_home / "state.db")) as db:
        db.create_session(
            root_id, source="local", chat_id=root_id, session_key=old_key, profile_name=old
        )
        assert db.set_session_title(root_id, "Bot Chat")
        assert db.set_session_hidden(root_id, True)
        db.end_session(root_id, "compression")
        db.create_session(tip_id, source="local", parent_session_id=root_id, profile_name=old)
        db.append_message(tip_id, "user", "Synthetic history across rename")
        assert db.get_compression_chain(root_id) == [root_id, tip_id]
        db.save_gateway_routing_entry(old_key, json.dumps(old_entry), scope=scope)
        db.save_gateway_routing_entry(new_key, json.dumps({"session_key": new_key}), scope=scope)
    before = read_durable_state(old_home / "state.db", scope)
    assert set(before["routes"]) == {old_key, new_key}

    capsys.readouterr()
    native.run("rename", old, new)
    err = capsys.readouterr().err
    assert not old_home.exists() and new_home.is_dir()
    new_path = new_home / "state.db"
    assert f"identity migration failed for {new_path}" in err
    assert "profile routing collision" in err
    root_rekeyed = read_durable_state(root_path, scope)
    assert {key: json.loads(value) for key, value in root_rekeyed["routes"].items()} == {
        new_key: expected_entry
    }
    assert read_durable_state(new_path, scope) == before

    with pytest.raises(SystemExit) as still_blocked:
        native.run("migrate-identity", old, new)
    assert still_blocked.value.code == 1
    assert f"hermes profile migrate-identity {old} {new}" in capsys.readouterr().err
    assert read_durable_state(root_path, scope) == root_rekeyed
    assert read_durable_state(new_path, scope) == before

    # Remove only the synthetic route occupying the destination in the moved store.
    with closing(sqlite3.connect(new_path)) as conn, conn:
        removed = conn.execute(
            "DELETE FROM gateway_routing WHERE scope = ? AND session_key = ?", (scope, new_key)
        ).rowcount
        assert removed == 1
    native.run("migrate-identity", old, new)
    repaired = read_durable_state(new_path, scope)
    assert {key: json.loads(value) for key, value in repaired["routes"].items()} == {
        new_key: expected_entry
    }
    assert repaired["messages"] == before["messages"]
    with closing(SessionDB(new_path)) as db:
        assert db.get_compression_chain(root_id) == [root_id, tip_id]
        for session_id in (root_id, tip_id):
            row = db.get_session(session_id)
            assert (row["profile_name"], row["session_key"]) == (new, new_key)

    native.run("migrate-identity", old, new)
    assert read_durable_state(root_path, scope) == root_rekeyed
    assert read_durable_state(new_path, scope) == repaired
