"""Offline synthetic media invariants, not a production voice provider or auth boundary.

No capture, playback, ASR, TTS, provider calls, persistence or native turns occur.
Only zero-valued PCM fixtures are admitted. Python objects are not trusted contexts.
"""

from collections import deque
from dataclasses import dataclass
from typing import Any, Never, cast

_CONFIG_VERSION = "personal.voice.simulation-config.v1"
_FRAME_VERSION = "personal.voice.simulation-frame.v1"
_MAX_COUNTER = 2**63 - 1


class VoiceSimulationError(ValueError):
    """Bounded error code; never includes submitted data."""


def _reject(code: str) -> Never:
    raise VoiceSimulationError(code)


def _integer(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _fields(value: object, expected: set[str]) -> dict[str, Any]:
    if type(value) is not dict or value.keys() != expected:
        _reject("invalid_fields")
    return cast(dict[str, Any], value)


def _literal(value: object, expected: str | int) -> bool:
    return type(value) is type(expected) and value == expected


def simulation_config() -> dict[str, object]:
    """Return a fresh, exact supported config, with no provider/endpoint options."""
    return {
        "schema_version": _CONFIG_VERSION,
        "encoding": "pcm_s16le",
        "sample_rate_hz": 16000,
        "channels": 1,
        "frame_ms": 20,
        "queue_ms": 100,
        "turn_detection": "none",
    }


@dataclass(frozen=True, slots=True)
class _Frame:
    epoch: int
    generation: int
    sequence: int
    timestamp_us: int
    sample_count: int
    payload: bytes


class SyntheticVoiceAdapter:
    """Single-threaded bounded fixture state machine, never registered as a provider.

    Duplicate recognition covers only the latest accepted frame in each direction.
    Gaps/overflow invalidate input until a new epoch; no incomplete input is committed.
    Recovery discards all fixture data and never resumes a provider or native turn.
    """

    def __init__(self, config: object) -> None:
        values = _fields(config, set(simulation_config()))
        for key, expected in simulation_config().items():
            if key in {"frame_ms", "queue_ms"}:
                continue
            if type(values[key]) is not type(expected) or values[key] != expected:
                _reject("capability_unavailable")
        if not _integer(values["frame_ms"], 10, 60):
            _reject("invalid_frame_duration")
        if not _integer(values["queue_ms"], values["frame_ms"], 500):
            _reject("invalid_queue_duration")
        self._frame_ms: int = values["frame_ms"]
        self._capacity: int = values["queue_ms"] // self._frame_ms
        self._epoch = 0
        self._generation = 0
        self._closed = False
        self._input_broken = False
        self._input: deque[_Frame] = deque()
        self._output: deque[_Frame] = deque()
        self._last_input: _Frame | None = None
        self._last_output: _Frame | None = None
        self._last_interrupt: int | None = None

    @staticmethod
    def describe() -> dict[str, object]:
        return {
            "schema_version": "personal.voice.simulation-capabilities.v1",
            "simulation_only": True,
            "encoding": "pcm_s16le",
            "sample_rate_hz": 16000,
            "channels": 1,
            "frame_ms_min": 10,
            "frame_ms_max": 60,
            "queue_ms_max": 500,
            "payload": "zero_pcm_fixture_only",
            "asr": False,
            "tts": False,
            "native_work": "unsupported",
            "provider_resume": False,
            "playback_accounting": "unsupported",
        }

    def snapshot(self) -> dict[str, object]:
        """Only bounded counters and state, never fixture data or user content."""
        return {
            "stream_epoch": self._epoch,
            "output_generation": self._generation,
            "closed": self._closed,
            "input_recovery_required": self._input_broken,
            "input_queued_frames": len(self._input),
            "output_queued_frames": len(self._output),
            "queue_capacity_frames": self._capacity,
            "native_work": "unsupported",
        }

    def _ready(self) -> None:
        if self._closed:
            _reject("closed")

    def _parse(self, metadata: object, payload: object) -> _Frame:
        values = _fields(
            metadata,
            {
                "schema_version",
                "stream_epoch",
                "output_generation",
                "sequence",
                "timestamp_us",
                "sample_count",
                "encoding",
                "sample_rate_hz",
                "channels",
                "payload_bytes",
            },
        )
        if not _literal(values["schema_version"], _FRAME_VERSION):
            _reject("unsupported_frame_version")
        for key in ("stream_epoch", "output_generation", "sequence", "timestamp_us"):
            if not _integer(values[key], 0, _MAX_COUNTER):
                _reject("invalid_frame_integer")
        for key, expected in (
            ("encoding", "pcm_s16le"),
            ("sample_rate_hz", 16000),
            ("channels", 1),
        ):
            if not _literal(values[key], expected):
                _reject("frame_format_mismatch")
        samples = self._frame_ms * 16
        if not _integer(values["sample_count"], samples, samples):
            _reject("frame_duration_mismatch")
        if not _integer(values["payload_bytes"], samples * 2, samples * 2):
            _reject("payload_alignment_mismatch")
        if type(payload) is not bytes or len(payload) != samples * 2:
            _reject("payload_alignment_mismatch")
        if any(payload):
            _reject("non_synthetic_payload")
        return _Frame(
            values["stream_epoch"],
            values["output_generation"],
            values["sequence"],
            values["timestamp_us"],
            samples,
            payload,
        )

    def append_input(self, metadata: object, payload: object) -> str:
        return self._append(metadata, payload, output=False)

    def append_output(self, metadata: object, payload: object) -> str:
        """Queue a zero fixture, not synthesized or authorized backend output."""
        return self._append(metadata, payload, output=True)

    def _append(self, metadata: object, payload: object, *, output: bool) -> str:
        self._ready()
        frame = self._parse(metadata, payload)
        if frame.epoch != self._epoch:
            _reject("stale_epoch")
        if frame.generation != (self._generation if output else 0):
            _reject("stale_generation")
        if not output and self._input_broken:
            _reject("input_recovery_required")
        last = self._last_output if output else self._last_input
        queue = self._output if output else self._input
        if last is not None and frame.sequence <= last.sequence:
            if frame == last:
                return "duplicate"
            _reject("conflicting_or_expired_duplicate")
        sequence = 0 if last is None else last.sequence + 1
        timestamp = 0 if last is None else last.timestamp_us + self._frame_ms * 1000
        if frame.sequence != sequence or frame.timestamp_us != timestamp:
            queue.clear()
            if not output:
                self._input_broken = True
            else:
                self._advance_generation()
            _reject("audio_gap")
        if len(queue) >= self._capacity:
            queue.clear()
            if not output:
                self._input_broken = True
            else:
                self._advance_generation()
            _reject("queue_overflow")
        queue.append(frame)
        if output:
            self._last_output = frame
        else:
            self._last_input = frame
        return "accepted"

    def drain_fixture(self, direction: str) -> int:
        """Discard queued fixtures; does not acknowledge real playback or input commit."""
        self._ready()
        if type(direction) is not str or direction not in {"input", "output"}:
            _reject("invalid_direction")
        queue = self._input if direction == "input" else self._output
        count = len(queue)
        queue.clear()
        return count

    def _advance_generation(self) -> None:
        if self._generation == _MAX_COUNTER:
            self.close()
            _reject("counter_exhausted")
        self._last_interrupt = None
        self._generation += 1
        self._output.clear()
        self._last_output = None

    def interrupt_output(self, expected_generation: object) -> str:
        self._ready()
        if not _integer(expected_generation, 0, _MAX_COUNTER):
            _reject("invalid_generation")
        if expected_generation == self._last_interrupt:
            return "already_interrupted"
        if expected_generation != self._generation:
            _reject("stale_generation")
        self._advance_generation()
        self._last_interrupt = self._generation - 1
        return "simulation_output_stopped"

    def interrupt_native_work(self) -> str:
        return "unsupported"

    def recover(self, expected_epoch: object) -> str:
        """Idempotent compare-and-advance; only the immediately prior retry is retained."""
        self._ready()
        if not _integer(expected_epoch, 0, _MAX_COUNTER):
            _reject("invalid_epoch")
        if expected_epoch == self._epoch - 1:
            return "already_recovered"
        if expected_epoch != self._epoch:
            _reject("stale_epoch")
        if self._epoch == _MAX_COUNTER:
            self.close()
            _reject("counter_exhausted")
        self._advance_generation()
        self._epoch += 1
        self._input.clear()
        self._last_input = None
        self._input_broken = False
        return "new_simulation_epoch"

    def close(self) -> str:
        if self._closed:
            return "already_closed"
        self._closed = True
        self._input.clear()
        self._output.clear()
        self._last_input = None
        self._last_output = None
        return "simulation_closed"


def _fixture(
    *, sequence: int = 0, epoch: int = 0, generation: int = 0, frame_ms: int = 20
) -> tuple[dict[str, object], bytes]:
    return (
        {
            "schema_version": _FRAME_VERSION,
            "stream_epoch": epoch,
            "output_generation": generation,
            "sequence": sequence,
            "timestamp_us": sequence * frame_ms * 1000,
            "sample_count": frame_ms * 16,
            "encoding": "pcm_s16le",
            "sample_rate_hz": 16000,
            "channels": 1,
            "payload_bytes": frame_ms * 32,
        },
        bytes(frame_ms * 32),
    )


def run_voice_self_test() -> dict[str, object]:
    """Deterministic bounded JSON diagnostics using only generated silent fixtures.

    Failure details are deliberately not serialized; no runtime feature is enabled.
    """
    checks: dict[str, bool] = {}

    def rejected(name: str, operation: Any, code: str) -> None:
        try:
            operation()
        except VoiceSimulationError as error:
            checks[name] = str(error) == code
        else:
            checks[name] = False

    adapter = SyntheticVoiceAdapter(simulation_config())
    frame, payload = _fixture()
    checks["synthetic_frame"] = adapter.append_input(frame, payload) == "accepted"
    checks["duplicate"] = adapter.append_input(frame, payload) == "duplicate"
    rejected(
        "unknown_config",
        lambda: SyntheticVoiceAdapter({**simulation_config(), "url": "x"}),
        "invalid_fields",
    )
    rejected(
        "unsupported_rate",
        lambda: SyntheticVoiceAdapter({**simulation_config(), "sample_rate_hz": 24000}),
        "capability_unavailable",
    )
    rejected(
        "strict_integer",
        lambda: adapter.append_input({**frame, "sequence": True}, payload),
        "invalid_frame_integer",
    )
    rejected(
        "alignment", lambda: adapter.append_input(frame, payload[:-1]), "payload_alignment_mismatch"
    )
    rejected(
        "zero_pcm_only",
        lambda: adapter.append_input(frame, payload[:-1] + b"\x01"),
        "non_synthetic_payload",
    )
    rejected(
        "duration",
        lambda: adapter.append_input({**frame, "sample_count": 1}, payload),
        "frame_duration_mismatch",
    )
    rejected("gap", lambda: adapter.append_input(*_fixture(sequence=2)), "audio_gap")
    checks["gap_flush"] = adapter.snapshot()["input_queued_frames"] == 0
    checks["recovery"] = adapter.recover(0) == "new_simulation_epoch"
    checks["recovery_retry"] = adapter.recover(0) == "already_recovered"
    rejected("epoch_fence", lambda: adapter.append_input(frame, payload), "stale_epoch")
    for sequence in range(5):
        adapter.append_input(*_fixture(sequence=sequence, epoch=1))
    rejected(
        "queue_bound",
        lambda: adapter.append_input(*_fixture(sequence=5, epoch=1)),
        "queue_overflow",
    )
    adapter.append_output(*_fixture(epoch=1, generation=1))
    checks["interrupt"] = adapter.interrupt_output(1) == "simulation_output_stopped"
    checks["interrupt_retry"] = adapter.interrupt_output(1) == "already_interrupted"
    checks["output_flush"] = adapter.snapshot()["output_queued_frames"] == 0
    rejected(
        "generation_fence",
        lambda: adapter.append_output(*_fixture(epoch=1, generation=1)),
        "stale_generation",
    )
    checks["native_work_unsupported"] = adapter.interrupt_native_work() == "unsupported"
    independent = SyntheticVoiceAdapter(simulation_config())
    independent.append_input(*_fixture())
    independent.append_output(*_fixture())
    independent.interrupt_output(0)
    checks["input_survives_output_interrupt"] = (
        independent.append_input(*_fixture(sequence=1)) == "accepted"
    )
    independent.close()
    checks["close"] = adapter.close() == "simulation_closed"
    checks["close_retry"] = adapter.close() == "already_closed"
    rejected("closed_fence", lambda: adapter.recover(1), "closed")
    return {
        "schema_version": "personal.voice.self-test.v1",
        "status": "ok" if all(checks.values()) else "failed",
        "simulation": True,
        "microphone_used": False,
        "provider_calls": 0,
        "native_turns_submitted": 0,
        "simulation_only": True,
        "live_voice_enabled": False,
        "native_work": "unsupported",
        "checks": [{"name": name, "passed": passed} for name, passed in checks.items()],
    }
