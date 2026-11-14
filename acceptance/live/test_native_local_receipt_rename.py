"""Opt-in acceptance of the review-only stopped LOCAL receipt rename."""

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest
from native_profile_cli_fixture import (
    SIBLINGS,
    assert_siblings,
    create_canonical,
    lookup,
    profile_cli_installation,
    retained_host_client,
    roster,
    run_profile_cli,
)
from test_native_profile_rename import NEW, OLD, stored_receipt, stored_route
from test_native_profile_retirement import inventory, wait_for_profiles

PROPOSAL = Path(__file__).resolve().parents[2] / "experiments/local-receipt-rename"
RENAME = ("rename", OLD, NEW, "--preserve-local-sessions")
REQUEST = "fixture-local-receipt-rename"
LABEL = "local-receipt-rename"
TIP = "fixture-rename-tip"
MESSAGE = "Synthetic continuation after compression"
INPUT = "fixture-rename-input"


async def seed_session(host, env, homes, workspace, endpoint):
    home = homes["default"]
    await wait_for_profiles(homes, homes)
    async with retained_host_client(home, endpoint) as client:
        await assert_siblings(client)
        session = await create_canonical(client, OLD, workspace, REQUEST)
        assert await lookup(client, OLD) == [(session, session)]
        receipt = stored_receipt(homes[OLD], session)
        result = await asyncio.to_thread(run_profile_cli, host, home, env, *RENAME)
        assert result.returncode != 0
        assert "Exclusive maintenance refused" in result.stdout + result.stderr
        assert homes[OLD].is_dir() and not homes[OLD].with_name(NEW).exists()
        assert await lookup(client, OLD) == [(session, session)]
        assert stored_receipt(homes[OLD], session) == receipt
        return session, receipt


def prepare_history(profile, session, receipt):
    from hermes_state import SessionDB
    from hermes_state_runtime import admit_session_input

    with SessionDB(profile / "state.db") as db:
        epoch = inventory(profile)[0][0]
        admitted = admit_session_input(
            db,
            epoch=epoch,
            principal_id=receipt["principal_id"],
            session_id=session,
            request_id=INPUT,
            payload={"text": "Synthetic accepted input"},
        )
        assert db.try_acquire_compression_lock(session, LABEL)
        try:
            db.append_message(session, "user", "Synthetic original message")
            db.publish_compression_child(
                parent_session_id=session,
                child_session_id=TIP,
                source="cli",
                messages=[{"role": "user", "content": MESSAGE}],
                compression_lock_holder=LABEL,
            )
        finally:
            db.release_compression_lock(session, LABEL)
        assert db.set_session_hidden(TIP, True)
        return admitted["admission_id"], epoch


async def check_reopened(homes, endpoint, session, workspace):
    from hermes_cli.gateway_client import GatewayRPCError

    await wait_for_profiles(homes, homes)
    async with retained_host_client(homes["default"], endpoint) as client:
        with pytest.raises(GatewayRPCError) as expired_route:
            await lookup(client, OLD)
        assert (expired_route.value.code, expired_route.value.data.get("reason")) == (
            4001,
            "profile_mismatch",
        )
        assert await lookup(client, NEW) == [(session, session)]
        canonical = (await roster(client))[NEW]["canonical_session"]
        assert (canonical["id"], canonical["resolved_id"]) == (session, TIP)
        info = await client.rpc("session.info", profile=NEW, session_id=session, _timeout=5)
        resumed = await client.rpc("session.resume", profile=NEW, session_id=session, _timeout=5)
        assert info["profile_name"] == NEW and info["cwd"] == str(workspace)
        assert resumed["session_id"] == session
        assert any(row["content"] == MESSAGE for row in resumed["messages"])
        assert await create_canonical(client, NEW, workspace, REQUEST) == session
        await assert_siblings(client)


