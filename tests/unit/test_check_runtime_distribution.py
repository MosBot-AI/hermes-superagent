"""Acceptance gates run before any installed-shaped package execution."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_runtime_distribution import commit, git
from test_runtime_distribution import source as source  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "runtime_checker", ROOT / "scripts/check_runtime_distribution.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.fixture
def package(source, tmp_path):  # noqa: F811
    repo, sha = source
    package = tmp_path / "package"
    checker.builder.build(repo, sha, package)
    return repo, sha, package


@pytest.mark.parametrize("change", ["missing", "tampered", "extra", "symlink", "absent"])
def test_integrity_refuses_before_host_or_scan(package, tmp_path, monkeypatch, change):
    repo, sha, package = package
    target = package / "plugin.yaml"
    if change == "missing":
        target.unlink()
    elif change == "tampered":
        target.write_text("tampered")
    elif change == "extra":
        (package / "foreign.py").write_text("raise Exception('must not execute')")
    elif change == "symlink":
        link = tmp_path / "link"
        link.symlink_to(package, target_is_directory=True)
        package = link
    else:
        package = tmp_path / "absent"
    monkeypatch.setattr(checker, "verify_host", lambda *args: pytest.fail("host checked too early"))
    monkeypatch.setattr(checker, "run_stage", lambda *args: pytest.fail("package executed"))
    with pytest.raises(ValueError):
        checker.check(repo, sha, package, tmp_path, Path(sys.executable), {})


@pytest.mark.parametrize("verdict", ["caution", "dangerous", "unknown", None])
def test_scan_keeps_all_findings_and_never_loads_on_non_safe(package, monkeypatch, verdict):
    repo, sha, package = package
    monkeypatch.setattr(checker, "verify_host", lambda host, expected: host)
    monkeypatch.setattr(checker, "materialize_host", lambda *args: "synthetic-tree")
    calls = []
    scan = {"verdict": verdict, "findings": [{"severity": "medium", "match": "SQLite byte"}]}

    def stage(name, *args):
        calls.append(name)
        assert name == "scan"
        return scan

    monkeypatch.setattr(checker, "run_stage", stage)
    report = {}
    with pytest.raises(ValueError, match="not safe"):
        checker.check(repo, sha, package, repo, Path(sys.executable), report)
    assert report["plugin_guard"] == scan and calls == ["scan"]
    assert "acceptance" not in report


def test_safe_scan_preserves_medium_findings_and_runs_verified_copy(package, monkeypatch):
    repo, sha, package = package
    monkeypatch.setattr(checker, "verify_host", lambda host, expected: host)
    monkeypatch.setattr(checker, "materialize_host", lambda *args: "synthetic-tree")
    calls = []
    scan = {"verdict": "safe", "findings": [{"severity": "medium", "match": "SQLite byte"}]}

    def stage(name, host, copied, source, interpreter, work):
        assert copied != package and copied.parent.parent == work / "profile"
        checker.builder.verify(repo, sha, copied)
        calls.append(name)
        return scan if name == "scan" else {"synthetic_acceptance": True}

    monkeypatch.setattr(checker, "run_stage", stage)
    report = {}
    checker.check(repo, sha, package, repo, Path(sys.executable), report)
    assert calls == ["scan", "runtime"] and report["status"] == "passed"
    assert report["plugin_guard"] == scan
    assert report["provenance_sha256"] == checker.builder.digest(
        (package / "PROVENANCE.json").read_bytes()
    )


def test_scan_time_tampering_blocks_runtime(package, monkeypatch):
    repo, sha, package = package
    monkeypatch.setattr(checker, "verify_host", lambda host, expected: host)
    monkeypatch.setattr(checker, "materialize_host", lambda *args: "synthetic-tree")

    def stage(name, host, copied, *args):
        assert name == "scan"
        (copied / "__init__.py").write_text("tampered")
        return {"verdict": "safe", "findings": []}

    monkeypatch.setattr(checker, "run_stage", stage)
    with pytest.raises(ValueError, match="integrity mismatch"):
        checker.check(repo, sha, package, repo, Path(sys.executable), {})


def test_wrong_dirty_and_symlink_host_refused(tmp_path):
    host = tmp_path / "host"
    host.mkdir()
    git(host, "init", "-q")
    (host / "tracked").write_text("original")
    sha = commit(host)
    assert checker.verify_host(host, sha) == host
    with pytest.raises(ValueError, match="pinned commit"):
        checker.verify_host(host, "0" * 40)
    (host / "untracked.py").write_text("unexpected")
    with pytest.raises(ValueError, match="clean"):
        checker.verify_host(host, sha)
    link = tmp_path / "linked-host"
    link.symlink_to(host, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        checker.verify_host(link, sha)


def test_report_exclusive_and_failure_has_no_machine_paths(package, tmp_path, monkeypatch):
    repo, sha, package = package
    report = tmp_path / "report.json"
    args = [
        "--repo",
        str(repo),
        "--source-commit",
        sha,
        "--package",
        str(package),
        "--hermes",
        str(tmp_path / "host"),
        "--hermes-python",
        sys.executable,
        "--report",
        str(report),
    ]

    def fail(*args):
        raise ValueError("private path: " + str(tmp_path))

    monkeypatch.setattr(checker, "check", fail)
    assert checker.main(args) == 1
    data = json.loads(report.read_text())
    assert data["error"] == "validation_failed" and str(tmp_path) not in report.read_text()
    assert not data["installation_performed"] and not data["live_model_calls"]
    with pytest.raises(FileExistsError):
        checker.main(args)
    args[-1] = str(package / "report.json")
    with pytest.raises(SystemExit):
        checker.main(args)


def test_child_rejects_global_imports_and_enforces_offline_guards():
    # Source checks complement the real cold-process acceptance run in CI.
    assert 'fullname == "personal_agent"' in checker.CHILD
    assert "sys.addaudithook(audit)" in checker.CHILD
    assert 'event == "subprocess.Popen"' in checker.CHILD
    assert 'scan_plugin(plugin, source="verified-committed-runtime")' in checker.CHILD
    assert "manager.discover_and_load()" in checker.CHILD


def test_scanner_machine_path_is_refused_not_written_to_report(package, monkeypatch):
    repo, sha, package = package
    monkeypatch.setattr(checker, "verify_host", lambda host, expected: host)
    monkeypatch.setattr(checker, "materialize_host", lambda *args: "synthetic-tree")

    def stage(name, host, copied, *args):
        assert name == "scan"
        return {"verdict": "safe", "findings": [{"file": str(copied / "plugin.yaml")}]}

    monkeypatch.setattr(checker, "run_stage", stage)
    report = {}
    with pytest.raises(ValueError, match="machine path"):
        checker.check(repo, sha, package, repo, Path(sys.executable), report)
    assert "plugin_guard" not in report and "acceptance" not in report


@pytest.mark.parametrize("hidden", ["skip-worktree", "assume-unchanged"])
def test_host_snapshot_ignores_hidden_index_edits_and_poisoned_bytecode(tmp_path, hidden):
    host = tmp_path / "host"
    host.mkdir()
    git(host, "init", "-q")
    (host / "module.py").write_text("ORIGINAL = True\n")
    (host / ".gitignore").write_text("__pycache__/\n")
    sha = commit(host)
    git(host, "update-index", "--" + hidden, "module.py")
    (host / "module.py").write_text("raise RuntimeError('hidden worktree poison')\n")
    cache = host / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-314.pyc").write_bytes(b"poison")
    # Git status really hides both hazards; neither is an execution input.
    assert not git(host, "status", "--porcelain", "--untracked-files=all")
    snapshot = tmp_path / "snapshot"
    checker.materialize_host(host, sha, snapshot)
    assert (snapshot / "module.py").read_text() == "ORIGINAL = True\n"
    assert not (snapshot / "__pycache__").exists()
    assert "poison" in (host / "module.py").read_text()


def test_host_snapshot_ignores_export_attributes_and_git_replacements(tmp_path):
    host = tmp_path / "host"
    host.mkdir()
    git(host, "init", "-q")
    (host / "module.py").write_text("ORIGINAL = True\n")
    sha = commit(host)
    (host / ".git/info/attributes").write_text("module.py export-ignore\n")
    (host / "module.py").write_text("REPLACED = True\n")
    replacement = commit(host)
    git(host, "replace", sha, replacement)
    assert "REPLACED" in git(host, "show", f"{sha}:module.py")
    snapshot = tmp_path / "snapshot"
    checker.materialize_host(host, sha, snapshot)
    assert (snapshot / "module.py").read_text() == "ORIGINAL = True\n"


def test_host_snapshot_rejects_committed_links(tmp_path):
    host = tmp_path / "host"
    host.mkdir()
    git(host, "init", "-q")
    (host / "module.py").symlink_to("outside.py")
    sha = commit(host)
    with pytest.raises(ValueError, match="unsafe file"):
        checker.materialize_host(host, sha, tmp_path / "snapshot")


def test_host_git_checks_ignore_fsmonitor_and_ambient_git_redirects(tmp_path, monkeypatch):
    host = tmp_path / "host"
    host.mkdir()
    git(host, "init", "-q")
    (host / "module.py").write_text("ORIGINAL = True\n")
    sha = commit(host)
    marker = tmp_path / "must-not-exist"
    hook = tmp_path / "fsmonitor"
    hook.write_text("#!/bin/sh\ntouch " + str(marker) + "\n")
    hook.chmod(0o755)
    git(host, "config", "core.fsmonitor", str(hook))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong-git-dir"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hook))
    assert checker.verify_host(host, sha) == host
    checker.materialize_host(host, sha, tmp_path / "snapshot")
    assert not marker.exists()


def test_child_guards_block_connectionless_sends_and_processes_before_io(tmp_path):
    import subprocess

    bootstrap = checker.CHILD.split('\nif stage == "scan":', 1)[0]
    # Call patched descriptors with None: no socket creation or packet is needed.
    probe = """
