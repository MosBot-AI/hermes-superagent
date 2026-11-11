"""Retained-source repack qualification and negative controls on synthetic stores."""

import sqlite3

import pytest

from acceptance.memory import retained
from personal_agent.memory_backend import MemoryError


def test_mixed_provenance_repack_and_interrupted_recovery(tmp_path):
    report = retained.run_retained_repack_acceptance(tmp_path)
    assert report["passed"]
    assert report["fresh_process_reopens"] == 2
    assert report["interrupted_cutovers"] == 1
    assert report["decisions_per_profile"] == 8
    assert "Synthetic source marker" not in str(report)


def test_fixture_has_explicit_migrated_and_observed_obligations(tmp_path):
    expected = retained._prepare(tmp_path / "home")
    for request, status, cursor in zip(
        retained._requests(), expected["statuses"], expected["cursors"], strict=True
    ):
        state = request["request_id"].rsplit("-", 1)[1]
        decision = status["decision"]
        assert status["state"] == "found"
        assert decision["source_sequence"] == 1
        source = dict(request["source"])
        source.setdefault("kind", "retained_native_snapshot")
        assert decision["source"] == source
        assert decision["state"] == ("accepted" if state in {"corrected", "forgotten"} else state)
        assert status["suppressed"] == (state != "pending")
        assert cursor["through_sequence"] == (0 if state == "pending" else 1)
        assert cursor["pending"] == (decision if state == "pending" else None)
        if state in {"corrected", "forgotten"}:
            assert decision["record"]["revision"] == 1
            assert decision["record"]["status"] == "active"
            assert status["current"]["revision"] == 2
            assert status["current"]["status"] == (
                "forgotten" if state == "forgotten" else "active"
            )
        else:
            assert decision["record"] is None
            assert status["current"] is None


@pytest.mark.parametrize(
    "damage",
    [
        "DELETE FROM retained_source_decisions WHERE state='pending'",
        "UPDATE retained_source_decisions SET source_observation='" + "a" * 64 + "' "
        "WHERE source_kind='observed_native_snapshot' AND state='pending'",
        "UPDATE retained_source_decisions SET suppressed=0 WHERE state='discarded'",
        "DELETE FROM receipts",
        "UPDATE records SET content='Silently damaged corrected payload' WHERE status='active'",
        "DELETE FROM events WHERE revision=2",
    ],
)
def test_explicit_snapshot_detects_dropped_or_changed_evidence(tmp_path, damage):
    home = tmp_path / "home"
    expected = retained._prepare(home)
    with sqlite3.connect(retained._path(home)) as connection:
        connection.execute(damage)
    with pytest.raises((AssertionError, MemoryError)):
        retained._verify(home, expected)


def test_admission_check_detects_silent_success():
    class BrokenSDK:
        def execute(self, operation, request):
            return {"data": {}, "replayed": False}

    with pytest.raises(AssertionError, match="unsafe source admission"):
        retained._refuses(BrokenSDK(), {}, "source_suppressed")


def test_behavioral_probe_detects_lost_suppression_protection(tmp_path, monkeypatch):
    from personal_agent import retained_sources

    home = tmp_path / "home"
    expected = retained._prepare(home)
    monkeypatch.setattr(retained_sources, "_check_suppression", lambda *_: None)
    with pytest.raises(AssertionError, match="unsafe source admission"):
        retained._verify(home, expected)


def test_child_environment_excludes_parent_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_PROVIDER_API_KEY", "synthetic-do-not-inherit")
    calls = []
    monkeypatch.setattr(retained.subprocess, "run", lambda *a, **kw: calls.append(kw))
    retained._process(tmp_path, "verify", {})
    assert set(calls[0]["env"]) == {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "PYTHONPATH"}
    assert calls[0]["env"]["HOME"] == str(tmp_path)


def test_child_denies_network_before_verification(tmp_path, monkeypatch):
    # Patch attributes first so pytest restores process-wide socket functions afterward.
    for owner, attribute in (
        (retained.socket, "create_connection"),
        (retained.socket.socket, "connect"),
        (retained.socket.socket, "connect_ex"),
    ):
        monkeypatch.setattr(owner, attribute, getattr(owner, attribute))
    monkeypatch.setattr(retained, "_verify", lambda *_: None)
    retained._child(tmp_path, "verify", {})
    with pytest.raises(AssertionError, match="forbids network"):
        retained.socket.create_connection(("synthetic.invalid", 443))
