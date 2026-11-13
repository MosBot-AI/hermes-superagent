"""Manual evidence for live deletion and a fresh profile at the same route."""

import asyncio

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

PROFILE = "scout"
LABEL = "profile-recreate"


async def verify_recreate(host, env, homes, workspace, endpoint):
    from gateway.status import get_process_start_time
    from hermes_cli.gateway_client import GatewayRPCError
    from hermes_cli.profiles import read_profile_meta
    from hermes_constants import named_profile_is_deleted

    home, scout = (homes[name] for name in ("default", PROFILE))
    canary = scout / "fixture-incarnation"
    canary.write_text("Synthetic original profile marker", encoding="utf-8")
    identity = await wait_for_profiles(homes, homes)
    pid, instance = identity
    assert instance == endpoint.instance_id
    birth = get_process_start_time(pid)
    assert birth is not None

    async with asyncio.timeout(85), retained_host_client(home, endpoint) as client:
        await assert_siblings(client)
        controls = {name: inventory(homes[name]) for name in SIBLINGS}
        old_id = await create_canonical(client, PROFILE, workspace, "fixture-recreate-original")
        assert await lookup(client, PROFILE) == [(old_id, old_id)]
        mounted = await client.rpc("session.resume", profile=PROFILE, session_id=old_id, _timeout=5)
        assert mounted["session_id"] == old_id and mounted["messages"] == []
        old_canonical = (await roster(client))[PROFILE]["canonical_session"]
        assert (old_canonical["id"], old_canonical["resolved_id"]) == (old_id, old_id)
        old_store = inventory(scout)  # Returns materialized rows and closes every SQLite handle.
        assert old_store[0][1] == instance and old_store[1:] == ([(old_id, TITLE, 1, None)], [], [])

        deleted = await asyncio.to_thread(
            run_profile_cli, host, home, env, "delete", PROFILE, "--yes"
        )
        if deleted.returncode or f"Profile '{PROFILE}' deleted." not in deleted.stdout:
            pytest.fail("Native CLI did not confirm a settled profile delete", pytrace=False)
        assert not scout.exists() and named_profile_is_deleted(scout)
        del homes[PROFILE]
        assert await wait_for_profiles(homes, homes) == identity
        assert set(await roster(client)) == set(homes)
        with pytest.raises(GatewayRPCError) as old_title:
            await lookup(client, PROFILE)
        assert (old_title.value.code, old_title.value.data.get("reason")) == (
            4001,
            "profile_mismatch",
        )
        with pytest.raises(GatewayRPCError) as old_route:
            await client.rpc("session.info", profile=PROFILE, session_id=old_id, _timeout=5)
        assert (old_route.value.code, old_route.value.data.get("reason")) == (
            4001,
            "profile_mismatch",
        )
        await assert_siblings(client)

        created = await asyncio.to_thread(
            run_profile_cli, host, home, env, "create", PROFILE, "--no-alias", "--no-skills"
        )
        if created.returncode or f"Profile '{PROFILE}' created" not in created.stdout:
            pytest.fail("Native CLI did not confirm a fresh profile create", pytrace=False)
        homes[PROFILE] = scout
        assert scout.is_dir() and not named_profile_is_deleted(scout)
        assert not canary.exists() and not read_profile_meta(scout).get("previous_names")
        assert (scout / ".no-bundled-skills").is_file()
        assert all(
            not line.strip() or line.lstrip().startswith("#")
            for line in (scout / ".env").read_text(encoding="utf-8").splitlines()
        )

        # Only ordinary create notification and native reconcile can serve this new home.
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == birth
        fresh = inventory(scout)
        assert fresh[0][1] == instance and fresh[1:] == ([], [], [])
        fresh_roster = await roster(client)
        assert set(fresh_roster) == set(homes)
        assert fresh_roster[PROFILE]["canonical_session"] is None
        assert await lookup(client, PROFILE) == []
        with pytest.raises(GatewayRPCError) as missing:
            await client.rpc("session.info", profile=PROFILE, session_id=old_id, _timeout=5)
        assert (missing.value.code, missing.value.data.get("reason")) == (4001, "not_found")

        new_id = await create_canonical(client, PROFILE, workspace, "fixture-recreate-replacement")
        assert new_id != old_id
        assert await lookup(client, PROFILE) == [(new_id, new_id)]
        mounted = await client.rpc("session.resume", profile=PROFILE, session_id=new_id, _timeout=5)
        assert mounted["session_id"] == new_id and mounted["messages"] == []
        canonical = (await roster(client))[PROFILE]["canonical_session"]
        assert (canonical["id"], canonical["resolved_id"]) == (new_id, new_id)
        assert inventory(scout) == (fresh[0], [(new_id, TITLE, 1, None)], [], [])
        await assert_siblings(client)
        assert {name: inventory(homes[name]) for name in SIBLINGS} == controls
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == birth


def test_native_live_recreate_does_not_inherit_canonical_chat(tmp_path_factory, monkeypatch):
    with profile_cli_gateway(tmp_path_factory, monkeypatch, LABEL) as fixture:
        asyncio.run(verify_recreate(*fixture))
