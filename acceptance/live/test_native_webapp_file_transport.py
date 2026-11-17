"""Manual acceptance of native browser staging, attachment and download tickets."""

import asyncio
import hmac
import stat
from contextlib import AsyncExitStack
from pathlib import Path

from native_bot_socket_guard import activate
from test_native_webapp_signout import (
    PROFILE,
    TOKEN_PATH,
    browser_connection,
    distinct_ports,
    history_snapshot,
    isolated_webapp_host,
    prepare_install,
    read_private_credential,
    serving_install,
    webapp_cli,
)

UPLOAD = "/api/chat/file-upload"
ISSUE_TICKET = "/api/files/ticket"
DOWNLOAD = "/api/fs/download"
FILE_NAME = "synthetic-notes.txt"
FILE_BODY = "Synthetic native attachment\n合成附件\n".encode()


def verify_private_file(path, directory):
    assert path.parent == directory
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert path.read_bytes() == FILE_BODY


async def issue_download(http, headers, resource):
    result = await http.post(ISSUE_TICKET, json={"route": "download", **resource}, headers=headers)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    ticket = result.json().get("ticket")
    assert type(ticket) is str and len(ticket) > 0
    return {**resource, "ticket": ticket}


async def verify_file_transport(host, home, env, endpoint, identity):
    import httpx
    from hermes_cli.gateway_client import GatewayClient
    from hermes_cli.gateway_runtime_discovery import query_identify

    origin = endpoint.api_origin
    named = home / "profiles" / PROFILE
    session_id = f"fixture-{home.parent.name}-{PROFILE}"
    credential_path = home / TOKEN_PATH
    credential = read_private_credential(credential_path)
    origin_header = {"Origin": origin}
    headers = origin_header | {"X-Hermes-Session-Token": credential.decode().strip()}
    uploads = {"file": (FILE_NAME, FILE_BODY, "text/plain")}
    before = history_snapshot({"a": (home, env, endpoint, identity)})
    assert len(before) == 2
    assert all(
        len(sessions) == len(messages) == 1 and not admissions
        for sessions, messages, admissions in before.values()
    )

    async with asyncio.timeout(50), AsyncExitStack() as stack:
        http = await stack.enter_async_context(
            httpx.AsyncClient(base_url=origin, trust_env=False, timeout=5)
        )
        anonymous = await http.post(
            UPLOAD, params={"profile": PROFILE}, files=uploads, headers=origin_header
        )
        assert anonymous.status_code == 401
        assert not list((named / "uploads").glob("*"))

        staged_response = await http.post(
            UPLOAD, params={"profile": PROFILE}, files=uploads, headers=headers
        )
        assert staged_response.status_code == 200
        staged = staged_response.json()
        assert staged["ok"] is True and staged["size"] == len(FILE_BODY)
        staged_path = Path(staged["path"])
        verify_private_file(staged_path, named / "uploads")
        assert not list((home / "uploads").glob("*"))

        ws = await browser_connection(stack, endpoint, credential)
        browser = await stack.enter_async_context(GatewayClient(ws))
        await browser.rpc("session.resume", session_id=session_id, _timeout=5)
        attachment = await browser.rpc(
            "file.attach",
            session_id=session_id,
            name=FILE_NAME,
            staged_upload=staged["staged_upload"],
            _timeout=5,
        )
        assert attachment["attached"] is True and attachment["uploaded"] is True
        assert attachment["ref_text"].startswith("@file:")
        attached_path = Path(attachment["path"])
        verify_private_file(attached_path, named / "attachments")
        assert not list((home / "attachments").glob("*"))

        resource = {"path": str(attached_path), "profile": PROFILE, "session_id": session_id}
        download = await issue_download(http, headers, resource)
        for route, params in (
            (DOWNLOAD, download | {"path": str(staged_path)}),
            (DOWNLOAD, download | {"profile": "default"}),
            (DOWNLOAD, download | {"session_id": f"fixture-{home.parent.name}-default"}),
            ("/api/files/stream", download),
        ):
            refused = await http.get(route, params=params, headers=origin_header)
            assert refused.status_code == 401

        head = await http.head(DOWNLOAD, params=download, headers=origin_header)
        assert head.status_code == 200 and not head.content
        assert int(head.headers["content-length"]) == len(FILE_BODY)
        for _ in range(2):
            reply = await http.get(DOWNLOAD, params=download, headers=origin_header)
            assert reply.status_code == 200 and reply.content == FILE_BODY
        exhausted = await http.get(DOWNLOAD, params=download, headers=origin_header)
        assert exhausted.status_code == 401

        retained = await issue_download(http, headers, resource)
        valid = await http.get(DOWNLOAD, params=retained, headers=origin_header)
        assert valid.status_code == 200 and valid.content == FILE_BODY
        await asyncio.to_thread(
            webapp_cli,
            host,
            env,
            "--sign-out",
            expected="Signed out of every Webapp tab: closed 1 browser connection.",
        )
        async with asyncio.timeout(10):
            await ws.wait_closed()
        assert ws.close_code == 4401
        revoked = await http.get(DOWNLOAD, params=retained, headers=origin_header)
        assert revoked.status_code == 401
        old_mint = await http.post(
            ISSUE_TICKET, json={"route": "download", **resource}, headers=headers
        )
        assert old_mint.status_code == 401
        replacement = read_private_credential(credential_path)
        assert not hmac.compare_digest(credential, replacement)
        fresh = await issue_download(
            http, origin_header | {"X-Hermes-Session-Token": replacement.decode().strip()}, resource
        )
        recovered = await http.get(DOWNLOAD, params=fresh, headers=origin_header)
        assert recovered.status_code == 200 and recovered.content == FILE_BODY

    verify_private_file(attached_path, named / "attachments")
    assert history_snapshot({"a": (home, env, endpoint, identity)}) == before
    current = query_identify(home, timeout=2)
    assert (current["pid"], current["instance_id"]) == (identity["pid"], identity["instance_id"])


def test_native_webapp_files_attach_and_revoke_browser_ticket(tmp_path_factory, monkeypatch):
    with isolated_webapp_host(tmp_path_factory, monkeypatch) as (host, root, env, isolated):
        port, _ = distinct_ports()
        restrict = activate(root, dial_ports=(port,), dial_host="127.0.0.1")
        try:
            home, install_env = prepare_install(root / "a", env, port)
            with serving_install(host, home, install_env, port, isolated) as (endpoint, identity):
                asyncio.run(verify_file_transport(host, home, install_env, endpoint, identity))
        finally:
            restrict()
