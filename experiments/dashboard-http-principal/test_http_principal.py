"""Compare the same metadata-only dashboard plugin on the clean and proposed hosts."""

import importlib.util
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from hermes_cli import web_server
from hermes_cli.dashboard_auth.cookies import (
    SESSION_AT_COOKIE,
    SESSION_PROVIDER_COOKIE,
    SESSION_RT_COOKIE,
)
from hermes_cli.dashboard_auth.registry import clear_providers, register_provider
from hermes_cli.plugin_host import PluginHost
from plugins.dashboard_auth.session_token import SessionTokenProvider
from tests.hermes_cli import test_plugin_secondary_profile_host as secondary
from tests.hermes_cli.conftest_dashboard_auth import StubAuthProvider, _sign

NAME = "identity-probe"
URL = f"/api/plugins/{NAME}/identity"
ISSUER = "https://issuer.example.test"
GROUP = "stub-org-1"
SHARED_TOKEN = "synthetic-shared-dashboard-admission"
CANDIDATE = importlib.util.find_spec("hermes_cli.plugin_http_principal") is not None

if (expected_target := os.environ.get("HERMES_TEST_EXPECT_PLUGIN_PRINCIPAL")) is not None:
    assert expected_target == ("yes" if CANDIDATE else "no"), "Wrong probe namespace"

API = """
import os
from dataclasses import asdict
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from hermes_cli.web_deps import late

try:
    from hermes_cli.plugin_http_principal import get_plugin_http_principal
except ModuleNotFoundError:
    get_plugin_http_principal = None

router = APIRouter()

@router.api_route("/identity", methods=["GET", "POST"])
async def identity(request: Request):
    late("_require_token")(request)
    principal = get_plugin_http_principal(request) if get_plugin_http_principal else None
    body = {"pid": os.getpid()}
    if principal is None:
        return JSONResponse({
            **body,
            "error": "host_identity_unavailable",
            "provider_session": getattr(request.state, "session", None) is not None,
            "hosted_admission": getattr(request.state, "hosted_http_authenticated", None) is True,
        }, status_code=503)
    return {**body, "principal": asdict(principal)}
"""


class IssuerStub(StubAuthProvider):
    """Add a verified fixture issuer to the upstream synthetic provider."""

    def verify_session(self, *, access_token):
        session = super().verify_session(access_token=access_token)
        return replace(session, issuer=ISSUER) if session is not None else None

    def refresh_session(self, *, refresh_token):
        return replace(super().refresh_session(refresh_token=refresh_token), issuer=ISSUER)


def access_token(subject):
    return _sign(
        {
            "sub": subject,
            "email": "synthetic-private@example.test",
            "name": "Synthetic Private Name",
            "org_id": GROUP,
            "exp": int(time.time()) + 600,
        }
    )


def cookie(subject):
    return {
        "Cookie": f"{SESSION_AT_COOKIE}={access_token(subject)}; {SESSION_PROVIDER_COOKIE}=stub",
    }


def bearer(subject):
    return {"Authorization": f"Bearer {access_token(subject)}"}


daemon = secondary.daemon


@pytest.fixture
def dashboard(daemon, monkeypatch):
    monkeypatch.setattr(PluginHost, "asgi_request", secondary._REAL_ASGI_REQUEST)
    monkeypatch.setattr(web_server.app.state, "auth_required", True, raising=False)
    monkeypatch.setattr(web_server.app.state, "ui_surface", "dashboard", raising=False)
    clear_providers()
    register_provider(IssuerStub())
    register_provider(SessionTokenProvider(token=SHARED_TOKEN))
    try:
        yield daemon
    finally:
        secondary._shutdown_hosts()
        clear_providers()


def install(home, *, isolation="in_process"):
    secondary._install(home, NAME)
    api = home / "plugins" / NAME / "dashboard" / "plugin_api.py"
    api.write_text(API, encoding="utf-8")
    secondary._plugins(home, enabled=[NAME], isolation=isolation)


def expect_principal(response, *, hosted, subject, kind, profile):
    body = response.json()
    assert (body["pid"] != os.getpid()) is hosted
    if CANDIDATE:
        assert response.status_code == 200
        assert body == {
            "pid": body["pid"],
            "principal": {
                "provider": "stub",
                "issuer": ISSUER,
                "subject": subject,
                "organization": GROUP,
                "credential_kind": kind,
                "profile_name": profile,
            },
        }
    else:
        assert response.status_code == 503
        assert body == {
            "pid": body["pid"],
            "error": "host_identity_unavailable",
            "provider_session": not hosted,
            "hosted_admission": hosted,
        }


