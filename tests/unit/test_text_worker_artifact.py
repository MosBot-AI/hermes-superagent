"""Review-bundle integrity only. Do not execute or apply the proposed host patch."""

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "experiments/text-worker"
SHA = "35ef9ac9089437fc4e82ac5e3e52fe7150f0a5bb421e02b396c840855a07eec2"
BASE = "90d6b98fd86d20981ee06ddd5b7d93e4320f26a4"


def manifest():
    return json.loads((ARTIFACT / "manifest.json").read_text())


def runner():
    spec = importlib.util.spec_from_file_location("text_worker_runner", ARTIFACT / "run_tests.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_exact_patch_and_source_inventory():
    data = manifest()
    patch = (ARTIFACT / data["patch_file"]).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == data["patch_sha256"] == SHA
    assert data["base"] == BASE
    assert re.findall(r"^diff --git a/(\S+) b/\S+$", patch.decode(), re.M) == data["patch_files"]
    assert len(data["patch_files"]) == data["changed_files"]
    assert sorted(data["artifact_files"]) == sorted(
        p.name for p in ARTIFACT.iterdir() if p.is_file()
    )
    assert set(data["source_hashes"]) == {
        "consumer.py",
        "worker_ledger.py",
        "worker_presentation.py",
        "test_task_worker.py",
    }
    for name, digest in data["source_hashes"].items():
        assert hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest() == digest


def test_release_scope_and_license():
    data = manifest()
    assert data["installed_or_runtime_integrated"] is False
    assert data["submitted_upstream"] is False
    assert data["real_provider_or_model_tested"] is False
    assert data["restricted_gateway_sockets_retried"] is False
    assert data["selected_suite"]["failed"] == data["selected_suite"]["skipped"] == 0
    assert data["selected_suite"]["full_upstream_suite"] is False
    assert data["environment"]["lock_environment_equivalence_attested"] is False
    assert "Copyright (c) 2025 Nous Research" in (ARTIFACT / "LICENSE.hermes-agent").read_text()
    for name in ("__init__.py", "plugin.yaml", "personal_agent/plugin.py"):
        assert "launch_text" not in (ROOT / name).read_text()
        assert "personal_task_plan_preview" not in (ROOT / name).read_text()


def test_runner_requires_disposable_acknowledgement(tmp_path):
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
    assert result.returncode == 2 and "--disposable-copy" in result.stderr


@pytest.mark.parametrize(
    "answers,reason",
    [
        ([b"other-base"], "exact base"),
        ([BASE.encode(), b"h hidden.py\0"], "index flags"),
        ([BASE.encode(), b"S hidden.py\0"], "index flags"),
        ([BASE.encode(), b"H file.py\0", b"dirty.py"], "Unstaged"),
        ([BASE.encode(), b"H file.py\0", b"", b"untracked.py"], "Untracked"),
        ([BASE.encode(), b"H file.py\0", b"", b"", b"changed patch"], "exactly equal"),
    ],
)
def test_runner_refuses_altered_checkouts(monkeypatch, tmp_path, answers, reason):
    module = runner()
    responses = iter(answers)
    monkeypatch.setattr(module, "git", lambda *args: next(responses))
    with pytest.raises(ValueError, match=reason):
        module.verify(tmp_path)


def test_runner_accepts_exact_staged_bundle(monkeypatch, tmp_path):
    module = runner()
    data = manifest()
    responses = iter(
        [BASE.encode(), b"H file.py\0", b"", b"", (ARTIFACT / data["patch_file"]).read_bytes()]
    )
    monkeypatch.setattr(module, "git", lambda *args: next(responses))
    assert module.verify(tmp_path) == data


def test_runner_canonical_offline_selection():
    source = (ARTIFACT / "run_tests.py").read_text()
    assert '"scripts/run_tests.sh"' in source
    assert '"HERMES_RUNTIME_DIR": str(Path(home) / "runtime")' in source
    assert '"__HERMES_TESTS_REEXEC": "1"' in source
    assert 'str(ARTIFACT / "test_task_worker.py")' in source
    assert all("gateway" not in path for path in manifest()["portable_test_files"])
