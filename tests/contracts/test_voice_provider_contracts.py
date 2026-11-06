"""Pinned public voice registrars, exercised with offline synthetic providers.

No production provider, microphone, model, socket server or credential is used.
Private manager observations verify discovery/cleanup, not a supported plugin ABI.
"""

import json
import os
from pathlib import Path

import pytest

PLUGIN_ID = "voice-contract-fixture"
NAME = "synthetic-voice-contract"

PLUGIN = """
import os
from pathlib import Path
from agent.transcription_provider import TranscriptionProvider, TranscriptionStreamSession
from agent.tts_provider import TTSProvider

class Utterance(TranscriptionStreamSession):
    def __init__(self):
        self.audio = bytearray()
        self.closed = False
    def push_audio(self, chunk):
        if self.closed:
            raise RuntimeError("utterance already finalized")
        self.audio.extend(chunk)
    def partial_transcript(self):
        return "synthetic partial" if self.audio else ""
    def finalize(self):
        if self.closed:
            return {"success": False, "transcript": "", "provider": "synthetic-voice-contract",
                    "error": "utterance already finalized"}
        self.closed = True
        return {"success": True, "transcript": "synthetic final",
                "provider": "synthetic-voice-contract",
                "bytes": len(self.audio)}

class ASR(TranscriptionProvider):
    name = "synthetic-voice-contract"
    streaming_capable = True
    def is_available(self):
        return False  # fixture is never advertised as a production-ready backend
    def list_models(self):
        return [{"id": "synthetic-only"}]
    def transcribe(self, file_path, *, model=None, language=None, **extra):
        if extra.get("fail"):
            return {"success": False, "transcript": "", "provider": self.name,
                    "error": "synthetic ASR failure"}
        return {"success": True, "transcript": "synthetic file", "provider": self.name,
                "model": model, "language": language, "bytes": len(Path(file_path).read_bytes()),
                "pid": os.getpid(), "unknown_capability": self.unknown_capability}
    def open_stream_session(self, *, language=None, prompt=None):
        return Utterance()

class Speech(TTSProvider):
    name = "synthetic-voice-contract"
    streams_pcm = True
    stream_sample_rate = 16000
    def is_available(self):
        return False
    def list_voices(self):
        return [{"id": "synthetic-voice", "language": "en"}]
    def synthesize(self, text, output_path, *, voice=None, model=None, speed=None,
                   format="mp3", **extra):
        if text == "fail":
            raise ValueError("synthetic TTS failure")
        Path(output_path).write_bytes(b"\\x00\\x00\\x01\\x00")
        return output_path
    def stream(self, text, *, voice=None, model=None, format="opus", **extra):
        yield b"\\x00\\x00"
        yield b"\\x01\\x00"

class FileASR(TranscriptionProvider):
    name = "synthetic-file-only"
    def is_available(self):
        return False
    def transcribe(self, file_path, **extra):
        return {"success": True, "transcript": "file only", "provider": self.name}

class FileSpeech(TTSProvider):
    name = "synthetic-file-only"
    def is_available(self):
        return False
    def synthesize(self, text, output_path, **extra):
        return output_path

def register(ctx):
    asr = ASR()
    asr.unknown_capability = ctx.has_capability("voice.synthetic.unknown")
    ctx.register_transcription_provider(asr)
    ctx.register_tts_provider(Speech())
    ctx.register_transcription_provider(FileASR())
    ctx.register_tts_provider(FileSpeech())
    collision_asr = ASR()
    collision_asr.name = " OPENAI "
    collision_tts = Speech()
    collision_tts.name = " OPENAI "
    ctx.register_transcription_provider(collision_asr)
    ctx.register_tts_provider(collision_tts)
"""


@pytest.fixture(params=["in_process", "host"])
def voice_host(request, tmp_path, monkeypatch):
    from hermes_cli.plugins import PluginManager

    home = tmp_path / "profile"
    plugin = home / "plugins" / PLUGIN_ID
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        json.dumps({"name": PLUGIN_ID, "version": "0.0.0"}), encoding="utf-8"
    )
    (plugin / "__init__.py").write_text(PLUGIN, encoding="utf-8")
    config = {
        "plugins": {"enabled": [PLUGIN_ID], "isolation": request.param},
        "stt": {"provider": "local", "model": "unchanged-asr"},
        "tts": {"provider": "edge", "model": "unchanged-tts"},
        "model": "unchanged-main-model",
    }
    config_path = home / "config.yaml"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    before = config_path.read_bytes()
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "os-home")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    manager = PluginManager()
    try:
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        assert loaded.enabled and loaded.error is None, loaded.error
        assert config_path.read_bytes() == before
        yield request.param, home, manager
    finally:
        manager.unload()
        if request.param == "host":
            manager._plugin_host().shutdown()
        assert config_path.read_bytes() == before


