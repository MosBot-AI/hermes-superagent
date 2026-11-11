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
SHA = "7407e37482e44c95bbc7093ccf097cca30ca3351d253e9367905eb944cc279f8"
BASE = "2281116525106e3c109993ccb5dc74d02bfc1427"


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
        "test_production_entrypoint.py",
    }
    for name, digest in data["source_hashes"].items():
        assert hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest() == digest


def test_release_scope_and_license():
    data = manifest()
    assert data["installed_or_live_runtime_integrated"] is False
    assert data["submitted_upstream"] is False
    assert data["live_model_acceptance_passed"] is False
    assert data["restricted_gateway_sockets_retried"] is False
    assert data["selected_suite"]["failed"] == data["selected_suite"]["skipped"] == 0
    assert data["selected_suite"]["full_upstream_suite"] is False
    assert data["environment"]["lock_environment_equivalence_attested"] is False
    assert "Copyright (c) 2025 Nous Research" in (ARTIFACT / "LICENSE.hermes-agent").read_text()
    assert data["production_package_integration"] is True
    assert data["contract_marker"] == "hermes.text-worker.v1"
    for name, digest in data["production_source_hashes"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    assert "plan_worker" in (ROOT / "plugin.yaml").read_text()
    assert "plan_worker_host_status" in (ROOT / "personal_agent/plugin.py").read_text()


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
        [
            BASE.encode(),
            b"H file.py\0",
            b"",
            b"",
            (ARTIFACT / data["patch_file"]).read_bytes(),
            data["staged_tree"].encode(),
        ]
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


def test_historical_evidence_cannot_be_attributed_to_current_pin():
    data = manifest()
    historical = data["historical_evidence"]
    assert historical["base"] == "90d6b98fd86d20981ee06ddd5b7d93e4320f26a4"
    assert (
        historical["patch_sha256"]
        == "97e4acd85091f64e693185a195c9141bd5faa43a3c23896ba635564966e372d8"
    )
    assert (
        historical["source_hashes"]["test_production_entrypoint.py"]
        == "8fbe7112dcc13eb47d3291fae856d01ff0432e1d27ba39912cb8e9e8428104a0"
    )
    assert historical["selected_suite"]["passed"] == 357
    assert historical["production_entrypoint_suite"]["clean_host_passed"] == 4
    assert historical["live_transport_probe"]["acceptance_passed"] is False
    assert historical["official_install_attempt"]["override_or_retry"] is False
    assert "live_transport_probe" not in data and "official_install_attempt" not in data


def test_runner_refuses_wrong_staged_tree(monkeypatch, tmp_path):
    module = runner()
    data = manifest()
    responses = iter(
        [
            BASE.encode(),
            b"H file.py\0",
            b"",
            b"",
            (ARTIFACT / data["patch_file"]).read_bytes(),
            b"wrong-tree",
        ]
    )
    monkeypatch.setattr(module, "git", lambda *args: next(responses))
    with pytest.raises(ValueError, match="Staged tree"):
        module.verify(tmp_path)


@pytest.mark.parametrize(
    "answers,reason",
    [
        ([b"old-pin"], "exact current pin"),
        ([BASE.encode(), b"h hidden.py\0"], "index flags"),
        ([BASE.encode(), b"S hidden.py\0"], "index flags"),
        ([BASE.encode(), b"H file.py\0", b" M changed.py"], "changed or untracked"),
        ([BASE.encode(), b"H file.py\0", b"?? untracked.py"], "changed or untracked"),
    ],
)
def test_runner_refuses_dirty_clean_host(monkeypatch, tmp_path, answers, reason):
    module = runner()
    responses = iter(answers)
    monkeypatch.setattr(module, "git", lambda *args: next(responses))
    with pytest.raises(ValueError, match=reason):
        module.verify_clean(tmp_path)


def test_runner_accepts_clean_host(monkeypatch, tmp_path):
    module = runner()
    responses = iter([BASE.encode(), b"H file.py\0", b""])
    monkeypatch.setattr(module, "git", lambda *args: next(responses))
    module.verify_clean(tmp_path)
