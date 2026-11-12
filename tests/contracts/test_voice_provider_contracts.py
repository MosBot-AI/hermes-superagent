"""Pinned public voice registrars, exercised with offline synthetic providers.

No production provider, microphone, model, socket server or credential is used.
Private manager observations verify discovery/cleanup, not a supported plugin ABI.
"""

import json
import os
import wave
from pathlib import Path
from struct import pack
from threading import Event

import pytest

PLUGIN_ID = "voice-contract-fixture"
NAME = "synthetic-voice-contract"
READY_ASR = "synthetic-ready-asr"

PLUGIN = """
import json
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
                "bytes": len(self.audio), "pcm_hex": self.audio.hex()}

class ASR(TranscriptionProvider):
    name = "synthetic-voice-contract"
    streaming_capable = True
    def is_available(self):
        return False  # fixture is never advertised as a production-ready backend
    def list_models(self):
        return [{"id": "synthetic-only"}]
    def transcribe(self, file_path, *, model=None, language=None, **extra):
        source = Path(file_path)
        source.with_suffix(".called").write_text(self.name)
        if extra.get("fail"):
            return {"success": False, "transcript": "", "provider": self.name,
                    "error": "synthetic ASR failure"}
        return {"success": True, "transcript": "synthetic file", "provider": self.name,
                "model": model, "language": language, "prompt": extra.get("prompt"),
                "bytes": len(source.read_bytes()),
                "pid": os.getpid(), "unknown_capability": self.unknown_capability}
    def open_stream_session(self, *, language=None, prompt=None):
        return Utterance()

class ReadyASR(ASR):
    name = "synthetic-ready-asr"
    unknown_capability = False
    def is_available(self):
        return True

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
        output = Path(output_path)
        if text == "fail":
            raise ValueError("synthetic TTS failure")
        if text == "partial failure":
            output.write_bytes(b"partial")
            raise ValueError("synthetic partial TTS failure")
        if text == "dispatch settings":
            output.write_text(f"{voice}/{model}/{speed}/{format}/{os.getpid()}")
        else:
            output.write_bytes(b"\\x00\\x00\\x01\\x00")
        return output_path
    def stream(self, text, *, voice=None, model=None, format="opus", **extra):
        yield b"\\x00\\x00"
        yield b"\\x01\\x00"

class ReadySpeech(Speech):
    name = "synthetic-ready-tts"
    stream_sample_rate = 22050
    def is_available(self):
        return True
    def stream(self, text, *, voice=None, model=None, format="opus", **extra):
        home = Path(os.environ["HERMES_HOME"])
        received = {"text": text, "voice": voice, "model": model, "format": format,
                    "speed": extra.get("speed"), "pid": os.getpid()}
        (home / "tts-stream-opened.json").write_text(json.dumps(received), encoding="utf-8")
        return self._chunks(home)
    def _chunks(self, home):
        (home / "tts-stream-iterated").touch()
        yield b"\\x00\\x00"
        yield b"\\x01\\x00\\x02\\x00"

class InvalidRateSpeech(ReadySpeech):
    name = "synthetic-invalid-rate-tts"
    stream_sample_rate = True

class FileASR(TranscriptionProvider):
    name = "synthetic-file-only"
    def is_available(self):
        return True
    def transcribe(self, file_path, **extra):
        return {"success": True, "transcript": "file only", "provider": self.name}

class FileSpeech(TTSProvider):
    name = "synthetic-file-only"
    def is_available(self):
        return False
    def synthesize(self, text, output_path, **extra):
        return output_path

class ReadyFileSpeech(FileSpeech):
    name = "synthetic-ready-file-tts"
    def is_available(self):
        return True

def register(ctx):
    asr = ASR()
    asr.unknown_capability = ctx.has_capability("voice.synthetic.unknown")
    ctx.register_transcription_provider(asr)
    ctx.register_transcription_provider(ReadyASR())
    ctx.register_tts_provider(Speech())
    ctx.register_tts_provider(ReadySpeech())
    ctx.register_tts_provider(InvalidRateSpeech())
    ctx.register_tts_provider(ReadyFileSpeech())
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
    from hermes_cli import plugins

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
    monkeypatch.setattr(plugins, "_plugin_manager", None)
    monkeypatch.setattr(plugins, "_plugin_managers_by_home", {})
    manager = plugins.get_plugin_manager()
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
        "pcm_hex": "00000100",
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


@pytest.fixture
def voice_config(voice_host, monkeypatch):
    import pm

    monkeypatch.setattr(pm, "ensure_import", unexpected_backend)
    _, home, _ = voice_host
    path = home / "config.yaml"
    before = path.read_bytes()
    expected = before

    def configure(**sections):
        nonlocal expected
        config = {**json.loads(before), **sections}
        expected = json.dumps(config).encode()
        path.write_bytes(expected)

    try:
        yield configure
        assert path.read_bytes() == expected
    finally:
        path.write_bytes(before)


def unexpected_backend(*args, **kwargs):
    pytest.fail("Unexpected provider detection, installation or backend invocation")


@pytest.fixture
def synthetic_recording(tmp_path, monkeypatch):
    from tools import transcription_tools

    monkeypatch.setattr(transcription_tools, "_detect_local_backend", unexpected_backend)
    for provider in transcription_tools.BUILTIN_STT_PROVIDERS:
        monkeypatch.setattr(transcription_tools, f"_transcribe_{provider}", unexpected_backend)

    recording = tmp_path / "synthetic.wav"
    with wave.open(str(recording), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(bytes(320))
    return recording


def test_stt_file_dispatch_uses_selected_plugin(voice_config, synthetic_recording, voice_host):
    from tools.transcription_tools import transcribe_audio

    mode, _, _ = voice_host
    voice_config(
        stt={
            "provider": READY_ASR,
            "prompt": "synthetic vocabulary",
            READY_ASR: {"language": "en", "model": "configured-model"},
        },
    )
    result = transcribe_audio(str(synthetic_recording), model="explicit-model")
    assert result["success"] is True
    assert result["transcript"] == "synthetic file"
    assert result["provider"] == READY_ASR
    assert result["model"] == "explicit-model"
    assert result["language"] == "en"
    assert result["prompt"] == "synthetic vocabulary"
    assert result["bytes"] == synthetic_recording.stat().st_size
    assert (result["pid"] == os.getpid()) is (mode == "in_process")
    assert synthetic_recording.with_suffix(".called").read_text() == READY_ASR


@pytest.mark.parametrize(
    ("config", "error"),
    [
        ({"provider": READY_ASR, "enabled": False}, "STT is disabled"),
        ({"provider": NAME}, f"STT plugin '{NAME}' is not available"),
        ({"provider": "synthetic-missing"}, "no built-in, command, or plugin provider"),
    ],
    ids=["disabled", "unavailable", "unregistered"],
)
def test_stt_file_dispatch_does_not_fall_back(
    voice_config,
    synthetic_recording,
    config,
    error,
):
    from tools.transcription_tools import transcribe_audio

    voice_config(stt=config)
    result = transcribe_audio(str(synthetic_recording))
    assert result["success"] is False
    assert result["transcript"] == ""
    assert error in result["error"]
    assert not synthetic_recording.with_suffix(".called").exists()
    if config["provider"] == "synthetic-missing":
        assert result["provider"] == "synthetic-missing"
        assert result["error_type"] == "provider_not_registered"


@pytest.fixture
def stt_streaming(monkeypatch):
    from tools import transcription_streaming, transcription_tools

    monkeypatch.setattr(transcription_streaming, "_builtin_session", unexpected_backend)
    monkeypatch.setattr(transcription_tools, "_detect_local_backend", unexpected_backend)
    return transcription_streaming


@pytest.mark.parametrize(
    "config",
    [
        {"provider": NAME},
        {"provider": NAME, "streaming": True, "enabled": False},
        {"provider": "synthetic-missing", "streaming": True},
        {"provider": "synthetic-file-only", "streaming": True},
    ],
    ids=["not-opted-in", "disabled", "unregistered", "file-only"],
)
def test_stt_streaming_consumer_refuses_unavailable_routes(voice_config, stt_streaming, config):
    voice_config(stt=config)
    assert stt_streaming.streaming_available() is False
    assert stt_streaming.open_streaming_session() is None


@pytest.mark.parametrize(
    ("voice_host", "input_rate"),
    [("in_process", 16000), ("in_process", 32000), ("host", 16000)],
    indirect=["voice_host"],
)
def test_stt_streaming_consumer_delivers_pcm_or_reports_host_projection(
    voice_config, voice_host, stt_streaming, input_rate
):
    mode, _, manager = voice_host
    asr, _ = providers(manager)
    assert asr.is_available() is False
    voice_config(stt={"provider": NAME, "streaming": True})
    assert stt_streaming.streaming_available() is True

    received_partial = Event()
    partials = []

    def on_partial(text):
        partials.append(text)
        received_partial.set()

    session = stt_streaming.open_streaming_session(on_partial=on_partial)
    assert session is not None
    worker = session._worker
    assert worker is not None
    expected_pcm = pack("<h", 500) * 160  # 10 ms of mono s16le at 16 kHz
    input_pcm = pack("<2h", 300, 700) * 160 if input_rate == 32000 else expected_pcm
    try:
        session.set_input_rate(input_rate)
        session.push_audio(input_pcm)
        if mode == "in_process":
            assert received_partial.wait(3)
            assert session.partial_transcript() == "synthetic partial"
            assert session.finalize(timeout=3) == {
                "success": True,
                "transcript": "synthetic final",
                "provider": NAME,
                "bytes": len(expected_pcm),
                "pcm_hex": expected_pcm.hex(),
            }
            assert partials == ["synthetic partial"]
        else:
            result = session.finalize(timeout=3)
            assert result["success"] is False
            assert result["transcript"] == ""
            assert result["provider"] == NAME
            assert result["error"].startswith("live transcription failed:")
            assert "not available inside the plugin host" in result["error"]
            assert partials == []
    finally:
        session.cancel()
        worker.join(timeout=3)
    assert not worker.is_alive()


@pytest.mark.parametrize("voice_host", ["in_process"], indirect=True)
def test_stt_streaming_cancel_settles_local_result_before_provider_finishes(
    voice_config, voice_host, stt_streaming, monkeypatch
):
    _, _, manager = voice_host
    asr, _ = providers(manager)
    utterance = asr.open_stream_session()
    original_finalize = utterance.finalize
    finalizing = Event()
    release = Event()
    provider_results = []

    def blocked_finalize():
        finalizing.set()
        if not release.wait(10):
            raise RuntimeError("Synthetic finalize was not released")
        result = original_finalize()
        provider_results.append(result)
        return result

    monkeypatch.setattr(utterance, "finalize", blocked_finalize)
    monkeypatch.setattr(asr, "open_stream_session", lambda **hints: utterance)
    voice_config(stt={"provider": NAME, "streaming": True})
    session = stt_streaming.open_streaming_session()
    assert session is not None
    worker = session._worker
    assert worker is not None
    cancelled = {"success": False, "transcript": "", "provider": NAME, "error": "cancelled"}
    try:
        session.end_audio()
        assert finalizing.wait(3)
        session.cancel()
        assert session.finalize(timeout=3) == cancelled
        assert worker.is_alive()
        assert provider_results == []
    finally:
        if not finalizing.is_set():
            session.cancel()
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert len(provider_results) == 1
    assert provider_results[0]["success"] is True
    assert session.finalize(timeout=3) == cancelled


def test_tts_file_dispatch_uses_configured_plugin_despite_listing_readiness(
    voice_config,
    voice_host,
    tmp_path,
    monkeypatch,
):
    from tools import tts_tool

    mode, _, _ = voice_host
    monkeypatch.setattr(tts_tool, "_select_builtin_engine", unexpected_backend)
    voice_config(
        tts={
            "provider": NAME,
            "voice": "synthetic-voice",
            "model": "synthetic-model",
            "speed": 1.25,
            "output_format": "PCM",
        },
    )
    output = tmp_path / "selected.pcm"
    assert tts_tool.check_tts_requirements() is False
    result = json.loads(
        tts_tool.text_to_speech_tool("dispatch settings", str(output), provider="minimax"),
    )
    assert result["success"] is True
    assert result["provider"] == NAME
    assert result["file_paths"] == [str(output)]
    settings, pid = output.read_text().rsplit("/", 1)
    assert settings == "synthetic-voice/synthetic-model/1.25/pcm"
    assert (int(pid) == os.getpid()) is (mode == "in_process")


def test_tts_plugin_failure_discards_partial_output_and_preserves_existing_file(
    voice_config,
    tmp_path,
    monkeypatch,
):
    from tools import tts_tool

    monkeypatch.setattr(tts_tool, "_select_builtin_engine", unexpected_backend)
    voice_config(tts={"provider": NAME, "output_format": "pcm"})
    directory = tmp_path / "audio"
    directory.mkdir()
    output = directory / "existing.pcm"
    output.write_bytes(b"existing")

    result = json.loads(tts_tool.text_to_speech_tool("partial failure", str(output)))

    assert result["success"] is False
    assert "synthetic partial TTS failure" in result["error"]
    assert output.read_bytes() == b"existing"
    assert list(directory.iterdir()) == [output]


@pytest.fixture
def resolve_tts_streamer(voice_config, monkeypatch):
    from tools import tts_streaming, tts_tool

    for provider in tts_streaming._REGISTRY.values():
        monkeypatch.setattr(provider, "available", staticmethod(unexpected_backend))

    def resolve(**config):
        voice_config(tts=config)
        return tts_streaming.resolve_streaming_provider(tts_tool._load_tts_config())

    return resolve


def test_tts_stream_resolves_pcm_provider_but_host_cannot_iterate(resolve_tts_streamer, voice_host):
    mode, home, _ = voice_host
    opened = home / "tts-stream-opened.json"
    iterated = home / "tts-stream-iterated"
    streamer = resolve_tts_streamer(
        provider="synthetic-ready-tts",
        voice="fixture-voice",
        model="fixture-model",
        speed=1.25,
    )
    assert streamer is not None
    assert (streamer.sample_rate, streamer.channels, streamer.sample_width) == (22050, 1, 2)
    chunks = streamer.stream("synthetic text")
    assert not opened.exists()
    if mode == "in_process":
        assert list(chunks) == [b"\x00\x00", b"\x01\x00\x02\x00"]
        assert iterated.exists()
    else:
        with pytest.raises(TypeError, match="Opaque.*not iterable"):
            next(chunks)
        assert not iterated.exists()

    received = json.loads(opened.read_text(encoding="utf-8"))
    assert (received.pop("pid") == os.getpid()) is (mode == "in_process")
    assert received == {
        "text": "synthetic text",
        "voice": "fixture-voice",
        "model": "fixture-model",
        "format": "pcm",
        "speed": 1.25,
    }


@pytest.mark.parametrize(
    "name",
    [NAME, "synthetic-invalid-rate-tts", "synthetic-ready-file-tts", "synthetic-missing"],
    ids=["unavailable", "invalid-rate", "file-only", "unregistered"],
)
def test_tts_stream_unusable_explicit_selection_has_no_substitute(
    resolve_tts_streamer,
    voice_host,
    name,
):
    _, home, _ = voice_host
    streamer = resolve_tts_streamer(provider="synthetic-ready-tts", streaming={"provider": name})
    assert streamer is None
    assert not (home / "tts-stream-opened.json").exists()


@pytest.mark.parametrize(
    ("edge_available", "neutts_available", "expected_engine", "reported_provider"),
    [
        (True, True, "edge", "synthetic-missing"),
        (False, True, "neutts", "neutts"),
        (False, False, None, None),
    ],
    ids=["edge", "neutts", "unavailable"],
)
def test_unknown_tts_file_provider_falls_through_to_native_defaults(
    voice_config,
    tmp_path,
    monkeypatch,
    edge_available,
    neutts_available,
    expected_engine,
    reported_provider,
):
    from tools import tts_tool

    calls = []
    synthesize_builtin = tts_tool._synthesize_builtin

    def import_edge():
        if not edge_available:
            raise ImportError("synthetic missing Edge SDK")

    def write_edge(_text, path, _config):
        calls.append("edge")
        Path(path).write_bytes(b"synthetic Edge output")

    def write_neutts(_text, path, _config):
        calls.append("neutts")
        Path(path).write_bytes(b"synthetic NeuTTS output")

    def guard_synthesis(engine, text, path, config, instructions):
        if engine not in {"synthetic-missing", "edge", "neutts"}:
            unexpected_backend()
        synthesize_builtin(engine, text, path, config, instructions)

    monkeypatch.setattr(tts_tool, "_import_edge_tts", import_edge)
    monkeypatch.setattr(tts_tool, "_check_neutts_available", lambda: neutts_available)
    monkeypatch.setattr(tts_tool, "_run_edge_tts", write_edge)
    monkeypatch.setattr(tts_tool, "_generate_neutts", write_neutts)
    monkeypatch.setattr(tts_tool, "_synthesize_builtin", guard_synthesis)
    voice_config(tts={"provider": "synthetic-missing"})
    output = tmp_path / "fallback.mp3"

    assert tts_tool.check_tts_requirements() is False
    assert calls == []
    result = json.loads(tts_tool.text_to_speech_tool("synthetic speech", str(output)))

    if expected_engine is None:
        assert result["success"] is False
        assert "No TTS provider available" in result["error"]
        assert calls == []
        assert not output.exists()
    else:
        assert result["success"] is True
        assert result["provider"] == reported_provider
        assert result["file_paths"] == [str(output)]
        assert calls == [expected_engine]
        assert output.stat().st_size > 0