@pytest.mark.parametrize("isolation", ["in_process", "host"])
def test_verified_cookie_bearer_and_refresh_keep_request_identity(dashboard, isolation):
    install(dashboard.launch, isolation=isolation)
    get = dashboard.client.get
    hosted = isolation == "host"
    first = get(URL, headers=cookie("fixture-alice"))
    second = get(URL, headers=bearer("fixture-bob"))
    third = get(URL, headers=cookie("fixture-alice"))
    assert first.json()["pid"] == second.json()["pid"] == third.json()["pid"]
    for response, subject, kind in (
        (first, "fixture-alice", "cookie_session"),
        (second, "fixture-bob", "provider_bearer"),
        (third, "fixture-alice", "cookie_session"),
    ):
        expect_principal(response, hosted=hosted, subject=subject, kind=kind, profile="default")

    refresh_token = _sign({"sub": "fixture-refresh", "exp": int(time.time()) + 600})
    refreshed = get(
        URL,
        headers={
            "Cookie": f"{SESSION_RT_COOKIE}={refresh_token}; {SESSION_PROVIDER_COOKIE}=stub",
        },
    )
    expect_principal(
        refreshed,
        hosted=hosted,
        subject="fixture-refresh",
        kind="cookie_session",
        profile="default",
    )
    assert SESSION_AT_COOKIE in refreshed.cookies and SESSION_RT_COOKIE in refreshed.cookies

    refreshed_at = refreshed.cookies[SESSION_AT_COOKIE]
    continued = get(
        URL,
        headers={
            "Cookie": f"{SESSION_AT_COOKIE}={refreshed_at}; {SESSION_PROVIDER_COOKIE}=stub",
        },
    )
    expect_principal(
        continued,
        hosted=hosted,
        subject="fixture-refresh",
        kind="cookie_session",
        profile="default",
    )


def test_overlapping_requests_reuse_host_without_sharing_identity(dashboard):
    install(dashboard.launch, isolation="host")
    get = dashboard.client.get
    first = get(URL, headers=cookie("fixture-warmup"))
    expect_principal(
        first, hosted=True, subject="fixture-warmup", kind="cookie_session", profile="default"
    )
    with ThreadPoolExecutor(max_workers=2) as workers:
        left = workers.submit(get, URL, headers=cookie("fixture-left"))
        right = workers.submit(get, URL, headers=bearer("fixture-right"))
        results = (left.result(timeout=15), right.result(timeout=15))
    for response, subject, kind in zip(
        results,
        ("fixture-left", "fixture-right"),
        ("cookie_session", "provider_bearer"),
        strict=True,
    ):
        assert response.json()["pid"] == first.json()["pid"]
        expect_principal(response, hosted=True, subject=subject, kind=kind, profile="default")


def test_secondary_profile_uses_its_own_host_and_scope(dashboard):
    install(dashboard.launch, isolation="host")
    install(dashboard.beta)
    launch = dashboard.client.get(URL, headers=bearer("fixture-one"))
    beta = dashboard.client.get(URL, params={"profile": "beta"}, headers=bearer("fixture-two"))
    assert launch.json()["pid"] != beta.json()["pid"]
    expect_principal(
        launch, hosted=True, subject="fixture-one", kind="provider_bearer", profile="default"
    )
    expect_principal(
        beta, hosted=True, subject="fixture-two", kind="provider_bearer", profile="beta"
    )


@pytest.mark.parametrize("isolation", ["in_process", "host"])
def test_host_denials_and_consent_precede_the_plugin(dashboard, isolation):
    install(dashboard.launch, isolation=isolation)
    get = dashboard.client.get
    assert get(URL).status_code == 401
    good = cookie("fixture-alice")
    assert get(URL, headers=good | {"Authorization": "Bearer invalid-fixture"}).status_code == 401
    wrong_page = good | {"Origin": "https://other.example.test", "Sec-Fetch-Site": "cross-site"}
    assert dashboard.client.post(URL, headers=wrong_page).status_code == 403
    assert get(URL, params={"profile": "unknown"}, headers=good).status_code == 404
    allowed = get(URL, headers=good)
    expect_principal(
        allowed,
        hosted=isolation == "host",
        subject="fixture-alice",
        kind="cookie_session",
        profile="default",
    )
    secondary._plugins(dashboard.launch, enabled=[NAME], disabled=[NAME], isolation=isolation)
    assert get(URL, headers=good).status_code == 404


def test_admission_only_modes_do_not_yield_provider_identity(dashboard, monkeypatch):
    install(dashboard.launch, isolation="host")
    install(dashboard.beta)
    get = dashboard.client.get
    for headers in (
        {"X-Hermes-Session-Token": SHARED_TOKEN},
        {"Authorization": f"Bearer {SHARED_TOKEN}"},
        dashboard.beta_ticket(),
    ):
        refused = get(URL, headers=headers)
        assert refused.status_code == 503
        assert refused.json()["error"] == "host_identity_unavailable"
        assert refused.json()["hosted_admission"] is True
    assert (
        get(URL, params={"profile": "default"}, headers=dashboard.beta_ticket()).status_code == 403
    )

    monkeypatch.setattr(web_server.app.state, "auth_required", False)
    loopback = get(URL, headers=dashboard.owner)
    assert loopback.status_code == 503
    assert loopback.json()["error"] == "host_identity_unavailable"
    assert loopback.json()["hosted_admission"] is True