def test_explicit_offline_rename_preserves_existing_local_receipt(tmp_path_factory, monkeypatch):
    if os.environ.get("HERMES_REVIEW_LOCAL_RECEIPT_RENAME") != "1":
        pytest.skip("Requires an explicit, verified LOCAL receipt rename candidate")
    with profile_cli_installation(tmp_path_factory, monkeypatch, proposal=PROPOSAL) as (
        cli_source,
        cli_env,
        homes,
        workspace,
        serve,
    ):
        with serve(LABEL) as endpoint:
            session, raw_receipt = asyncio.run(
                seed_session(cli_source, cli_env, homes, workspace, endpoint)
            )
        home, source = homes["default"], homes[OLD]
        from hermes_state import SessionDB
        from hermes_state_runtime import cancel_session_input

        admission, epoch = prepare_history(source, session, json.loads(raw_receipt))
        pending = {name: inventory(profile) for name, profile in homes.items()}
        raw_receipt = stored_receipt(source, session)
        assert json.loads(raw_receipt)["lineage"] == [session, TIP]
        state = source / "state.db"
        inode = state.stat()
        destination = source.with_name(NEW)
        destination.mkdir()
        refused = run_profile_cli(cli_source, home, cli_env, *RENAME)
        assert refused.returncode != 0
        assert "destination profile already exists" in refused.stdout + refused.stderr
        destination.rmdir()
        result = run_profile_cli(cli_source, home, cli_env, *RENAME)
        assert result.returncode != 0 and "session_busy" in result.stdout + result.stderr
        assert source.is_dir() and not source.with_name(NEW).exists()
        assert {name: inventory(profile) for name, profile in homes.items()} == pending
        assert stored_receipt(source, session) == raw_receipt
        with SessionDB(state) as db:
            cancelled = cancel_session_input(db, epoch=epoch, admission_id=admission)
        assert (cancelled["status"], cancelled["outcome"]) == ("terminal", "cancelled")
        before = {name: inventory(profile) for name, profile in homes.items()}
        # A separate directory with the same stored bytes cannot replace the admitted home.
        copied = source.with_name("copy-control")
        shutil.copytree(source, copied)
        destination.symlink_to(copied, target_is_directory=True)
        refused = run_profile_cli(cli_source, home, cli_env, *RENAME)
        assert refused.returncode != 0 and destination.is_symlink()
        destination.unlink()
        assert stored_receipt(copied, session) == raw_receipt
        shutil.rmtree(copied)
        result = run_profile_cli(cli_source, home, cli_env, *RENAME)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"Profile renamed: {OLD} → {NEW}" in result.stdout
        homes[NEW] = homes.pop(OLD).with_name(NEW)
        assert not source.exists()
        renamed = homes[NEW]
        moved = (renamed / "state.db").stat()
        assert (moved.st_dev, moved.st_ino) == (inode.st_dev, inode.st_ino)

        original = json.loads(raw_receipt)
        expected = json.loads(raw_receipt)
        route = f"agent:{NEW}:" + original["route"].removeprefix(f"agent:{OLD}:")
        expected["route"] = expected["entry"]["session_key"] = route
        expected["entry"]["origin"]["profile"] = NEW
        assert json.loads(stored_receipt(renamed, session)) == expected
        assert stored_route(renamed, session) == route
        after_receipt = stored_receipt(renamed, session)

        refused = run_profile_cli(cli_source, home, cli_env, *RENAME)
        assert refused.returncode != 0
        result = run_profile_cli(cli_source, home, cli_env, "migrate-identity", OLD, NEW)
        assert result.returncode == 0
        assert stored_receipt(renamed, session) == after_receipt
        with serve(f"{LABEL}-successor") as successor:
            assert successor.instance_id != endpoint.instance_id
            asyncio.run(check_reopened(homes, successor, session, workspace))
            assert inventory(renamed)[1:] == before[OLD][1:]
            assert {name: inventory(homes[name])[1:] for name in SIBLINGS} == {
                name: before[name][1:] for name in SIBLINGS
            }
            assert stored_receipt(renamed, session) == after_receipt
