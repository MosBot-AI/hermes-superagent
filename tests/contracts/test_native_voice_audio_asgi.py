"""Native local audio WebSockets with synthetic providers and in-memory ASGI frames."""

import asyncio
import json
import os
import socket
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from selectors import SelectSelector
from types import SimpleNamespace

import pytest

TRANSCRIBE = "/api/audio/transcribe-stream"
SPEAK = "/api/audio/speak-stream"
PROTOCOL = "hermes-gateway-v1"
PROVIDER = "synthetic-native-audio"
SENTENCE = "The synthetic sentence is long enough."
TRANSCRIBE_FRAMES = (
    {"type": "websocket.receive", "text": '{"sample_rate":16000}'},
    {"type": "websocket.receive", "bytes": b"\x01\x00\x02\x00"},
    {"type": "websocket.receive", "text": '{"eos":true}'},
)
PLUGIN = r"""
import json
import os
from agent.secret_scope import get_secret
from agent.transcription_provider import TranscriptionProvider, TranscriptionStreamSession
from agent.tts_provider import TTSProvider
from hermes_constants import get_hermes_home


def record(stage, **fields):
    home = get_hermes_home()
    with (home / "audio-calls.jsonl").open("a", encoding="utf-8") as sink:
        data = {"stage": stage, "home": str(home), "pid": os.getpid(),
                "marker": get_secret("VOICE_PROBE_MARKER"), **fields}
        sink.write(json.dumps(data) + "\n")


class Utterance(TranscriptionStreamSession):
    def __init__(self):
        self.audio = bytearray()
    def push_audio(self, chunk):
        self.audio.extend(chunk)
    def partial_transcript(self):
        return ""
    def finalize(self):
        record("asr-finalize", pcm=self.audio.hex())
        return {
            "success": True, "transcript": "synthetic final", "provider": "synthetic-native-audio",
        }


class ASR(TranscriptionProvider):
    name = "synthetic-native-audio"
    streaming_capable = True
    def is_available(self):
        return True
    def transcribe(self, *args, **kwargs):
        record("asr-file")
        raise AssertionError("Unexpected file transcription")
    def open_stream_session(self, *, language=None, prompt=None):
        record("asr-open", language=language, prompt=prompt)
        return Utterance()


class Speech(TTSProvider):
    name = "synthetic-native-audio"
    streams_pcm = True
    stream_sample_rate = 22050
    def is_available(self):
        record("tts-resolve")
        return True
    def synthesize(self, *args, **kwargs):
        record("tts-file")
        raise AssertionError("Unexpected file synthesis")
    def stream(self, text, *, voice=None, model=None, format="opus", **extra):
        record("tts-open", text=text, voice=voice, model=model, format=format,
               speed=extra.get("speed"))
        return self.chunks()
    def chunks(self):
        record("tts-iterate")
        yield b"\x01\x00"
        yield b"\x02\x00\x03\x00"


def register(ctx):
    ctx.register_transcription_provider(ASR())
    ctx.register_tts_provider(Speech())
"""


def audio_messages(app, path, frames, *, ticket=None, query=b"", origin=None):
    protocols = [PROTOCOL, f"hermes-gateway-ticket.{ticket}"] if ticket else []
    headers = [(b"host", b"127.0.0.1:8765")]
    if protocols:
        headers.append((b"sec-websocket-protocol", ", ".join(protocols).encode()))
    if origin is not None:
        headers.append((b"origin", origin))
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query,
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
        "subprotocols": protocols,
        "state": {},
    }
    incoming = deque([{"type": "websocket.connect"}, *frames])
    sent = []

    async def receive():
        if incoming:
            return incoming.popleft()
        # Keep the client connected after done until the native route closes it.
        return await asyncio.Future()

    async def send(message):
        sent.append(message)

    run_audio_app(app, scope, receive, send)
    return sent


def run_audio_app(app, scope, receive, send):
    async def drive():
        task = asyncio.create_task(app(scope, receive, send))
        try:
            async with asyncio.timeout(5):
                # The test loop stays runnable when sandbox thread wakeups are delayed.
                while not task.done():
                    await asyncio.sleep(0.002)
                await task
        finally:
            pending = asyncio.all_tasks() - {asyncio.current_task()}
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                _, remaining = await asyncio.wait(pending, timeout=1)
                assert not remaining, "Native audio left pending ASGI tasks"

    # Keep executor shutdown synchronous and avoid a TestClient thread portal.
    with ThreadPoolExecutor(max_workers=2) as executor:
        loop = asyncio.SelectorEventLoop(SelectSelector())
        loop.set_default_executor(executor)
        try:
            loop.run_until_complete(drive())
        finally:
            loop.close()


