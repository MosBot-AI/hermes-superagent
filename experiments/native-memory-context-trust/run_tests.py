"""Verify and test the reviewed host patch in a prepared disposable checkout."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parent
BASE = "2281116525106e3c109993ccb5dc74d02bfc1427"
PATCH = "native-memory-context-trust.patch"
GUARD = ARTIFACT.parents[1] / "acceptance/live/native_bot_socket_guard.py"


def git(checkout, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(checkout), *args],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def verify(checkout):
    manifest = json.loads((ARTIFACT / "manifest.json").read_text())
    patch = (ARTIFACT / PATCH).read_bytes()
    if manifest["base"] != BASE or hashlib.sha256(patch).hexdigest() != manifest["patch_sha256"]:
        raise ValueError("Wrong base or patch checksum")
    if git(checkout, "rev-parse", "HEAD").decode().strip() != BASE:
        raise ValueError("Wrong checkout HEAD")
    entries = git(checkout, "ls-files", "-v", "-z").split(b"\0")
    if any(entry and (entry[:1].islower() or entry[:1] == b"S") for entry in entries):
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
    for name in ("run_tests.py", "../../acceptance/live/native_bot_socket_guard.py"):
        digest = hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest()
        if digest != manifest["source_hashes"][name]:
            raise ValueError("Experiment source checksum mismatch")
    return manifest


def run(checkout, interpreter, files):
    with tempfile.TemporaryDirectory(prefix="memory-context-trust-") as temp:
        root = Path(temp)
        guard = root / "guard"
        guard.mkdir()
        home = root / "home"
        home.mkdir()
        (guard / "sitecustomize.py").write_text(
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "try:\n"
            "    from native_bot_socket_guard import activate\n"
            "    activate(Path(os.environ['HERMES_TEST_SANDBOX']))\n"
            "except Exception:\n"
            "    raise SystemExit('Could not load the fixture socket guard') from None\n"
            "try:\n"
            "    sys.audit('socket.getaddrinfo', 'blocked.invalid')\n"
            "except PermissionError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('Fixture socket guard did not deny external DNS')\n"
        )
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(home),
            "HERMES_HOME": str(home / ".hermes"),
            "HERMES_RUNTIME_DIR": str(root / "runtime"),
            "HERMES_TEST_SANDBOX": str(root),
            "TMPDIR": str(root),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "PYTHONPATH": os.pathsep.join(map(str, (guard, GUARD.parent, checkout))),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "LANG": "C.UTF-8",
            "TZ": "UTC",
        }
        return subprocess.run(
            [
                str(interpreter.absolute()),
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--tb=short",
                "--show-capture=no",
                *files,
            ],
            cwd=checkout,
            env=env,
            timeout=600,
            check=False,
        ).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    try:
        manifest = verify(checkout)
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Refusing experiment run: {exc}\n")
    if args.check_only:
        print("Exact staged artifact verified. No upstream Python executed.")
        return 0
    return run(checkout, args.python, manifest["native_test_files"])


if __name__ == "__main__":
    raise SystemExit(main())
