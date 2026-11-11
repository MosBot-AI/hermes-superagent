#!/usr/bin/env python3
"""Verify an explicitly prepared disposable staged checkout; never install/apply/activate."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parent
BASE = "2281116525106e3c109993ccb5dc74d02bfc1427"


def git(checkout, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(checkout), *args],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )


def verify(checkout):
    manifest = json.loads((ARTIFACT / "manifest.json").read_text())
    patch = (ARTIFACT / manifest["patch_file"]).read_bytes()
    if manifest["base"] != BASE or hashlib.sha256(patch).hexdigest() != manifest["patch_sha256"]:
        raise ValueError("Wrong base or patch checksum")
    if git(checkout, "rev-parse", "HEAD").decode().strip() != BASE:
        raise ValueError("Wrong checkout HEAD")
    if any(
        e and (e[:1].islower() or e[:1] == b"S")
        for e in git(checkout, "ls-files", "-v", "-z").split(b"\0")
    ):
        raise ValueError("Hidden index flags refused")
    if git(checkout, "diff", "--no-ext-diff", "--no-textconv", "--name-only"):
        raise ValueError("Unstaged changes refused")
    if git(checkout, "ls-files", "--others", "--exclude-standard"):
        raise ValueError("Untracked files refused")
    diff = git(
        checkout,
        "-c",
        "core.quotePath=true",
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--abbrev=8",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        BASE,
    )
    if diff != patch or git(checkout, "write-tree").decode().strip() != manifest["staged_tree"]:
        raise ValueError("Staged checkout differs from reviewed artifact")
    for name, digest in manifest["source_hashes"].items():
        if hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Experiment source checksum mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    manifest = verify(checkout)
    if args.check_only:
        print("Exact staged artifact verified; no upstream Python executed.")
        return 0
    with tempfile.TemporaryDirectory(prefix="checkpoint-source-review-") as home:
        env = {
            "PATH": os.defpath,
            "HOME": home,
            "HERMES_HOME": home,
            "PYTHONPATH": str(checkout),
            "CHECKPOINT_PROPOSAL_HOST": str(checkout),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
            "TZ": "UTC",
        }
        # Observe native journal selection without overriding its safety policy.
        probe = subprocess.run(
            [
                str(args.python.absolute()),
                "-c",
                "import os, sqlite3; from pathlib import Path; "
                "from hermes_state import SessionDB; "
                "db = SessionDB(Path(os.environ['HERMES_HOME']) / 'journal-probe.db'); "
                "print('Native SQLite runtime:', sqlite3.sqlite_version, "
                "'journal_mode:', db._conn.execute('PRAGMA journal_mode').fetchone()[0], "
                "flush=True); db.close()",
            ],
            cwd=checkout,
            env=env,
            timeout=60,
        ).returncode
        if probe:
            return probe
        result = subprocess.run(
            [
                str(args.python.absolute()),
                "-m",
                "pytest",
                "-q",
                str(ARTIFACT / "test_checkpoint_sources.py"),
                str(ARTIFACT / "test_recovery.py"),
                str(ARTIFACT / "test_source_reads.py"),
                str(ARTIFACT / "test_acceptance.py"),
                "--confcutdir=" + str(ARTIFACT),
            ],
            cwd=checkout,
            env=env,
            timeout=600,
        ).returncode
        if result:
            return result
        # Use the pinned host's canonical per-file isolation runner, not bare pytest.
        # An explicit prepared interpreter avoids provisioning or installing anything.
        env.update(HERMES_PYTHON=str(args.python.absolute()))
        return subprocess.run(
            [
                "bash",
                str(checkout / "scripts/run_tests.sh"),
                "-j",
                "2",
                *manifest["native_test_files"],
                "-q",
            ],
            cwd=checkout,
            env=env,
            timeout=1200,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