@pytest.fixture
def native_audio_gateway(tmp_path, monkeypatch):
    launch = tmp_path / "launch"
    profile = launch / "profiles" / "fixture"
    profile.mkdir(parents=True)
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("HERMES_DASHBOARD_SESSION_TOKEN", "synthetic-dashboard-fixture")
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    for name in ("GROQ_API_KEY", "ELEVENLABS_API_KEY", "VOICE_TOOLS_OPENAI_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for home in (launch, profile):
        (home / "config.yaml").write_text("{}", encoding="utf-8")

    import pm
    from hermes_cli import env_loader

    unexpected_calls = []

    def refuse(*args, **kwargs):
        unexpected_calls.append("Unexpected network, install or voice backend invocation")
        raise AssertionError(unexpected_calls[-1])

    monkeypatch.setattr(pm, "ensure_import", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "bind", refuse)
    monkeypatch.setattr(socket.socket, "listen", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    with monkeypatch.context() as startup:
        # Startup may consider the pinned checkout's developer .env; only fixture homes are used.
        startup.setattr(env_loader, "load_hermes_dotenv", lambda *args, **kwargs: [])
        startup.setattr(env_loader, "apply_config_bootstrap_env", lambda *args, **kwargs: None)
        from agent.secret_scope import is_multiplex_active, set_multiplex_active
        from gateway.run_api import GatewayRuntimeAPI
        from gateway.runtime_bootstrap import TicketStore
        from gateway.session_authorities import SessionAuthorities
        from hermes_cli import profiles, web_server
        from tui_gateway import launch_profile_policy

    monkeypatch.setattr(launch_profile_policy, "_snapshot", None)
    monkeypatch.setattr(profiles, "_get_default_hermes_home", lambda: launch)
    monkeypatch.setattr(profiles, "_get_profiles_root", lambda: launch / "profiles")

    authorities = SessionAuthorities(launch, multiplexed=True)
    for home in (launch, profile):
        authorities.add(home, SimpleNamespace(profile_id=str(home), instance_id="fixture"))
    store = TicketStore("fixture", authorities.profile_ids())
    runner = SimpleNamespace(
        session_authorities=authorities,
        session_ticket_store=store,
        _draining=False,
        session_runtime_descriptor={
            "state": "ready",
            "instance_id": "fixture",
            "served_profiles": authorities.served_profiles(),
        },
    )
    state = web_server.app.state
    monkeypatch.setattr(state, "gateway_runner", runner, raising=False)
    monkeypatch.setattr(state, "ui_surface", "gateway", raising=False)
    monkeypatch.setattr(state, "auth_required", False, raising=False)
    monkeypatch.setattr(state, "bound_host", "127.0.0.1", raising=False)
    previous_multiplexed = is_multiplex_active()
    try:
        yield SimpleNamespace(
            app=GatewayRuntimeAPI(web_server.app, runner, web_server.app),
            store=store,
            state=state,
            launch=launch,
            profile=profile,
            refuse=refuse,
        )
    finally:
        set_multiplex_active(previous_multiplexed)
        assert not unexpected_calls


@pytest.fixture
def native_audio(native_audio_gateway, monkeypatch, request):
    from hermes_cli import plugins
    from hermes_cli.dashboard_auth.native_http import grant_home_scope
    from hermes_cli.web_routers import audio
    from hermes_cli.web_server_profiles import _config_profile_scope
    from tools import transcription_streaming, tts_streaming, tts_tool

    isolation = getattr(request, "param", "in_process")
    profile = native_audio_gateway.profile
    launch = native_audio_gateway.launch
    plugin = profile / "plugins" / PROVIDER
    plugin.mkdir(parents=True)
    (launch / ".env").write_text("VOICE_PROBE_MARKER=launch\n", encoding="utf-8")
    (profile / ".env").write_text("VOICE_PROBE_MARKER=target\n", encoding="utf-8")
    config = {
        "plugins": {"enabled": [PROVIDER], "isolation": isolation},
        "stt": {
            "provider": PROVIDER,
            "streaming": True,
            "prompt": "fixture prompt",
            PROVIDER: {"language": "en"},
        },
        "tts": {
            "provider": PROVIDER,
            "voice": "fixture-voice",
            "model": "fixture-model",
            "speed": 1.25,
        },
    }
    (profile / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
    (plugin / "plugin.yaml").write_text(
        json.dumps({"name": PROVIDER, "version": "0.0.0"}), encoding="utf-8"
    )
    (plugin / "__init__.py").write_text(PLUGIN, encoding="utf-8")
    refuse = native_audio_gateway.refuse
    monkeypatch.setattr(transcription_streaming, "_builtin_session", refuse)
    monkeypatch.setattr(audio, "_sync_sentence_to_pcm", refuse)
    monkeypatch.setattr(tts_tool, "text_to_speech_tool", refuse)
    for provider in tts_streaming._REGISTRY.values():
        monkeypatch.setattr(provider, "available", staticmethod(refuse))
    monkeypatch.setattr(plugins, "_plugin_manager", None)
    monkeypatch.setattr(plugins, "_plugin_managers_by_home", {})
    manager = None
    try:
        # Prepare the synthetic provider registry before dialing the native route.
        with grant_home_scope({"profile_id": str(profile)}), _config_profile_scope(None):
            manager = plugins.get_plugin_manager()
            manager.discover_and_load()
            loaded = manager._plugins[PROVIDER]
            assert loaded.enabled and loaded.error is None, loaded.error
        yield SimpleNamespace(
            app=native_audio_gateway.app,
            store=native_audio_gateway.store,
            launch=launch,
            profile=profile,
            isolation=isolation,
        )
    finally:
        with grant_home_scope({"profile_id": str(profile)}):
            if manager is not None:
                manager.unload()
                if isolation == "host":
                    manager._plugin_host().shutdown()
        assert not (launch / "audio-calls.jsonl").exists()


def assert_refused(sent):
    (message,) = sent
    assert message["type"] == "websocket.close" and message["code"] == 4401


def admitted_frames(native_audio, path, frames):
    ticket = native_audio.store.mint(
        profile_id=str(native_audio.profile), subject="fixture-desktop", purpose="interactive"
    )
    sent = audio_messages(native_audio.app, path, frames, ticket=ticket)
    assert sent[0]["type"] == "websocket.accept" and sent[0]["subprotocol"] == PROTOCOL
    assert sent[-1]["type"] == "websocket.close" and sent[-1]["code"] == 1000
    assert ticket not in repr(sent)
    calls_path = native_audio.profile / "audio-calls.jsonl"
    recorded = calls_path.read_bytes()
    for denied_ticket in (None, ticket):
        assert_refused(audio_messages(native_audio.app, path, frames, ticket=denied_ticket))
        assert calls_path.read_bytes() == recorded
    calls = [json.loads(line) for line in recorded.splitlines()]
    for call in calls:
        assert call.pop("home") == str(native_audio.profile)
        assert call.pop("marker") == "target"
        assert (call.pop("pid") == os.getpid()) is (native_audio.isolation == "in_process")
    payloads = [json.loads(m["text"]) if "text" in m else m["bytes"] for m in sent[1:-1]]
    return payloads, calls


def test_native_audio_transcribes_synthetic_pcm_in_ticket_profile(native_audio):
    payloads, calls = admitted_frames(native_audio, TRANSCRIBE, TRANSCRIBE_FRAMES)
    assert payloads == [{"type": "final", "transcript": "synthetic final", "provider": PROVIDER}]
    assert calls == [
        {"stage": "asr-open", "language": "en", "prompt": "fixture prompt"},
        {"stage": "asr-finalize", "pcm": "01000200"},
    ]


@pytest.mark.parametrize("native_audio", ["in_process", "host"], indirect=True)
def test_native_audio_speech_pcm_or_host_fallback_in_ticket_profile(native_audio, caplog):
    payloads, calls = admitted_frames(
        native_audio,
        SPEAK,
        [{"type": "websocket.receive", "text": json.dumps({"text": SENTENCE, "done": True})}],
    )
    expected_calls = [
        {"stage": "tts-resolve"},
        {
            "stage": "tts-open",
            "text": SENTENCE,
            "voice": "fixture-voice",
            "model": "fixture-model",
            "format": "pcm",
            "speed": 1.25,
        },
    ]
    if native_audio.isolation == "in_process":
        assert payloads == [
            {"type": "start", "sample_rate": 22050, "channels": 1},
            b"\x01\x00",
            b"\x02\x00\x03\x00",
            {"type": "end"},
        ]
        expected_calls.append({"stage": "tts-iterate"})
    else:
        assert payloads == [{"type": "fallback"}]
        assert "Opaque" in caplog.text
    assert calls == expected_calls


@pytest.mark.parametrize(
    ("purpose", "query", "origin"),
    [
        ("native-http", b"", None),
        ("interactive", b"profile=default", None),
        ("interactive", b"", b"http://127.0.0.1:8765"),
    ],
    ids=["wrong-purpose", "other-profile", "origin"],
)
def test_native_audio_refuses_inapplicable_local_ticket(native_audio, purpose, query, origin):
    if query:
        from hermes_cli.web_server_profiles import _resolve_profile_dir

        assert _resolve_profile_dir("default") == native_audio.launch
    ticket = native_audio.store.mint(
        profile_id=str(native_audio.profile), subject="fixture-desktop", purpose=purpose
    )
    sent = audio_messages(
        native_audio.app,
        TRANSCRIBE,
        TRANSCRIBE_FRAMES,
        ticket=ticket,
        query=query,
        origin=origin,
    )
    assert_refused(sent)
    assert not (native_audio.profile / "audio-calls.jsonl").exists()
