"""Synthetic voice contract checks, never a live voice certification."""

import json

import pytest

from personal_agent.voice import (
    SyntheticVoiceAdapter,
    VoiceSimulationError,
    _fixture,
    run_voice_self_test,
    simulation_config,
)


def adapter(**changes):
    return SyntheticVoiceAdapter({**simulation_config(), **changes})


def rejects(code, operation):
    with pytest.raises(VoiceSimulationError, match=f"^{code}$"):
        operation()


def test_self_test_is_deterministic_bounded_and_content_free():
    report = run_voice_self_test()
    assert report == run_voice_self_test()
    assert report["status"] == "ok"
    assert report["simulation"] is True
    assert report["live_voice_enabled"] is False
    assert report["microphone_used"] is False
    assert report["provider_calls"] == report["native_turns_submitted"] == 0
    assert all(item["passed"] is True for item in report["checks"])
    assert len(report["checks"]) == 23
    encoded = json.dumps(report)
    assert len(encoded) < 4096
    assert "payload" not in encoded


@pytest.mark.parametrize("config", [None, [], {}, {**simulation_config(), "endpoint": "secret"}])
def test_exact_config_fields(config):
    rejects("invalid_fields", lambda: SyntheticVoiceAdapter(config))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "personal.voice.profile.v1"),
        ("encoding", "opus"),
        ("sample_rate_hz", 24000),
        ("sample_rate_hz", 16000.0),
        ("channels", True),
        ("channels", 2),
        ("turn_detection", "manual"),
    ],
)
def test_no_capability_fallback(field, value):
    rejects("capability_unavailable", lambda: adapter(**{field: value}))


@pytest.mark.parametrize("value", [True, 20.0, "20", 0, 9, 61, None])
def test_frame_duration_is_strict(value):
    rejects("invalid_frame_duration", lambda: adapter(frame_ms=value))


@pytest.mark.parametrize("value", [True, 100.0, 19, 501, None])
def test_queue_duration_is_bounded(value):
    rejects("invalid_queue_duration", lambda: adapter(queue_ms=value))


@pytest.mark.parametrize("duration", [10, 20, 37, 60])
def test_supported_durations_and_capacity(duration):
    instance = adapter(frame_ms=duration, queue_ms=500)
    capacity = 500 // duration
    assert instance.snapshot()["queue_capacity_frames"] == capacity
    for sequence in range(capacity):
        assert instance.append_input(*_fixture(sequence=sequence, frame_ms=duration)) == "accepted"
    rejects(
        "queue_overflow",
        lambda: instance.append_input(*_fixture(sequence=capacity, frame_ms=duration)),
    )
    assert instance.snapshot()["input_queued_frames"] == 0
    assert instance.snapshot()["input_recovery_required"] is True
    rejects("input_recovery_required", lambda: instance.append_input(*_fixture(frame_ms=duration)))


@pytest.mark.parametrize("field", ["stream_epoch", "output_generation", "sequence", "timestamp_us"])
@pytest.mark.parametrize("value", [True, 0.0, -1, 2**63, None, "0"])
def test_strict_frame_counters(field, value):
    instance = adapter()
    metadata, payload = _fixture()
    rejects(
        "invalid_frame_integer", lambda: instance.append_input({**metadata, field: value}, payload)
    )
    assert instance.snapshot()["input_queued_frames"] == 0


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("schema_version", "v2", "unsupported_frame_version"),
        ("encoding", "pcm_s16be", "frame_format_mismatch"),
        ("sample_rate_hz", 16000.0, "frame_format_mismatch"),
        ("channels", True, "frame_format_mismatch"),
        ("sample_count", True, "frame_duration_mismatch"),
        ("sample_count", 321, "frame_duration_mismatch"),
        ("payload_bytes", True, "payload_alignment_mismatch"),
        ("payload_bytes", 639, "payload_alignment_mismatch"),
    ],
)
def test_frame_metadata(field, value, code):
    instance = adapter()
    metadata, payload = _fixture()
    rejects(code, lambda: instance.append_input({**metadata, field: value}, payload))


@pytest.mark.parametrize(
    "payload", [None, [], bytearray(640), bytes(639), bytes(641), bytes(65537)]
)
def test_payload_is_exact_immutable_aligned_bytes(payload):
    metadata, _ = _fixture()
    rejects("payload_alignment_mismatch", lambda: adapter().append_input(metadata, payload))


def test_real_audio_is_not_a_supported_input():
    metadata, payload = _fixture()
    rejects("non_synthetic_payload", lambda: adapter().append_input(metadata, b"x" + payload[1:]))


def test_unknown_or_missing_frame_fields():
    metadata, payload = _fixture()
    rejects(
        "invalid_fields", lambda: adapter().append_input({**metadata, "text": "secret"}, payload)
    )
    del metadata["channels"]
    rejects("invalid_fields", lambda: adapter().append_input(metadata, payload))


