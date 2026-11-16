"""Pinned GPT-Live HTTP routes with a local fixture ticket and synthetic vendor transport."""

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest
from test_native_voice_audio_asgi import native_audio_gateway as native_audio_gateway
from test_native_voice_http_asgi import native_voice_http as native_voice_http
from test_native_voice_http_asgi import request_voice

STATUS = "/api/audio/voice-live/status"
SESSION = "/api/audio/voice-live/session"
TARGET_KEY = "synthetic-target-voice-key"
LAUNCH_KEY = "synthetic-launch-voice-key"
BASE_URL = "https://voice-fixture.invalid/v1"
MODEL = "fixture-live-model"
VOICE = "fixture-live-voice"
SDP = "v=0\r\ns=synthetic offer\r\n"


def configure_live(native_voice_http, *, mode, target_key):
    native_voice_http.config["voice"] = {
        "voice_chat_mode": mode,
        "gpt_live": {
            "base_url": f"{BASE_URL}/",
            "model": MODEL,
            "voice": VOICE,
            "instructions": "Use the synthetic voice.",
        },
    }
    (native_voice_http.home / "config.yaml").write_text(
        json.dumps(native_voice_http.config), encoding="utf-8"
    )
    with (native_voice_http.launch / ".env").open("a", encoding="utf-8") as launch_env:
        launch_env.write(f"\nVOICE_TOOLS_OPENAI_KEY={LAUNCH_KEY}\n")
    if target_key:
        with (native_voice_http.home / ".env").open("a", encoding="utf-8") as target_env:
            target_env.write(f"\nVOICE_TOOLS_OPENAI_KEY={TARGET_KEY}\n")


@pytest.mark.parametrize(
    ("mode", "vendor_failure"),
    [("gpt-live", False), ("chained", False), ("gpt-live", True)],
    ids=["gpt-live-answer", "chained-answer", "vendor-error"],
)
def test_native_live_status_and_sdp_exchange_use_ticket_profile(
    native_voice_http,
    monkeypatch,
    mode,
    vendor_failure,
):
    from tools import voice_live

    # The UI selection and the native session endpoint are independent at this pin.
    configure_live(native_voice_http, mode=mode, target_key=True)
    calls = []
    answer = {
        "session": {"id": "synthetic-live-session"},
        "transport": {"type": "webrtc", "sdp": "v=0\r\ns=synthetic answer\r\n"},
    }

    def exchange(request, timeout):
        calls.append((request, timeout))
        if vendor_failure:
            raise HTTPError(
                request.full_url, 429, "Synthetic quota failure", None, BytesIO(b"fixture refusal")
            )
        return BytesIO(json.dumps(answer).encode())

    monkeypatch.setattr(voice_live.urllib.request, "urlopen", exchange)
    code, status = request_voice(
        native_voice_http.app, path=STATUS, ticket=native_voice_http.mint()
    )
    assert code == 200
    assert status == {
        "ok": True,
        "mode": mode,
        "available": True,
        "reason": None,
        "model": MODEL,
        "voice": VOICE,
    }
    assert calls == []

    history = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Synthetic prior turn"}],
        },
    ]
    code, result = request_voice(
        native_voice_http.app,
        path=SESSION,
        ticket=native_voice_http.mint(),
        payload={"sdp": SDP, "history": history},
    )
    if vendor_failure:
        assert code == 502
        assert result == {"detail": "GPT-Live session creation failed (429): fixture refusal"}
    else:
        assert code == 200
        assert result == {"ok": True, **answer}

    ((request, timeout),) = calls
    assert request.full_url == f"{BASE_URL}/live/sessions"
    assert request.get_method() == "POST" and timeout == 30
    assert request.get_header("Authorization") == f"Bearer {TARGET_KEY}"
    assert request.get_header("Content-type") == "application/json"
    assert request.data is not None
    outbound = json.loads(request.data)
    assert outbound.pop("transport") == {"type": "webrtc", "sdp": SDP}
    session = outbound["session"]
    assert session.pop("instructions").endswith("\n\nUse the synthetic voice.")
    assert outbound == {
        "session": {
            "model": MODEL,
            "audio": {"output": {"voice": VOICE}},
            "delegation": {"type": "client"},
            "input": history,
        },
    }
    assert TARGET_KEY not in json.dumps(result)
    assert LAUNCH_KEY not in json.dumps(result)


@pytest.mark.parametrize(
    ("sdp", "target_key", "expected_code", "error"),
    [
        (" \r\n", True, 400, "An SDP offer is required"),
        (SDP, False, 503, "GPT-Live needs an OpenAI API key"),
    ],
    ids=["blank-offer", "missing-profile-key"],
)
def test_native_live_rejects_blank_sdp_or_missing_key_without_exchange(
    native_voice_http,
    monkeypatch,
    sdp,
    target_key,
    expected_code,
    error,
):
    from tools import voice_live

    configure_live(native_voice_http, mode="gpt-live", target_key=target_key)

    def refuse_exchange(*args, **kwargs):
        pytest.fail("Status and refused offers must not call the vendor transport")

    monkeypatch.setattr(voice_live.urllib.request, "urlopen", refuse_exchange)
    code, status = request_voice(
        native_voice_http.app, path=STATUS, ticket=native_voice_http.mint()
    )
    assert code == 200
    assert status["mode"] == "gpt-live" and status["available"] is target_key
    if target_key:
        assert status["reason"] is None
    else:
        assert "no OpenAI API key" in status["reason"]
    assert TARGET_KEY not in json.dumps(status)
    assert LAUNCH_KEY not in json.dumps(status)

    code, result = request_voice(
        native_voice_http.app,
        path=SESSION,
        ticket=native_voice_http.mint(),
        payload={"sdp": sdp},
    )
    assert code == expected_code
    assert result["detail"].startswith(error)
