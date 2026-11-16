"""Manual evidence for a live profile rename and its retained canonical chat route."""

import asyncio
import json
import sqlite3
from contextlib import closing

import pytest
from native_profile_cli_fixture import (
    SIBLINGS,
    TITLE,
    assert_siblings,
    create_canonical,
    lookup,
    profile_cli_installation,
    retained_host_client,
    roster,
    run_profile_cli,
)
from test_native_profile_retirement import inventory, wait_for_profiles

OLD = "scout"
NEW = "renamed"
LABEL = "profile-rename"


def stored_route(home, session):
    uri = (home / "state.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute("SELECT session_key FROM sessions WHERE id=?", (session,)).fetchone()[0]


def stored_receipt(home, session):
    from hermes_state_local import POLICY_PREFIX

    uri = (home / "state.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(
            "SELECT value FROM state_meta WHERE key=?", (POLICY_PREFIX + session,)
        ).fetchone()[0]


async def assert_rename_refusal(client, session, log):
    from hermes_cli.gateway_client import GatewayRPCError

    with pytest.raises(GatewayRPCError) as old_route:
        await lookup(client, OLD)
    assert (old_route.value.code, old_route.value.data.get("reason")) == (4001, "profile_mismatch")
    with pytest.raises(GatewayRPCError) as title_lookup:
        await lookup(client, NEW)
    assert (title_lookup.value.code, title_lookup.value.data.get("reason")) == (
        4001,
        "storage_unavailable",
    )
    for method in ("session.resume", "session.info"):
        with pytest.raises(GatewayRPCError) as named_read:
            await client.rpc(method, profile=NEW, session_id=session, _timeout=5)
        assert (named_read.value.code, named_read.value.data.get("reason")) == (
            4001,
            "storage_unavailable",
        )
    # Check the refusal cause without publishing the fixture's private log.
    marker = (
        f"Local session {session} receipt refused: ValueError: route mismatch at _checked_entry:"
    )
    assert marker.encode() in log.read_bytes()


async def rename_profile(host, env, homes, old, new):
    result = await asyncio.to_thread(
        run_profile_cli, host, homes["default"], env, "rename", old, new
    )
    if (
        result.returncode
        or f"Renamed {old} → {new}" not in result.stdout
        or "live gateway could not migrate session identity" in result.stderr
    ):
        pytest.fail("Native CLI did not confirm the expected live rename", pytrace=False)
    old_home = homes.pop(old)
    renamed = homes[new] = old_home.with_name(new)
    assert not old_home.exists() and renamed.is_dir()
    return renamed


async def verify_rename(host, env, homes, workspace, endpoint):
    from gateway.status import get_process_start_time
    from hermes_cli.profiles import read_profile_meta

    home = homes["default"]
    identity = await wait_for_profiles(homes, homes)
    pid, instance = identity
    assert instance == endpoint.instance_id
    start = get_process_start_time(pid)
    assert start is not None
    async with asyncio.timeout(68), retained_host_client(home, endpoint) as client:
        await assert_siblings(client)
        controls = {name: inventory(homes[name]) for name in SIBLINGS}
        session = await create_canonical(client, OLD, workspace, "fixture-live-profile-rename")
        assert await lookup(client, OLD) == [(session, session)]
        mounted = await client.rpc("session.resume", profile=OLD, session_id=session, _timeout=5)
        assert mounted["session_id"] == session and mounted["messages"] == []
        before_roster = await roster(client)
        canonical = before_roster[OLD]["canonical_session"]
        assert (canonical["id"], canonical["resolved_id"]) == (session, session)
        before = inventory(homes[OLD])
        assert before[0][1] == instance
        assert before[1:] == ([(session, TITLE, 1, None)], [], [])
        old_route_key = stored_route(homes[OLD], session)
        assert old_route_key.startswith(f"agent:{OLD}:")
        receipt = stored_receipt(homes[OLD], session)
        assert json.loads(receipt)["route"] == old_route_key

        renamed = await rename_profile(host, env, homes, OLD, NEW)
        assert OLD in read_profile_meta(renamed)["previous_names"]
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == start

        after_roster = await roster(client)
        assert set(after_roster) == set(homes)
        assert after_roster[NEW]["canonical_session"] == canonical
        await assert_rename_refusal(client, session, home.parent / f"{LABEL}.log")

        await assert_siblings(client)
        assert {name: inventory(homes[name]) for name in SIBLINGS} == controls
        after = inventory(renamed)
        assert after[0] == (before[0][0] + 1, instance)
        assert after[1:] == before[1:]
        assert stored_route(renamed, session) == f"agent:{NEW}:" + old_route_key.removeprefix(
            f"agent:{OLD}:"
        )
        assert stored_receipt(renamed, session) == receipt
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == start
        return session, canonical, receipt


async def verify_after_migration(homes, endpoint, session, canonical, receipt, previous_instance):
    home = homes["default"]
    _, instance = await wait_for_profiles(homes, homes)
    assert instance == endpoint.instance_id and instance != previous_instance
    async with retained_host_client(home, endpoint) as client:
        after_roster = await roster(client)
        assert set(after_roster) == set(homes)
        assert after_roster[NEW]["canonical_session"] == canonical
        await assert_rename_refusal(client, session, home.parent / f"{LABEL}-successor.log")
        await assert_siblings(client)
        assert stored_receipt(homes[NEW], session) == receipt


async def verify_inverse_rename(host, env, homes, endpoint, session, canonical, receipt):
    from hermes_cli.gateway_client import GatewayRPCError

    home = homes["default"]
    identity = await wait_for_profiles(homes, homes)
    before = inventory(homes[NEW])
    controls = {name: inventory(homes[name]) for name in SIBLINGS}
    async with asyncio.timeout(68), retained_host_client(home, endpoint) as client:
        restored = await rename_profile(host, env, homes, NEW, OLD)
        assert await wait_for_profiles(homes, homes) == identity
        with pytest.raises(GatewayRPCError) as removed_route:
            await lookup(client, NEW)
        assert (removed_route.value.code, removed_route.value.data.get("reason")) == (
            4001,
            "profile_mismatch",
        )
        restored_roster = await roster(client)
        assert set(restored_roster) == set(homes)
        assert restored_roster[OLD]["canonical_session"] == canonical
        assert await lookup(client, OLD) == [(session, session)]
        resumed = await client.rpc("session.resume", profile=OLD, session_id=session, _timeout=5)
        assert resumed["session_id"] == session and resumed["messages"] == []
        assert stored_route(restored, session) == json.loads(receipt)["route"]
        assert stored_receipt(restored, session) == receipt
        after = inventory(restored)
        assert after[0] == (before[0][0] + 1, identity[1])
        assert after[1:] == before[1:]
        await assert_siblings(client)
        assert {name: inventory(homes[name]) for name in SIBLINGS} == controls


def test_native_canonical_chat_requires_original_profile_route_after_rename(
    tmp_path_factory, monkeypatch
):
    with profile_cli_installation(tmp_path_factory, monkeypatch) as (
        cli_source,
        cli_env,
        homes,
        workspace,
        serve,
    ):
        with serve(LABEL) as endpoint:
            session, canonical, receipt = asyncio.run(
                verify_rename(cli_source, cli_env, homes, workspace, endpoint)
            )
        renamed = homes[NEW]
        route = stored_route(renamed, session)
        before_retry = {name: inventory(profile) for name, profile in homes.items()}
        for _ in range(2):
            result = run_profile_cli(
                cli_source, homes["default"], cli_env, "migrate-identity", OLD, NEW
            )
            assert result.returncode == 0
            assert f"Session/routing identity migrated: {OLD} → {NEW}" in result.stdout
            assert stored_route(renamed, session) == route
            assert stored_receipt(renamed, session) == receipt
            assert {name: inventory(profile) for name, profile in homes.items()} == before_retry
        with serve(f"{LABEL}-successor") as successor:
            asyncio.run(
                verify_after_migration(
                    homes, successor, session, canonical, receipt, endpoint.instance_id
                )
            )
            for name, profile in homes.items():
                after = inventory(profile)
                assert after[0][0] > before_retry[name][0][0]
                assert after[0][1] == successor.instance_id
                assert after[1:] == before_retry[name][1:]
            assert stored_route(renamed, session) == route
            asyncio.run(
                verify_inverse_rename(
                    cli_source, cli_env, homes, successor, session, canonical, receipt
                )
            )