import subprocess
for name in ("connect", "bind", "sendto", "sendmsg"):
    if hasattr(socket.socket, name):
        try:
            getattr(socket.socket, name)(None)
        except AssertionError:
            pass
        else:
            raise AssertionError("socket guard did not fire")
try:
    subprocess.run([sys.executable, "-c", "raise SystemExit(99)"])
except AssertionError:
    pass
else:
    raise AssertionError("subprocess guard did not fire")
print("guards verified")
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            bootstrap + probe,
            "runtime",
            str(tmp_path / "host"),
            str(tmp_path / "plugin"),
            str(tmp_path / "source"),
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "guards verified"


def test_git_wrapper_disables_fetch_protocols_and_scrubs_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_SSH_COMMAND", "must-not-run")
    monkeypatch.setenv("GIT_DIR", "/must-not-read")
    monkeypatch.setenv("SECRET_FIXTURE_VALUE", "must-not-inherit")
    seen = {}

    def execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return b"local objects only"

    monkeypatch.setattr(checker.builder.subprocess, "check_output", execute)
    assert checker.builder.git(tmp_path, "cat-file", "--batch", input=b"abc\n")
    assert "core.fsmonitor=false" in seen["command"]
    assert "protocol.allow=never" in seen["command"]
    assert "--no-replace-objects" in seen["command"]
    assert seen["input"] == b"abc\n"
    assert seen["env"]["GIT_NO_LAZY_FETCH"] == "1"
    assert seen["env"]["GIT_ALLOW_PROTOCOL"] == ""
    assert seen["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
    for key in ("GIT_SSH_COMMAND", "GIT_DIR", "SECRET_FIXTURE_VALUE"):
        assert key not in seen["env"]
