"""Manual evidence for a live profile rename and its retained canonical chat route."""

import asyncio
import sqlite3
from contextlib import closing

import pytest
from native_profile_cli_fixture import (
    SIBLINGS,
    TITLE,
    assert_siblings,
    create_canonical,
    lookup,
    profile_cli_gateway,
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


async def verify_rename(host, env, homes, workspace, endpoint):
    from gateway.status import get_process_start_time
    from hermes_cli.gateway_client import GatewayRPCError
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

        result = await asyncio.to_thread(run_profile_cli, host, home, env, "rename", OLD, NEW)
        if (
            result.returncode
            or f"Renamed {OLD} → {NEW}" not in result.stdout
            or "live gateway could not migrate session identity" in result.stderr
        ):
            pytest.fail("Native CLI did not confirm the expected live rename", pytrace=False)
        old_home = homes.pop(OLD)
        renamed = homes[NEW] = old_home.with_name(NEW)
        assert not old_home.exists() and renamed.is_dir()
        assert OLD in read_profile_meta(renamed)["previous_names"]
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == start

        after_roster = await roster(client)
        assert set(after_roster) == set(homes)
        assert after_roster[NEW]["canonical_session"] == canonical
        with pytest.raises(GatewayRPCError) as old_route:
            await lookup(client, OLD)
        assert (old_route.value.code, old_route.value.data.get("reason")) == (
            4001,
            "profile_mismatch",
        )
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
        # Test a fixed synthetic diagnostic predicate without displaying the private log.
        marker = (
            f"Local session {session} receipt refused: "
            "ValueError: route mismatch at _checked_entry:"
        ).encode()
        cause_seen = marker in (home.parent / f"{LABEL}.log").read_bytes()
        assert cause_seen

        await assert_siblings(client)
        assert {name: inventory(homes[name]) for name in SIBLINGS} == controls
        after = inventory(renamed)
        assert after[0] == (before[0][0] + 1, instance)
        assert after[1:] == before[1:]
        assert stored_route(renamed, session) == f"agent:{NEW}:" + old_route_key.removeprefix(
            f"agent:{OLD}:"
        )
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == start


def test_native_live_rename_retains_roster_but_refuses_canonical_chat_reads(
    tmp_path_factory, monkeypatch
):
    with profile_cli_gateway(tmp_path_factory, monkeypatch, LABEL) as fixture:
        asyncio.run(verify_rename(*fixture))
