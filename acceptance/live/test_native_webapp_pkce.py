"""Verify the pinned Webapp's native password PKCE flow over real loopback sockets."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Queue
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from native_gateway_fixture import gateway_daemon
from test_native_webapp_signout import (
    TOKEN_PATH,
    distinct_ports,
    isolated_webapp_host,
    prepare_install,
    read_private_credential,
    webapp_cli,
)

PUBLIC_NAME = "webapp-pkce.example.test"
USER = "fixture-owner"
ME = "/api/auth/me"
AUTHORIZE = "/auth/native/authorize"
EXCHANGE = "/auth/native/token"
REFRESH = "/auth/native/refresh"
LOGIN = "/auth/password-login"
CALLBACK = "/native-callback"


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        target = urlsplit(self.path)
        if target.path != CALLBACK:
            self.send_error(404)
            return
        self.server.callbacks.put(parse_qs(target.query))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_):
        # The discarded request line contains the one-use synthetic code.
        return


@contextmanager
def callback_listener():
    with HTTPServer(("127.0.0.1", 0), CallbackHandler) as server:
        server.callbacks = Queue()
        service = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        service.start()
        try:
            port = server.server_port
            yield f"http://127.0.0.1:{port}{CALLBACK}?fixture=1", server.callbacks
        finally:
            server.shutdown()
            service.join(timeout=5)
            assert not service.is_alive()


def configure_gated_webapp(host, home, env, port, password):
    from plugins.dashboard_auth.basic import hash_password

    config = home / "config.yaml"
    document = json.loads(config.read_bytes())
    document["webapp"]["public_url"] = f"http://{PUBLIC_NAME}:{port}"
    config.write_text(json.dumps(document), encoding="utf-8")
    return env | {
        "HERMES_BUNDLED_PLUGINS": str(host / "plugins"),
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": USER,
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH": hash_password(password),
        "HERMES_DASHBOARD_BASIC_AUTH_SECRET": secrets.token_hex(32),
    }


def gateway_http(endpoint):
    import httpx

    port = urlsplit(endpoint.api_origin).port
    authority = f"{PUBLIC_NAME}:{port}"
    # Address only the test Gateway's loopback socket while selecting its declared HTTP host.
    return httpx.Client(
        base_url=endpoint.api_origin,
        headers={"Host": authority, "Origin": f"http://{authority}"},
        follow_redirects=False,
        trust_env=False,
        timeout=6,
    )


def expected_status(reply, status):
    assert reply.status_code == status


def authorization(redirect_uri):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, {
        "provider": "basic",
        "code_challenge": challenge.decode("ascii").rstrip("="),
        "code_challenge_method": "S256",
        "redirect_uri": redirect_uri,
        "state": secrets.token_urlsafe(24),
    }


def check_unsupported_callbacks(browser, redirect_uri, callbacks):
    port = urlsplit(redirect_uri).port
    _, params = authorization(redirect_uri)
    for unsupported in (
        {"redirect_uri": f"http://localhost:{port}{CALLBACK}"},
        {"redirect_uri": "https://mobile.example.test/return"},
        {"redirect_uri": "fixture-app:/return"},
        {"code_challenge_method": "plain"},
    ):
        refused = browser.get(AUTHORIZE, params=params | unsupported)
        expected_status(refused, 400)
        assert "location" not in refused.headers and "set-cookie" not in refused.headers
    assert not browser.cookies and callbacks.empty()


def login(browser, password):
    reply = browser.post(LOGIN, json={"provider": "basic", "username": USER, "password": password})
    expected_status(reply, 200)
    accepted = reply.json()
    assert accepted.get("ok") is True
    return accepted["next"]


def collect_code(browser, password, redirect_uri, callbacks):
    import httpx

    verifier, params = authorization(redirect_uri)
    started = browser.get(AUTHORIZE, params=params)
    expected_status(started, 302)
    assert started.headers.get("location") == "/login"
    assert any("hermes_session_pkce" in name for name in browser.cookies)

    target = login(browser, password)
    candidate, registered = urlsplit(target), urlsplit(redirect_uri)
    assert candidate._replace(query="") == registered._replace(query="")
    expected_status(httpx.get(target, trust_env=False, follow_redirects=False, timeout=5), 204)
    callback = callbacks.get(timeout=3)
    assert set(callback) == {"code", "state", "fixture"}
    assert callback["fixture"] == ["1"]
    assert callback["state"] == [params["state"]]
    (code,) = callback["code"]
    assert code
    assert not any(
        "hermes_session_at" in name or "hermes_session_rt" in name for name in browser.cookies
    )
    expected_status(browser.get(ME), 401)
    return code, verifier


def token_pair(response):
    expected_status(response, 200)
    body = response.json()
    assert (body.get("provider"), body.get("user_id"), body.get("token_type")) == (
        "basic",
        USER,
        "Bearer",
    )
    assert body["expires_at"] > time.time()
    assert "set-cookie" not in response.headers
    pair = (body["access_token"], body["refresh_token"])
    if any(type(value) is not str or not value for value in pair):
        raise AssertionError("Expected both native credentials")
    return pair


def check_identity(response):
    expected_status(response, 200)
    identity = response.json()
    assert (identity.get("provider"), identity.get("user_id")) == ("basic", USER)


def verify_sign_in(host, home, env, endpoint, password, redirect_uri, callbacks):
    from hermes_cli.gateway_runtime_discovery import query_identify

    owner = query_identify(home, timeout=2)
    with gateway_http(endpoint) as native, gateway_http(endpoint) as browser:
        status = native.get("/api/status")
        expected_status(status, 200)
        assert status.json()["auth_required"] is True
        assert {"cookie", "native_pkce"}.issubset(status.json()["auth_flows"])
        expected_status(native.get(ME), 401)
        check_unsupported_callbacks(browser, redirect_uri, callbacks)

        invalid_code, verifier = collect_code(browser, password, redirect_uri, callbacks)
        wrong = native.post(
            EXCHANGE, json={"code": invalid_code, "code_verifier": secrets.token_urlsafe(48)}
        )
        expected_status(wrong, 400)
        reused = native.post(EXCHANGE, json={"code": invalid_code, "code_verifier": verifier})
        expected_status(reused, 400)
        assert reused.json() == wrong.json()

        code, verifier = collect_code(browser, password, redirect_uri, callbacks)
        exchange = {"code": code, "code_verifier": verifier}
        access, refresh = token_pair(native.post(EXCHANGE, json=exchange))
        expected_status(native.post(EXCHANGE, json=exchange), 400)
        assert not native.cookies
        check_identity(native.get(ME, headers={"Authorization": f"Bearer {access}"}))

        assert login(browser, password) == "/"
        check_identity(browser.get(ME))
        before = read_private_credential(home / TOKEN_PATH)
        webapp_cli(host, env, "--sign-out", expected="Signed out every browser:")
        assert not hmac.compare_digest(before, read_private_credential(home / TOKEN_PATH))
        expected_status(browser.get(ME), 401)
        check_identity(native.get(ME, headers={"Authorization": f"Bearer {access}"}))
        new_access, new_refresh = token_pair(
            native.post(REFRESH, json={"refresh_token": refresh, "provider": "basic"})
        )
        assert not hmac.compare_digest(access, new_access)
        assert not hmac.compare_digest(refresh, new_refresh)
        check_identity(native.get(ME, headers={"Authorization": f"Bearer {new_access}"}))
        assert not native.cookies and callbacks.empty()
        current = query_identify(home, timeout=2)
        assert (current["pid"], current["instance_id"]) == (owner["pid"], endpoint.instance_id)
        return new_access


def test_native_webapp_pkce_loopback_and_browser_signout_boundary(tmp_path_factory, monkeypatch):
    with isolated_webapp_host(tmp_path_factory, monkeypatch) as (host, root, common, scope):
        port, _ = distinct_ports()
        home, env = prepare_install(root / "pkce", common, port)
        password = secrets.token_urlsafe(32)
        env = configure_gated_webapp(host, home, env, port, password)
        for name in ("HERMES_HOME", "HERMES_RUNTIME_DIR"):
            scope.setenv(name, env[name])
        with (
            gateway_daemon(host, home, env, "pkce") as first,
            callback_listener() as (redirect_uri, callbacks),
        ):
            assert first.api_origin == f"http://127.0.0.1:{port}"
            access = verify_sign_in(host, home, env, first, password, redirect_uri, callbacks)
        with (
            gateway_daemon(host, home, env, "pkce-restart") as second,
            gateway_http(second) as native,
        ):
            assert second.instance_id != first.instance_id and second.api_origin == first.api_origin
            check_identity(native.get(ME, headers={"Authorization": f"Bearer {access}"}))