def test_duplicate_window_is_one_frame_and_retry_does_not_allocate():
    instance = adapter()
    metadata, payload = _fixture()
    instance.append_input(metadata, payload)
    for _ in range(100):
        assert instance.append_input(metadata, payload) == "duplicate"
    assert instance.snapshot()["input_queued_frames"] == 1
    rejects(
        "conflicting_or_expired_duplicate",
        lambda: instance.append_input({**metadata, "timestamp_us": 1}, payload),
    )
    instance.append_input(*_fixture(sequence=1))
    rejects("conflicting_or_expired_duplicate", lambda: instance.append_input(metadata, payload))
    assert instance.drain_fixture("input") == 2
    assert instance.append_input(*_fixture(sequence=1)) == "duplicate"
    assert instance.snapshot()["input_queued_frames"] == 0


@pytest.mark.parametrize("field,value", [("sequence", 1), ("timestamp_us", 1)])
def test_initial_gap_requires_explicit_recovery(field, value):
    instance = adapter()
    metadata, payload = _fixture()
    rejects("audio_gap", lambda: instance.append_input({**metadata, field: value}, payload))
    rejects("input_recovery_required", lambda: instance.append_input(metadata, payload))
    assert instance.recover(0) == "new_simulation_epoch"
    snapshot = instance.snapshot()
    assert instance.recover(0) == "already_recovered"
    assert instance.snapshot() == snapshot
    rejects("stale_epoch", lambda: instance.append_input(metadata, payload))
    assert instance.append_input(*_fixture(epoch=1)) == "accepted"
    rejects("stale_generation", lambda: instance.append_output(*_fixture(epoch=1)))
    assert instance.append_output(*_fixture(epoch=1, generation=1)) == "accepted"


def test_output_interruption_does_not_cancel_native_work():
    instance = adapter()
    instance.append_input(*_fixture())
    instance.append_output(*_fixture())
    assert instance.interrupt_native_work() == "unsupported"
    assert instance.interrupt_output(0) == "simulation_output_stopped"
    assert instance.snapshot()["input_queued_frames"] == 1
    assert instance.snapshot()["output_queued_frames"] == 0
    assert instance.interrupt_output(0) == "already_interrupted"
    rejects("stale_generation", lambda: instance.append_output(*_fixture()))
    instance.append_output(*_fixture(generation=1))
    assert instance.interrupt_output(0) == "already_interrupted"
    assert instance.snapshot()["output_queued_frames"] == 1
    assert instance.interrupt_output(1) == "simulation_output_stopped"
    rejects("stale_generation", lambda: instance.interrupt_output(0))


def test_recovery_and_gap_do_not_fabricate_interrupt_receipts():
    instance = adapter()
    instance.recover(0)
    rejects("stale_generation", lambda: instance.interrupt_output(0))
    rejects(
        "audio_gap", lambda: instance.append_output(*_fixture(epoch=1, generation=1, sequence=2))
    )
    rejects("stale_generation", lambda: instance.interrupt_output(1))
    assert instance.append_output(*_fixture(epoch=1, generation=2)) == "accepted"


def test_output_overflow_flushes_and_fences_generation():
    instance = adapter(queue_ms=20)
    instance.append_output(*_fixture())
    rejects("queue_overflow", lambda: instance.append_output(*_fixture(sequence=1)))
    assert instance.snapshot()["output_queued_frames"] == 0
    rejects("stale_generation", lambda: instance.append_output(*_fixture()))
    assert instance.append_output(*_fixture(generation=1)) == "accepted"


@pytest.mark.parametrize("value", [True, -1, 0.0, 2**63, "0"])
def test_control_counter_types(value):
    instance = adapter()
    rejects("invalid_epoch", lambda: instance.recover(value))
    rejects("invalid_generation", lambda: instance.interrupt_output(value))


def test_close_is_terminal_idempotent_and_releases_data():
    instance = adapter()
    instance.append_input(*_fixture())
    instance.append_output(*_fixture())
    assert instance.close() == "simulation_closed"
    snapshot = instance.snapshot()
    assert instance.close() == "already_closed"
    assert instance.snapshot() == snapshot
    assert snapshot["input_queued_frames"] == snapshot["output_queued_frames"] == 0
    for operation in [
        lambda: instance.append_input(*_fixture()),
        lambda: instance.append_output(*_fixture()),
        lambda: instance.interrupt_output(0),
        lambda: instance.recover(0),
        lambda: instance.drain_fixture("input"),
    ]:
        rejects("closed", operation)
    assert instance.interrupt_native_work() == "unsupported"


def test_counter_exhaustion_is_terminal():
    instance = adapter()
    instance._generation = 2**63 - 1
    rejects("counter_exhausted", lambda: instance.interrupt_output(2**63 - 1))
    assert instance.snapshot()["closed"] is True
    instance = adapter()
    instance._epoch = 2**63 - 1
    rejects("counter_exhausted", lambda: instance.recover(2**63 - 1))
    assert instance.snapshot()["closed"] is True


def test_snapshots_and_capabilities_do_not_mutate_adapter():
    instance = adapter()
    instance.snapshot()["closed"] = True
    instance.describe()["asr"] = True
    assert instance.snapshot()["closed"] is False
    assert instance.describe()["asr"] is False
    rejects("invalid_direction", lambda: instance.drain_fixture("anything"))