def providers(manager, name=NAME):
    from agent import transcription_registry, tts_registry

    return (
        transcription_registry.get_provider(name, scope=manager.scope_key),
        tts_registry.get_provider(name, scope=manager.scope_key),
    )


def test_public_registration_types_file_results_and_unknown_capability(voice_host):
    from agent.transcription_provider import TranscriptionProvider
    from agent.tts_provider import TTSProvider

    mode, home, manager = voice_host
    asr, tts = providers(manager)
    assert isinstance(asr, TranscriptionProvider)
    assert isinstance(tts, TTSProvider)
    assert asr.is_available() is False and tts.is_available() is False
    assert asr.default_model() == "synthetic-only"
    assert tts.default_voice() == "synthetic-voice"
    source = home / "synthetic.pcm"
    source.write_bytes(b"\x00\x00\x01\x00")
    result = asr.transcribe(str(source), model="explicit-model", language="en", ignored="yes")
    assert result["success"] is True and result["transcript"] == "synthetic file"
    assert result["model"] == "explicit-model" and result["language"] == "en"
    assert result["bytes"] == 4 and result["unknown_capability"] is False
    assert (result["pid"] == os.getpid()) is (mode == "in_process")
    output = home / "synthetic-output.pcm"
    assert tts.synthesize("synthetic", str(output), format="pcm", ignored="yes") == str(output)
    assert output.read_bytes() == source.read_bytes()


def test_asr_error_envelope_and_tts_raising_failure(voice_host):
    _, home, manager = voice_host
    asr, tts = providers(manager)
    result = asr.transcribe(str(home / "unused"), fail=True)
    assert result == {
        "success": False,
        "transcript": "",
        "provider": NAME,
        "error": "synthetic ASR failure",
    }
    # The native IPC exception allowlist preserves this built-in failure type.
    with pytest.raises(ValueError, match="synthetic TTS failure"):
        tts.synthesize("fail", str(home / "never-created"))
    assert not (home / "never-created").exists()


def test_optional_streaming_defaults_and_unsupported_cancellation(voice_host):
    _, _, manager = voice_host
    asr, tts = providers(manager, "synthetic-file-only")
    assert asr.streaming_capable is False
    assert tts.streams_pcm is False and tts.stream_sample_rate is None
    with pytest.raises(NotImplementedError, match="streaming"):
        asr.open_stream_session()
    with pytest.raises(NotImplementedError, match="streaming"):
        tts.stream("synthetic")
    assert not callable(getattr(asr, "cancel", None))
    assert not callable(getattr(tts, "cancel", None))


def test_optional_stream_return_values(voice_host):
    from agent.transcription_provider import TranscriptionStreamSession
    from hermes_cli.plugin_host_wire import Opaque

    mode, _, manager = voice_host
    asr, tts = providers(manager)
    assert asr.streaming_capable is True
    assert tts.streams_pcm is True and tts.stream_sample_rate == 16000
    session = asr.open_stream_session(language="en", prompt="synthetic")
    stream = tts.stream("synthetic", format="pcm")
    if mode == "host":
        # Registered provider ABCs survive IPC; returned live sessions/generators do not.
        assert isinstance(session, Opaque)
        assert isinstance(stream, Opaque)
        assert not isinstance(session, TranscriptionStreamSession)
        assert not callable(getattr(session, "push_audio", None))
        assert not callable(getattr(session, "finalize", None))
        with pytest.raises(TypeError):
            iter(stream)
        return
    assert isinstance(session, TranscriptionStreamSession)
    assert session.partial_transcript() == ""
    session.push_audio(b"\x00")
    session.push_audio(b"\x00\x01\x00")
    assert session.partial_transcript() == "synthetic partial"
    assert session.finalize() == {
        "success": True,
        "transcript": "synthetic final",
        "provider": NAME,
        "bytes": 4,
    }
    assert session.finalize()["success"] is False
    with pytest.raises(RuntimeError, match="already finalized"):
        session.push_audio(b"\x00\x00")
    assert not callable(getattr(session, "cancel", None))
    assert list(stream) == [b"\x00\x00", b"\x01\x00"]


def test_builtin_collision_and_unknown_provider_never_register(voice_host):
    _, _, manager = voice_host
    assert providers(manager, "openai") == (None, None)
    assert providers(manager, "unknown-voice-contract") == (None, None)
    assert all(provider is not None for provider in providers(manager))


def test_unload_removes_scoped_registrations(voice_host):
    _, _, manager = voice_host
    assert all(provider is not None for provider in providers(manager))
    manager.unload()
    assert providers(manager) == (None, None)
    assert providers(manager, "synthetic-file-only") == (None, None)
