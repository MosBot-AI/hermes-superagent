"""Pinned sidecar and LOCAL capture controls exercised with synthetic endpoints."""

import os
import sys
import threading
from threading import Event
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def sidecar(tmp_path, monkeypatch):
    from hermes_cli import env_loader
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text('{"voice": {"stop_phrases": ["stop"]}}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    token = set_hermes_home_override(home)
    try:
        with monkeypatch.context() as startup:
            # The startup loader also considers an ignored .env in the host checkout.
            startup.setattr(env_loader, "load_hermes_dotenv", lambda **_: [])
            # Import configures stdout and crash hooks for the standalone sidecar.
            startup.setattr(sys, "stdout", sys.stdout)
            startup.setattr(sys, "excepthook", sys.excepthook)
            startup.setattr(threading, "excepthook", threading.excepthook)
            from tui_gateway import server

        yield server
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize(
    ("phase", "interrupted"),
    [("playback", ()), ("generation", ("session-a", "session-b"))],
)
def test_sidecar_barge_in_stops_media_before_any_turn_interrupt(
    sidecar, monkeypatch, phase, interrupted
):
    from tools import tts_streaming

    effects = []
    stream_stop = Event()
    fallback_stops = [Event(), Event()]

    def media_stopped():
        return stream_stop.is_set() and all(stop.is_set() for stop in fallback_stops)

    def agent(session_id):
        def interrupt():
            file_stopped = ("file-playback-stop", True) in effects
            effects.append(("interrupt", session_id, media_stopped() and file_stopped))

        return SimpleNamespace(interrupt=interrupt)

    playback = ModuleType("tools.voice_mode")
    playback.stop_playback = lambda: effects.append(("file-playback-stop", media_stopped()))
    monkeypatch.setitem(sys.modules, "tools.voice_mode", playback)
    monkeypatch.setattr(
        tts_streaming, "mark_speech_interrupted", lambda: effects.append(("latch",))
    )
    monkeypatch.setattr(sidecar, "_voice_emit", lambda event: effects.append(("emit", event)))
    monkeypatch.setattr(sidecar, "_tts_stream_state", {"stop": stream_stop, "done": Event()})
    monkeypatch.setattr(
        sidecar, "_fd_speak_pipelines", [(stop, Event()) for stop in fallback_stops]
    )
    monkeypatch.setattr(
        sidecar,
        "_sessions",
        {
            "session-a": {"running": True, "agent": agent("session-a")},
            "session-b": {"running": True, "agent": agent("session-b")},
            "idle": {"running": False, "agent": agent("idle")},
        },
    )

    # The sidecar binds the split voice module's functions to the live server globals.
    sidecar._fd_trip(phase)

    assert media_stopped()
    assert sidecar._tts_stream_state is None
    assert effects[0] == ("latch",)
    assert ("file-playback-stop", True) in effects
    assert effects[-1] == ("emit", "voice.interrupted")
    assert sorted(effect for effect in effects if effect[0] == "interrupt") == [
        ("interrupt", session_id, True) for session_id in interrupted
    ]


def test_local_typed_stop_helper_fences_only_the_target_capture(sidecar, monkeypatch):
    from gateway import run_api
    from gateway.config import Platform

    effects = []
    saved_modes = []
    modes = {"capturing": "voice_only", "other": "voice_only"}
    sessions = {
        session_id: SimpleNamespace(
            source=SimpleNamespace(platform=Platform.LOCAL, chat_id=session_id)
        )
        for session_id in modes
    }
    runner = SimpleNamespace(
        _voice_mode=modes,
        _voice_key_for_source=lambda source: source.chat_id,
        _save_voice_modes=lambda: saved_modes.append(modes.copy()),
        session_authority=SimpleNamespace(sessions=sessions),
    )
    monkeypatch.setattr(run_api, "_ACTIVE_RUNNER", runner)
    monkeypatch.setenv("HERMES_VOICE", "1")
    monkeypatch.setenv("HERMES_VOICE_TTS", "1")
    monkeypatch.setattr(sidecar, "_voice_capture_sid", "capturing")
    monkeypatch.setattr(sidecar, "_voice_capture_gen", 0)
    monkeypatch.setattr(sidecar, "_voice_wake_owner", None)
    microphone = ModuleType("hermes_cli.voice")
    microphone.stop_continuous = lambda: effects.append(("capture-stop",))
    monkeypatch.setitem(sys.modules, "hermes_cli.voice", microphone)
    monkeypatch.setattr(
        sidecar, "_tts_stream_stop", lambda *, user_barge: effects.append(("tts-stop", user_barge))
    )
    monkeypatch.setattr(sidecar, "_voice_emit", lambda *args: effects.append(("emit", *args)))
    transcripts = []
    callback = sidecar._voice_capture_callback(transcripts.append)

    # Exercise the helper used after canonical admission checks, without invoking the wire path.
    assert sidecar._consume_typed_stop_phrase("stop working", "capturing", emit=False) is False
    assert sidecar._consume_typed_stop_phrase(" Stop! ", "other", emit=False) is True
    assert modes == {"capturing": "voice_only", "other": "off"}
    assert effects == [("tts-stop", False)]
    callback("still active")

    assert sidecar._consume_typed_stop_phrase("stop", "capturing", emit=False) is True
    callback("late text")
    assert transcripts == ["still active"]
    assert effects == [("tts-stop", False), ("capture-stop",), ("tts-stop", False)]
    assert saved_modes == [
        {"capturing": "voice_only", "other": "off"},
        {"capturing": "off", "other": "off"},
    ]
    assert os.environ["HERMES_VOICE"] == os.environ["HERMES_VOICE_TTS"] == "1"
