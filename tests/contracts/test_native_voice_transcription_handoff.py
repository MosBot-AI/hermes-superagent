"""Synthetic recorder WAVs through the pinned live-result and registered file ASR paths."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_native_voice_capture import BLOCK_FRAMES, DEVICE_RATE
from test_native_voice_capture import capture as capture
from test_native_voice_capture import isolated_voice_home as isolated_voice_home

NAME = "synthetic-file-asr"
PLUGIN = r"""
import json
import wave
from pathlib import Path

from agent.transcription_provider import TranscriptionProvider
from hermes_constants import get_hermes_home


def record(stage, file_path, **fields):
    with (get_hermes_home() / "synthetic-calls.jsonl").open("a", encoding="utf-8") as trace:
        trace.write(json.dumps({"stage": stage, "wav": file_path,
                                "exists": Path(file_path).is_file(), **fields}) + "\n")


def observe_hook(file_path, provider, model, language, prompt, source):
    record("hook", file_path, provider=provider, model=model, source=source)
    return {"language": "fr"}


class FileASR(TranscriptionProvider):
    name = "synthetic-file-asr"

    def is_available(self):
        return True

    def transcribe(self, file_path, *, model=None, language=None, **extra):
        with wave.open(file_path, "rb") as captured:
            record("file", file_path, model=model, language=language,
                   source_forwarded="source" in extra, rate=captured.getframerate(),
                   frames=captured.getnframes())
        if (get_hermes_home() / "reject-file").exists():
            return {"success": False, "transcript": "", "error": "synthetic file failure"}
        return {"success": True, "transcript": "synthetic file transcript"}


def register(ctx):
    ctx.register_transcription_provider(FileASR())
    ctx.register_hook("pre_transcription", observe_hook)
"""

LIVE_SUCCESS = {
    "success": True,
    "transcript": "synthetic live transcript",
    "provider": "synthetic-live",
}
LIVE_EMPTY = {"success": True, "transcript": "  ", "provider": "synthetic-live"}
LIVE_FAILED = {
    "success": False,
    "transcript": "",
    "provider": "synthetic-live",
    "error": "synthetic live failure",
}


class LiveResult:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def end_audio(self):
        self.calls.append("end_audio")

    def finalize(self):
        self.calls.append("finalize")
        return self.result.copy()

    def cancel(self):
        self.calls.append("cancel")


@pytest.fixture
def registered_file_asr(capture, tmp_path, monkeypatch):
    home = capture.home
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    plugin = home / "plugins" / NAME
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        json.dumps({"name": NAME, "version": "0.0.0"}), encoding="utf-8"
    )
    (plugin / "__init__.py").write_text(PLUGIN, encoding="utf-8")
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "plugins": {"enabled": [NAME], "isolation": "in_process"},
                "stt": {"enabled": True, "streaming": False, "provider": NAME},
            }
        ),
        encoding="utf-8",
    )

    from hermes_cli import env_loader

    with monkeypatch.context() as startup:
        startup.setattr(env_loader, "load_hermes_dotenv", lambda *args, **kwargs: [])
        startup.setattr(env_loader, "apply_config_bootstrap_env", lambda *args, **kwargs: None)
        from hermes_cli import plugins
        from tools import transcription_tools, voice_mode

    monkeypatch.setattr(plugins, "_plugin_manager", None)
    monkeypatch.setattr(plugins, "_plugin_managers_by_home", {})
    monkeypatch.setattr(voice_mode, "_LIVE_SESSIONS", {})

    def deny(*args, **kwargs):
        pytest.fail("The fallback must not use a built-in or autodetected provider")

    monkeypatch.setattr(transcription_tools, "_detect_local_backend", deny)
    for provider in transcription_tools.BUILTIN_STT_PROVIDERS:
        monkeypatch.setattr(transcription_tools, f"_transcribe_{provider}", deny)

    def recording(live_result):
        for _ in range(4):
            capture.feed(1200)
        live = LiveResult(live_result)
        capture.recorder._live = live  # Inject the terminal fixture after capturing synthetic PCM.
        return capture.recorder, live

    def effects():
        trace = home / "synthetic-calls.jsonl"
        if not trace.exists():
            return []
        return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]

    manager = plugins.get_plugin_manager()
    try:
        manager.discover_and_load()
        assert manager._plugins[NAME].enabled and manager.has_hook("pre_transcription")
        yield SimpleNamespace(
            home=home, recordings=capture.recordings, recording=recording, effects=effects
        )
    finally:
        manager.unload()
        assert voice_mode._LIVE_SESSIONS == {}


def assert_file_effects(effects, wav_path, model):
    assert effects == [
        {
            "stage": "hook",
            "wav": wav_path,
            "exists": True,
            "provider": NAME,
            "source": "voice_mode",
            "model": model,
        },
        {
            "stage": "file",
            "wav": wav_path,
            "exists": True,
            "model": model,
            "language": "fr",
            "source_forwarded": False,
            "rate": DEVICE_RATE,
            "frames": 4 * BLOCK_FRAMES,
        },
    ]


@pytest.mark.parametrize(
    "live_result",
    [LIVE_SUCCESS, LIVE_EMPTY, LIVE_FAILED],
    ids=["live-success", "live-empty", "live-failed"],
)
def test_recording_uses_live_result_or_file_hook_and_leaves_wav(registered_file_asr, live_result):
    from tools import voice_mode

    fixture = registered_file_asr
    recorder, live = fixture.recording(live_result)
    wav_path = recorder.stop()
    assert wav_path is not None
    path = Path(wav_path)
    wav_before = path.read_bytes()
    result = voice_mode.transcribe_recording(wav_path, model="synthetic-model")
    assert live.calls == ["end_audio", "finalize"]
    assert wav_path not in voice_mode._LIVE_SESSIONS
    assert path.read_bytes() == wav_before
    if live_result == LIVE_SUCCESS:
        assert result == LIVE_SUCCESS
        assert fixture.effects() == []
    else:
        assert result == {
            "success": True,
            "transcript": "synthetic file transcript",
            "provider": NAME,
        }
        assert_file_effects(fixture.effects(), wav_path, "synthetic-model")
    path.unlink()


@pytest.mark.parametrize("file_failure", [False, True], ids=["file-success", "file-failed"])
def test_native_push_to_talk_caller_unlinks_wav_after_transcription(
    registered_file_asr, monkeypatch, file_failure
):
    from hermes_cli import voice
    from tools import voice_mode

    fixture = registered_file_asr
    recorder, live = fixture.recording(LIVE_FAILED)
    if file_failure:
        (fixture.home / "reject-file").touch()
    fixture.recordings.mkdir()
    other = fixture.recordings / "unrelated.wav"
    other.write_bytes(b"unrelated synthetic file")
    monkeypatch.setattr(voice, "_recorder", recorder)

    result = voice.stop_and_transcribe()

    assert result == (None if file_failure else "synthetic file transcript")
    assert voice._recorder is None
    assert live.calls == ["end_audio", "finalize"]
    effects = fixture.effects()
    assert len(effects) == 2
    wav_path = effects[0]["wav"]
    path = Path(wav_path)
    assert path.parent == fixture.recordings and path.name.startswith("recording_")
    assert wav_path not in voice_mode._LIVE_SESSIONS
    assert_file_effects(effects, wav_path, None)
    assert not path.exists() and other.read_bytes() == b"unrelated synthetic file"
    other.unlink()
