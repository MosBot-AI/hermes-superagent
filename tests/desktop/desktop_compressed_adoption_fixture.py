"""Seed and observe the owned compressed-chat Desktop fixture."""

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs

PROFILE = "scout"
ROOT = "fixture-adopt-root"
TIP = "fixture-adopt-tip"
ROOT_MARKER = "fixture-compressed-root-only"
TIP_MARKER = "fixture-compressed-tip-only"
DECOY = "fixture-default-same-tip-id"
HISTORICAL_OWNER = "basic:fixture-historical"
TRANSCRIPT_PATHS = {
    f"/api/sessions/{session_id}/messages": session_id for session_id in (ROOT, TIP)
}


def seed():
    from hermes_constants import get_hermes_home
    from hermes_state import SessionDB

    home = get_hermes_home()
    with SessionDB(home / "state.db") as db:
        assert db.delete_session("fixture-adopt-default")
        db.create_session(
            TIP, source="desktop", model="mock-model", cwd=str(home), user_id=HISTORICAL_OWNER
        )
        assert db.set_session_title(TIP, "Bot Chat")
        assert db.set_session_hidden(TIP, True)
        db.append_message(TIP, "user", DECOY)

    named = home / "profiles" / PROFILE
    with SessionDB(named / "state.db") as db:
        assert db.delete_session("fixture-adopt-scout")
        db.create_session(
            ROOT, source="desktop", model="mock-model", cwd=str(named), user_id=HISTORICAL_OWNER
        )
        assert db.set_session_title(ROOT, "Bot Chat")
        assert db.set_session_hidden(ROOT, True)
        db.append_message(ROOT, "user", ROOT_MARKER)
        assert db.try_acquire_compression_lock(ROOT, "fixture-adoption")
        try:
            db.publish_compression_child(
                parent_session_id=ROOT,
                child_session_id=TIP,
                source="desktop",
                model="mock-model",
                messages=[{"role": "assistant", "content": TIP_MARKER}],
                compression_lock_holder="fixture-adoption",
            )
        finally:
            db.release_compression_lock(ROOT, "fixture-adoption")
        assert db.set_session_hidden(TIP, True)
        db.end_session(TIP, "session_switch")
        assert db.get_compression_tip(ROOT) == TIP


def seed_peer():
    from hermes_constants import get_hermes_home
    from hermes_state import SessionDB

    home = get_hermes_home()
    for directory, slug in ((home, "default"), (home / "profiles" / PROFILE, PROFILE)):
        with SessionDB(directory / "state.db") as db:
            assert db.delete_session(f"fixture-peer-{slug}")
            db.create_session(TIP, source="desktop", model="mock-model", cwd=str(directory))
            assert db.set_session_title(TIP, "Bot Chat")
            assert db.set_session_hidden(TIP, True)
            db.append_message(TIP, "user", f"fixture-peer-{slug}-same-tip-id")


async def assert_canonical_lineage():
    from hermes_cli.gateway_client import connect_gateway
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_constants import get_hermes_home

    endpoint = discover_gateway_endpoint(get_hermes_home() / "profiles" / PROFILE).endpoint
    assert endpoint is not None
    async with asyncio.timeout(8), connect_gateway(endpoint=endpoint) as client:
        result = await client.rpc("session.list", title="Bot Chat", include_hidden=True, limit=200)
    assert [(row["id"], row["resolved_id"]) for row in result["sessions"]] == [(ROOT, TIP)]


def inventory():
    from gateway.owner_identity import host_owner_subject
    from hermes_constants import get_hermes_home
    from hermes_state_local import POLICY_PREFIX
    from hermes_state_local_migration import LEGACY_PREFIX

    home = get_hermes_home()
    owner = host_owner_subject()
    owner_labels = {HISTORICAL_OWNER: "historical", owner: "host"}
    result = []
    for directory in (home, home / "profiles" / PROFILE):
        uri = (directory / "state.db").as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            saved = db.execute(
                "SELECT key,value FROM state_meta WHERE key LIKE ? OR key LIKE ? ORDER BY key",
                (POLICY_PREFIX + "%", LEGACY_PREFIX + "%"),
            ).fetchall()
            rows = db.execute(
                "SELECT id,title,hidden,parent_session_id,user_id,chat_id,end_reason,session_key "
                "FROM sessions ORDER BY id"
            ).fetchall()
            routes = {row["id"]: row["session_key"] for row in rows}
            bindings = []
            for key, raw in saved:
                receipt = json.loads(raw)
                legacy = key.startswith(LEGACY_PREFIX)
                session_id = receipt["session_id"]
                bindings.append(
                    {
                        "kind": "legacy" if legacy else "policy",
                        "id": session_id,
                        "keyMatches": key
                        == (LEGACY_PREFIX if legacy else POLICY_PREFIX) + session_id,
                        "owner": receipt["principal_id"] == owner,
                        "profile": receipt["profile_id"] == str(directory),
                        "targetMatches": receipt["legacy_session_id"] == session_id
                        and (legacy or receipt["entry"]["session_id"] == session_id),
                        "routeMatches": legacy
                        or bool(receipt["route"] and receipt["route"] == routes[session_id]),
                    }
                )
            result.append(
                {
                    "bindings": bindings,
                    "rows": [
                        {
                            "id": row["id"],
                            "title": row["title"],
                            "hidden": bool(row["hidden"]),
                            "parent": row["parent_session_id"],
                            "owner": owner_labels.get(row["user_id"], "other"),
                            "chatId": row["chat_id"],
                            "endReason": row["end_reason"],
                            "routed": bool(row["session_key"]),
                        }
                        for row in rows
                    ],
                }
            )
    print(json.dumps(result))


def run_gateway():
    from gateway.run import main
    from gateway.run_api import GatewayRuntimeAPI

    control = Path(os.environ["HERMES_ADOPTION_OBSERVER"])
    original = GatewayRuntimeAPI.__call__

    async def observe(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "GET"
            or not (control / "armed").exists()
            or (session_id := TRANSCRIPT_PATHS.get(scope.get("path"))) is None
        ):
            return await original(self, scope, receive, send)

        query = parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True)
        headers = dict(scope.get("headers", ()))
        observation = {
            "id": session_id,
            "tokenHeader": bool(headers.get(b"x-hermes-session-token")),
            "scoped": query.get("profile") == [PROFILE],
            "includesCompacted": query.get("include_compacted") == ["true"],
        }
        body = bytearray()
        oversized = False

        async def send_observed(message):
            nonlocal oversized
            if message["type"] == "http.response.start":
                observation["status"] = message["status"]
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                oversized = oversized or len(body) + len(chunk) > 64 * 1024
                if not oversized:
                    body.extend(chunk)
                if not message.get("more_body"):
                    observation.update(transcript_observation(body) if not oversized else {})
                    with (control / "rest.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(observation) + "\n")
            await send(message)

        return await original(self, scope, receive, send_observed)

    GatewayRuntimeAPI.__call__ = observe
    main()


def transcript_observation(body):
    # Record only expected marker counts and exact scope checks, without copying the response.
    try:
        payload = json.loads(body)
        contents = [row.get("content") for row in payload["messages"]]
    except KeyError, TypeError, AttributeError, ValueError:
        return {}
    return {
        "targetMatches": payload.get("session_id") == TIP and payload.get("profile") == PROFILE,
        "orderedMarkers": contents == [ROOT_MARKER, TIP_MARKER],
        "rootMarkers": contents.count(ROOT_MARKER),
        "tipMarkers": contents.count(TIP_MARKER),
        "decoyMarkers": contents.count(DECOY),
    }


if __name__ == "__main__":
    run_gateway()
