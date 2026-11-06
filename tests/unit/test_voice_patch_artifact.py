"""Offline packaging checks; never apply or execute the upstream voice patch."""

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ARTIFACT = Path(__file__).resolve().parents[2] / "experiments" / "voice-ipc"
SHA = "3e49d2993c9d1eadc7cf3c65e3f0ba0e63a750040f2ef757db7dd4a93330d2df"


def manifest():
    return json.loads((ARTIFACT / "manifest.json").read_text())


def test_patch_checksum_and_file_inventory():
    data = manifest()
    patch = (ARTIFACT / data["patch_file"]).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == data["patch_sha256"] == SHA
    actual = re.findall(r"^diff --git a/(\S+) b/\S+$", patch.decode(), re.M)
    assert actual == data["patch_files"]
    assert len(actual) == data["changed_files"] == 7
    assert sorted(data["artifact_files"]) == sorted(
        item.name for item in ARTIFACT.iterdir() if item.is_file()
    )


def test_bilingual_docs_and_license():
    assert "[简体中文](README-zh.md)" in (ARTIFACT / "README.md").read_text()
    assert "[English](README.md)" in (ARTIFACT / "README-zh.md").read_text()
    for name in ("README.md", "README-zh.md"):
        text = (ARTIFACT / name).read_text()
        assert SHA in text
        assert "--disposable-copy --check-only" in text
        assert "Opaque" in text
        assert "/workspace/shared/" not in text
    license_text = (ARTIFACT / "LICENSE.hermes-agent").read_text()
    assert "MIT License" in license_text
    assert "Copyright (c) 2025 Nous Research" in license_text


def test_historical_results_and_safe_selection():
    data = manifest()
    suite = data["selected_suite"]
    assert suite["historical"] is True
    assert (suite["passed"], suite["skipped_modules"], suite["files"]) == (120, 1, 13)
    assert len(suite["test_files"]) == len(set(suite["test_files"])) == 13
    assert "tests/tools/test_transcription_streaming.py" not in suite["test_files"]
    assert "tests/tools/test_tts_streaming.py" in suite["test_files"]
    assert len(data["portable_test_files"]) == 12
    assert set(data["portable_test_files"]) == set(suite["test_files"]) - {
        "tests/tools/test_tts_streaming.py"
    }
    assert "tests/tools/test_transcription_streaming.py" not in data["portable_test_files"]
    assert data["final_focused_suite"]["passed"] == 17
    assert data["static_checks"]["passed"] == 14
    assert data["submitted_upstream"] is False
    assert data["installed_or_runtime_integrated"] is False
    assert data["environment"]["lock_environment_equivalence_attested"] is False


def test_runner_requires_explicit_disposable_acknowledgement(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ARTIFACT / "run_tests.py"),
            "--checkout",
            str(tmp_path),
            "--python",
            sys.executable,
            "--check-only",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--disposable-copy" in result.stderr


def test_runner_rejects_wrong_base_before_test_execution(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "voice_artifact_runner", ARTIFACT / "run_tests.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "git", lambda *_args: b"wrong-base\n")
    with pytest.raises(ValueError, match="exact base"):
        runner.verify(tmp_path)


def test_runner_rejects_unstaged_and_changed_patch(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "voice_artifact_runner", ARTIFACT / "run_tests.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    answers = iter([runner.BASE.encode(), b"H tracked.py\0", b"changed.py\n"])
    monkeypatch.setattr(runner, "git", lambda *_args: next(answers))
    with pytest.raises(ValueError, match="Unstaged"):
        runner.verify(tmp_path)
    answers = iter([runner.BASE.encode(), b"H tracked.py\0", b"", b"", b"different patch"])
    with pytest.raises(ValueError, match="exactly equal"):
        runner.verify(tmp_path)


def test_runner_accepts_only_exact_staged_patch(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "voice_artifact_runner", ARTIFACT / "run_tests.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    data = manifest()
    patch = (ARTIFACT / data["patch_file"]).read_bytes()
    answers = iter([runner.BASE.encode(), b"H tracked.py\0", b"", b"", patch])
    monkeypatch.setattr(runner, "git", lambda *_args: next(answers))
    assert runner.verify(tmp_path) == data
    answers = iter([runner.BASE.encode(), b"H tracked.py\0", b"", b"untracked.py\n"])
    with pytest.raises(ValueError, match="Untracked"):
        runner.verify(tmp_path)


def test_runner_uses_canonical_entry_with_fail_closed_environment():
    source = (ARTIFACT / "run_tests.py").read_text()
    assert '"scripts/run_tests.sh"' in source
    assert "run_tests_parallel.py" not in source
    assert '"__HERMES_TESTS_REEXEC": "1"' in source
    assert '"HERMES_PYTHON": str(interpreter)' in source
    assert '"HERMES_RUNTIME_DIR": str(Path(home) / "runtime")' in source
    assert '*manifest["portable_test_files"]' in source


@pytest.mark.parametrize("entry", [b"h hidden.py\0", b"S hidden.py\0"])
def test_runner_rejects_hidden_index_flags_before_diff(monkeypatch, tmp_path, entry):
    spec = importlib.util.spec_from_file_location(
        "voice_artifact_runner", ARTIFACT / "run_tests.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    calls = []

    def fake_git(_checkout, *args):
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return runner.BASE.encode()
        assert args == ("ls-files", "-v", "-z")
        return entry

    monkeypatch.setattr(runner, "git", fake_git)
    with pytest.raises(ValueError, match="index flags"):
        runner.verify(tmp_path)
    assert calls == [("rev-parse", "HEAD"), ("ls-files", "-v", "-z")]


def test_numpy_supplement_preserves_historical_evidence_and_runtime_boundary():
    data = manifest()
    supplement = data["numpy_tts_follow_up"]
    assert data["selected_suite"]["skipped_modules"] == 1
    assert supplement["test_results"]["passed"] == 44
    assert supplement["test_results"]["skipped"] == supplement["test_results"]["failed"] == 0
    assert supplement["original_environment_package_fingerprint_unchanged"] is True
    assert supplement["pyproject_unchanged"] is supplement["uv_lock_unchanged"] is True
    assert supplement["package_changes"]["added"] == {
        "numpy": "2.5.4",
        "sounddevice": "0.5.6",
    }
    assert data["installed_or_runtime_integrated"] is False
