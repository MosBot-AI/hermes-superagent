"""Pinned recorder and RMS detector contracts with fabricated PCM and a fake input stream."""

import math
import os
import socket
import struct
import time
import wave
from itertools import chain
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

DEVICE_RATE = 24000
BLOCK_FRAMES = DEVICE_RATE // 8


class PCM(tuple):
    """Test-only array operations used by the host's RMS and WAV code."""

    def copy(self):
        return PCM(self)

    def astype(self, dtype):
        return PCM(map(dtype, self))

    def __pow__(self, exponent):
        return PCM(value**exponent for value in self)

    def tobytes(self):
        return struct.pack(f"<{len(self)}h", *self)


@pytest.fixture
def isolated_voice_home(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        '{"stt": {"enabled": false, "streaming": false}}', encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("HERMES_VOICE_DEBUG", raising=False)

    import pm

    def deny(*args, **kwargs):
        pytest.fail("The synthetic capture must not open a socket or install audio packages")

    monkeypatch.setattr(pm, "ensure_import", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    for method in ("bind", "listen", "connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, method, deny)
    return home


@pytest.fixture
def capture(isolated_voice_home, tmp_path, monkeypatch):
    from tools import transcription_streaming, voice_mode

    def deny_live(*args, **kwargs):
        pytest.fail("The recorder fixture config disables live transcription")

    monkeypatch.setattr(transcription_streaming, "_builtin_session", deny_live)
    monkeypatch.setattr(transcription_streaming, "_plugin_session", deny_live)
    streams = []
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(
        voice_mode, "time", SimpleNamespace(monotonic=lambda: clock.now, strftime=time.strftime)
    )
    recordings = tmp_path / "recordings"
    monkeypatch.setattr(voice_mode, "_TEMP_DIR", str(recordings))

    class InputStream:
        def __init__(self, *, samplerate, channels, dtype, callback):
            assert (samplerate, channels, dtype) == (DEVICE_RATE, 1, "int16")
            self.callback = callback
            self.active = False
            self.closed = False
            streams.append(self)

        def start(self):
            self.active = True

        def stop(self):
            self.active = False

        def close(self):
            self.closed = True

    def concatenate(frames, axis):
        assert axis == 0
        return PCM(chain.from_iterable(frames))

    numeric = SimpleNamespace(
        float64=float,
        sqrt=math.sqrt,
        mean=lambda values: math.fsum(values) / len(values),
        concatenate=concatenate,
    )
    device = SimpleNamespace(
        InputStream=InputStream, query_devices=lambda *args: {"default_samplerate": DEVICE_RATE}
    )
    monkeypatch.setattr(voice_mode, "_import_audio", lambda: (device, numeric))
    recorder = voice_mode.AudioRecorder()
    stopped = Event()

    def feed(sample):
        clock.now += 0.125
        streams[0].callback(PCM((sample,) * BLOCK_FRAMES), BLOCK_FRAMES, None, None)

    try:
        recorder.start(on_silence_stop=stopped.set)
        yield SimpleNamespace(
            home=isolated_voice_home,
            recorder=recorder,
            feed=feed,
            stopped=stopped,
            recordings=recordings,
            stream=streams[0],
        )
    finally:
        recorder.shutdown()
    assert len(streams) == 1 and not streams[0].active and streams[0].closed


def test_speech_then_silence_requests_stop_and_writes_device_rate_wav(capture):
    from tools.voice_mode import cleanup_temp_recordings

    for _ in range(4):
        capture.feed(1200)
    assert capture.recorder.current_rms == 1200
    for _ in range(24):
        capture.feed(0)
    assert capture.recorder.current_rms == 0
    assert capture.recorder._on_silence_stop is not None
    assert not capture.stopped.is_set()
    capture.feed(0)
    assert capture.stopped.wait(2)
    assert capture.recorder._on_silence_stop is None
    assert capture.recorder.is_recording  # The endpoint notifies the caller, which stops capture.

    wav_path = capture.recorder.stop()
    assert wav_path is not None and Path(wav_path).parent == capture.recordings
    assert not capture.recorder.is_recording and capture.stream.active
    with wave.open(wav_path, "rb") as recorded:
        assert (recorded.getframerate(), recorded.getnchannels(), recorded.getsampwidth()) == (
            DEVICE_RATE,
            1,
            2,
        )
        assert recorded.getnframes() == 29 * BLOCK_FRAMES
        assert recorded.readframes(29 * BLOCK_FRAMES) == (
            struct.pack("<h", 1200) * (4 * BLOCK_FRAMES) + bytes(2 * 25 * BLOCK_FRAMES)
        )
    old_time = time.time() - 120
    os.utime(wav_path, (old_time, old_time))
    assert cleanup_temp_recordings(max_age_seconds=60) == 1
    assert not Path(wav_path).exists()


def test_short_loud_capture_leaves_no_wav_or_endpoint_notification(capture):
    capture.feed(1200)
    assert capture.recorder.current_rms == 1200
    assert capture.recorder._on_silence_stop is not None
    assert capture.recorder.stop() is None
    assert not capture.recorder.is_recording and capture.stream.active
    assert not capture.stopped.is_set()
    assert list(capture.recordings.glob("*.wav")) == []


def test_playback_barge_detector_waits_past_grace_and_rejects_bleed(isolated_voice_home):
    from tools.voice_mode import _BargeDetector

    def percentile(values, quantile):
        assert quantile == 90
        # Every sample in the quiet calibration window has the same RMS.
        assert set(values) == {100}
        return 100

    detector = _BargeDetector(
        SimpleNamespace(percentile=percentile),
        mult=3,
        calib_blocks=4,
        trip_blocks=5,
        grace_blocks=4,
    )
    for _ in range(4):
        assert detector.feed(100, playing=False) is None
    for _ in range(4):
        assert detector.feed(5000, playing=True) is None  # Playback onset grace.
    for _ in range(6):
        assert detector.feed(1000, playing=True) is None  # Above generation floor, below playback.
    for _ in range(3):
        assert detector.feed(5000, playing=True) is None
    assert detector.feed(5000, playing=True) == "playback"
