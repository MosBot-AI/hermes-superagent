"""Native audio HTTP routes exercised with temporary profiles and synthetic credentials."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_native_voice_audio_asgi import native_audio_gateway as native_audio_gateway
from test_native_voice_audio_asgi import run_audio_app

VOICE_CONFIG = "/api/audio/voice-config"
PROFILE_STT_KEY = "synthetic-target-stt"
PROFILE_TTS_KEY = "synthetic-target-tts"


def request_voice(app, *, path=VOICE_CONFIG, ticket=None, query=b"", payload=None):
    headers = [(b"host", b"127.0.0.1:8765")]
    if ticket is not None:
        headers.append((b"x-hermes-gateway-ticket", ticket.encode()))
    request_body = b"" if payload is None else json.dumps(payload).encode()
    if payload is not None:
        headers += [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(request_body)).encode()),
        ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "http",
        "method": "GET" if payload is None else "POST",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query,
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
        "state": {},
    }
    received = False
    complete = asyncio.Event()
    sent = []

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": request_body, "more_body": False}
        await complete.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body"):
            complete.set()

    run_audio_app(app, scope, receive, send)
    (status,) = (frame["status"] for frame in sent if frame["type"] == "http.response.start")
    response = b"".join(
        frame.get("body", b"") for frame in sent if frame["type"] == "http.response.body"
    )
    return status, json.loads(response)


@pytest.fixture
def native_voice_http(native_audio_gateway, monkeypatch):
    from hermes_constants import get_hermes_home
    from tools import transcription_streaming, transcription_tools, tts_tool, voice_client_config

    launch, home = native_audio_gateway.launch, native_audio_gateway.profile
    config = {
        "voice": {"client_direct": True},
        "stt": {"provider": "groq", "streaming": False, "groq": {"model": "fixture-stt"}},
        "tts": {"provider": "elevenlabs", "elevenlabs": {"model_id": "fixture-tts"}},
    }
    for directory, stt_key, tts_key in (
        (launch, "synthetic-launch-stt", "synthetic-launch-tts"),
        (home, PROFILE_STT_KEY, PROFILE_TTS_KEY),
    ):
        (directory / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
        (directory / ".env").write_text(
            f"GROQ_API_KEY={stt_key}\nELEVENLABS_API_KEY={tts_key}\n",
            encoding="utf-8",
        )

    refuse = native_audio_gateway.refuse
    monkeypatch.setattr(transcription_tools, "_detect_local_backend", refuse)
    monkeypatch.setattr(transcription_tools, "transcribe_audio", refuse)
    monkeypatch.setattr(transcription_streaming, "open_streaming_session", refuse)
    monkeypatch.setattr(tts_tool, "text_to_speech_tool", refuse)
    resolver_calls = []
    original_resolver = voice_client_config.resolve_client_voice_config

    def resolve(client_direct):
        resolver_calls.append((get_hermes_home(), client_direct))
        return original_resolver(client_direct)

    monkeypatch.setattr(voice_client_config, "resolve_client_voice_config", resolve)

    def mint(purpose="native-http"):
        return native_audio_gateway.store.mint(
            profile_id=str(home), subject="fixture-client", purpose=purpose
        )

    return SimpleNamespace(
        app=native_audio_gateway.app,
        state=native_audio_gateway.state,
        home=home,
        launch=launch,
        config=config,
        calls=resolver_calls,
        mint=mint,
    )


def assert_relay_without_keys(body):
    for direction in ("stt", "tts"):
        assert body[direction]["mode"] == "relay"
        assert "api_key" not in body[direction]
    assert PROFILE_STT_KEY not in repr(body)
    assert PROFILE_TTS_KEY not in repr(body)


@pytest.mark.parametrize("surface", ["gateway", "dashboard", "serve", "webapp"])
def test_voice_config_applies_surface_policy_and_ticket_profile(native_voice_http, surface):
    host = native_voice_http
    host.state.ui_surface = surface
    status, body = request_voice(host.app, ticket=host.mint())
    assert status == 200 and body["ok"] is True
    assert host.calls == [(host.home, surface != "webapp")]
    assert body["stt"]["streaming"] is False
    if surface == "webapp":
        assert_relay_without_keys(body)
        assert body["stt"]["reason"] == body["tts"]["reason"] == "browser surface"
    else:
        assert body["stt"]["mode"] == body["tts"]["mode"] == "direct"
        assert body["stt"]["wire"] == "openai-multipart"
        assert body["tts"]["wire"] == "elevenlabs-tts"
        assert body["stt"]["model"] == "fixture-stt"
        assert body["tts"]["model"] == "fixture-tts"
        assert body["stt"]["api_key"] == PROFILE_STT_KEY
        assert body["tts"]["api_key"] == PROFILE_TTS_KEY


def test_voice_config_honors_profile_direct_opt_out(native_voice_http):
    host = native_voice_http
    host.config["voice"]["client_direct"] = False
    (host.home / "config.yaml").write_text(json.dumps(host.config), encoding="utf-8")
    status, body = request_voice(host.app, ticket=host.mint())
    assert status == 200 and body["ok"] is True
    assert host.calls == [(host.home, True)]
    assert_relay_without_keys(body)
    assert body["stt"]["reason"] == body["tts"]["reason"] == "voice.client_direct disabled"


def test_voice_config_refuses_inapplicable_native_http_tickets_before_resolution(native_voice_http):
    from hermes_cli.web_server_profiles import _resolve_profile_dir

    host = native_voice_http
    ticket = host.mint()
    assert request_voice(host.app, ticket=ticket)[0] == 200
    assert host.calls == [(host.home, True)]
    host.calls.clear()
    for unusable_ticket in (None, ticket, host.mint("interactive")):
        assert request_voice(host.app, ticket=unusable_ticket)[0] == 401
    assert _resolve_profile_dir("default") == host.launch
    assert request_voice(host.app, ticket=host.mint(), query=b"profile=default") == (
        403,
        {"detail": "profile_scope_mismatch"},
    )
    assert host.calls == []
