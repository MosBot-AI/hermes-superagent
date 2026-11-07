#!/usr/bin/env python3
"""Verify an explicitly prepared disposable checkout; optionally run fixture tests.

Never applies the patch, checks out a revision, installs packages or bootstraps an
interpreter. This is an experiment runner, not the project's compatibility lane.
"""

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parent
PATCH_SHA256 = "e6a0e0a78450a2fb5385e5943e60541f6bd6fd04f71717378a40e39c709cfa5f"
BASE = "90d6b98fd86d20981ee06ddd5b7d93e4320f26a4"


def git(checkout, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(checkout), *args],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )


def verify(checkout):
    manifest = json.loads((ARTIFACT / "manifest.json").read_text())
    patch = (ARTIFACT / manifest["patch_file"]).read_bytes()
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        raise ValueError("Bundled patch checksum mismatch")
    if manifest["base"] != BASE or manifest["patch_sha256"] != PATCH_SHA256:
        raise ValueError("Manifest revision or checksum mismatch")
    if git(checkout, "rev-parse", "HEAD").decode().strip() != BASE:
        raise ValueError("HEAD must be the exact base, with the patch staged but uncommitted")
    entries = git(checkout, "ls-files", "-v", "-z").split(b"\0")
    if any(entry and (entry[:1].islower() or entry[:1] == b"S") for entry in entries):
        raise ValueError("assume-unchanged and skip-worktree index flags are not permitted")
    if git(checkout, "diff", "--no-ext-diff", "--no-textconv", "--name-only"):
        raise ValueError("Unstaged tracked changes are not permitted")
    if git(checkout, "ls-files", "--others", "--exclude-standard"):
        raise ValueError("Untracked non-ignored files are not permitted")
    staged = git(
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
    if staged != patch:
        raise ValueError("Staged diff must exactly equal the bundled reviewed patch")
    for name, digest in manifest["source_hashes"].items():
        if hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Experiment source checksum mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument(
        "--python",
        required=True,
        type=Path,
        help="Existing pre-provisioned Python 3.14 interpreter",
    )
    parser.add_argument(
        "--disposable-copy",
        action="store_true",
        required=True,
        help="Acknowledge this is a disposable, credential-free checkout",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check patch/base guards without executing upstream Python",
    )
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    # Do not resolve the interpreter symlink: its venv path is significant.
    interpreter = args.python.absolute()
    try:
        manifest = verify(checkout)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Refusing experiment run: {exc}\n")
    if args.check_only:
        print("Exact base and staged reviewed patch verified; no tests run.")
        return 0
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        parser.exit(2, "An existing executable interpreter is required; nothing installed.\n")
    with tempfile.TemporaryDirectory(prefix="text-worker-tests-") as home:
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": home,
            "TZ": "UTC",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "PYTHONUTF8": "1",
            "HERMES_PYTHON": str(interpreter),
            "HERMES_RUNTIME_DIR": str(Path(home) / "runtime"),
            "__HERMES_TESTS_REEXEC": "1",
        }
        subprocess.run(
            [
                str(interpreter),
                "-c",
                "import sys, pytest; "
                "assert sys.version_info[:2] == (3, 14), 'Python 3.14 required'",
            ],
            check=True,
            cwd=checkout,
            env=env,
        )
        # The pinned canonical shell runner honors unactivated HERMES_PYTHON
        # when pytest imports. REEXEC makes a failed preflight exit rather
        # than provision; explicit runtime prevents account-store discovery.
        return subprocess.run(
            [
                "bash",
                "scripts/run_tests.sh",
                *manifest["portable_test_files"],
                str(ARTIFACT / "test_task_worker.py"),
                "--file-retries",
                "0",
                "--",
                "-o",
                "pythonpath="
                + " ".join(
                    shlex.quote(str(path))
                    for path in (
                        checkout,
                        ARTIFACT.parents[1],
                        ARTIFACT.parents[1] / "tests/contracts",
                    )
                ),
                "-q",
                "--tb=short",
            ],
            cwd=checkout,
            env=env,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
