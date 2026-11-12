"""One-shot owner-side error for the synthetic Electron Bot Chat fixture."""

import asyncio
import json
import os
from contextvars import ContextVar
from pathlib import Path

PROFILE = "scout"
TITLE = "Bot Chat"
CANONICAL = "fixture-canonical-scout"
SIDE_THREAD = "fixture-canonical-side"
SELECTORS = {"title": TITLE, "include_hidden": True, "limit": 200}
AUDITED = {
    "session.list",
    "session.info",
    "session.create",
    "session.resume",
    "session.activate",
    "prompt.submit",
}


def seed_side():
    from hermes_constants import get_hermes_home
    from hermes_state import SessionDB

    home = get_hermes_home() / "profiles" / PROFILE
    with SessionDB(home / "state.db") as db:
        db.create_session(SIDE_THREAD, source="cli", model="mock-model", cwd=str(home))
        assert db.set_session_title(SIDE_THREAD, "Side Thread")
        db.append_message(SIDE_THREAD, "user", SIDE_THREAD)


def _session_ids(result):
    return [[row.get("id"), row.get("resolved_id")] for row in result.get("sessions", [])]


async def warm_canonical():
    from hermes_cli.gateway_client import connect_gateway
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_constants import get_hermes_home

    endpoint = discover_gateway_endpoint(get_hermes_home() / "profiles" / PROFILE).endpoint
    assert endpoint is not None, "owned named Gateway endpoint is ready"
    async with asyncio.timeout(8), connect_gateway(endpoint=endpoint) as client:
        assert _session_ids(await client.rpc("session.list", **SELECTORS)) == [
            [CANONICAL, CANONICAL]
        ]


def run_gateway():
    from gateway.run import main
    from gateway.session_controls import AuthorityConnection
    from hermes_constants import get_hermes_home
    from hermes_state_runtime import RuntimeStoreError

    target = str((get_hermes_home() / "profiles" / PROFILE).resolve())
    control = Path(os.environ["HERMES_BOT_CANONICAL_CONTROL"])
    phase_file = control / "phase"
    nested = ContextVar("fixture_dispatch", default=False)
    native_list = AuthorityConnection.list_sessions
    native_dispatch = AuthorityConnection.dispatch

    def append_audit(record):
        with (control / "wire.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")

    async def list_sessions(self, ref, params):
        result = await native_list(self, ref, params)
        if self.authority.profile_id != target or params != SELECTORS:
            return result
        for phase in ("refusal", "empty"):
            fired = control / f"fired-{phase}.json"
            try:
                # Claim once after the native read. Later calls proceed normally.
                (control / f"arm-{phase}").rename(fired)
            except FileNotFoundError:
                continue
            ids = _session_ids(result)
            assert ids == [[CANONICAL, CANONICAL]], "the original lookup found the expected chat"
            fired.write_text(json.dumps(ids), encoding="utf-8")
            if phase == "refusal":
                raise RuntimeStoreError("permission_denied")
            return {**result, "sessions": []}
        return result

    async def dispatch(self, request):
        if not isinstance(request, dict):
            return await native_dispatch(self, request)
        method = request.get("method")
        if nested.get() or not isinstance(method, str) or method not in AUDITED:
            return await native_dispatch(self, request)
        try:
            phase = phase_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return await native_dispatch(self, request)
        assert phase in {"refusal", "empty", "retry"}, "the phase is fixture-owned"
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return await native_dispatch(self, request)
        record = {
            "phase": phase,
            "method": method,
            "profile": params.get("profile"),
            "sessionId": params.get("session_id"),
            "title": params.get("title"),
            "includeHidden": params.get("include_hidden"),
            "limit": params.get("limit"),
        }
        if method == "session.info":
            record["targetAuthority"] = self.authority.profile_id == target
        # Record the attempted dispatch even when its response later fails or is delayed.
        append_audit({"direction": "request", **record})
        token = nested.set(True)
        try:
            reply = await native_dispatch(self, request)
        finally:
            nested.reset(token)
        canonical_list = method == "session.list" and params.get("title") == TITLE
        canonical_info = method == "session.info" and params.get("session_id") == CANONICAL
        if canonical_list or canonical_info:
            error = (reply or {}).get("error") or {}
            result = (reply or {}).get("result") or {}
            append_audit(
                {
                    "direction": "reply",
                    **record,
                    "code": error.get("code"),
                    "reason": (error.get("data") or {}).get("reason"),
                    "ids": _session_ids(result),
                    "storedTitle": result.get("title"),
                    "archived": result.get("archived"),
                    "profileName": result.get("profile_name"),
                }
            )
        return reply

    AuthorityConnection.list_sessions = list_sessions
    AuthorityConnection.dispatch = dispatch
    main()


if __name__ == "__main__":
    run_gateway()
