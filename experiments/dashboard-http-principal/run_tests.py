"""Run the same dashboard consumer on verified clean and proposed Hermes checkouts."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree

ARTIFACT = Path(__file__).resolve().parent
GUARD = ARTIFACT.parents[1] / "acceptance/live/native_bot_socket_guard.py"
PROBE = ARTIFACT / "test_http_principal.py"
PATCH = ARTIFACT / "dashboard-http-principal.patch"
BASE = "2281116525106e3c109993ccb5dc74d02bfc1427"

GUARD_STARTUP = """
import os
import sys
from pathlib import Path

try:
    from native_bot_socket_guard import activate
    activate(Path(os.environ["HERMES_TEST_SANDBOX"]))
    try:
        sys.audit("socket.getaddrinfo", "blocked.invalid")
    except PermissionError:
        pass
    else:
        raise RuntimeError("Expected the socket guard to reject external DNS")
except Exception:
    raise SystemExit("Could not activate the synthetic fixture guard") from None
"""


def git(checkout, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(checkout), *args],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def verify_inputs(clean, proposed):
    manifest = json.loads((ARTIFACT / "manifest.json").read_text())
    if manifest["base"] != BASE:
        raise ValueError("Wrong Hermes base")
    for path in (PATCH, PROBE, GUARD, Path(__file__)):
        relative = os.path.relpath(path, ARTIFACT)
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"][relative]:
            raise ValueError(f"Input checksum mismatch for {relative}")
    for checkout in (clean, proposed):
        if git(checkout, "rev-parse", "HEAD").decode().strip() != BASE:
            raise ValueError("Wrong Hermes checkout revision")
        entries = git(checkout, "ls-files", "-v", "-z").split(b"\0")
        if any(entry and (entry[:1].islower() or entry[:1] == b"S") for entry in entries):
            raise ValueError("Hidden index flags refused")
        if git(checkout, "diff", "--name-only") or git(
            checkout, "ls-files", "--others", "--exclude-standard"
        ):
            raise ValueError("Unstaged or untracked changes refused")
    if git(clean, "diff", "--cached", "--name-only", BASE):
        raise ValueError("Clean Hermes checkout has staged changes")

    diff = git(
        proposed,
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
    staged_tree = git(proposed, "write-tree").decode().strip()
    if diff != PATCH.read_bytes() or staged_tree != manifest["staged_tree"]:
        raise ValueError("Staged Hermes checkout differs from review artifact")
    return manifest


def isolated_env(subdir, checkout, interpreter):
    home, hook, temp = (subdir / name for name in ("home", "hook", "tmp"))
    for directory in (home, hook, temp):
        directory.mkdir(parents=True)
    (hook / "sitecustomize.py").write_text(GUARD_STARTUP)
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "TMPDIR": str(temp),
        "XDG_CACHE_HOME": str(subdir / "cache"),
        "XDG_CONFIG_HOME": str(subdir / "config"),
        "HERMES_HOME": str(home / ".hermes"),
        "HERMES_RUNTIME_DIR": str(subdir / "runtime"),
        "HERMES_PYTHON": str(interpreter),
        "HERMES_TEST_SANDBOX": str(subdir),
        "PYTHONPATH": os.pathsep.join(map(str, (hook, GUARD.parent, checkout))),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }


def run_probe(checkout, interpreter, root, *, proposed, expected_cases):
    label = "candidate" if proposed else "clean pin"
    junit = root / "comparison.xml"
    env = isolated_env(root, checkout, interpreter)
    env["HERMES_TEST_EXPECT_PLUGIN_PRINCIPAL"] = "yes" if proposed else "no"
    print(f"Dashboard principal probe on {label}", flush=True)
    subprocess.run(
        [
            str(interpreter),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests.conftest",
            f"--rootdir={checkout}",
            f"--basetemp={root / 'pytest'}",
            "--show-capture=no",
            "--tb=short",
            "-o",
            "junit_logging=no",
            f"--junitxml={junit}",
            str(PROBE),
        ],
        cwd=checkout,
        env=env,
        check=True,
        timeout=180,
    )
    receipt = ElementTree.parse(junit)
    excluded = ("error", "failure", "skipped", "system-out", "system-err")
    if len(receipt.findall(".//testcase")) != expected_cases or any(
        receipt.findall(f".//{tag}") for tag in excluded
    ):
        raise ValueError(f"Expected {expected_cases} clean passing cases on {label}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--proposed", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    clean, proposed, interpreter = (
        args.clean.resolve(),
        args.proposed.resolve(),
        args.python.absolute(),
    )
    manifest = verify_inputs(clean, proposed)
    with tempfile.TemporaryDirectory(prefix="hpp-") as directory:
        root = Path(directory)
        run_probe(
            clean,
            interpreter,
            root / "clean",
            proposed=False,
            expected_cases=manifest["comparison_cases_per_checkout"],
        )
        run_probe(
            proposed,
            interpreter,
            root / "candidate",
            proposed=True,
            expected_cases=manifest["comparison_cases_per_checkout"],
        )
        subprocess.run(
            [
                "bash",
                "scripts/run_tests.sh",
                *manifest["native_regression_files"],
                "--file-retries",
                "0",
                "--",
                "-q",
                "--tb=short",
                "--show-capture=no",
            ],
            cwd=proposed,
            env=isolated_env(root / "regressions", proposed, interpreter),
            check=True,
            timeout=360,
        )


if __name__ == "__main__":
    main()
