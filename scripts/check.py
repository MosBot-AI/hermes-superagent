#!/usr/bin/env python3
"""Run offline checks; optional pinned-host contracts fail rather than skip."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 180) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=timeout)


def verify_checkout(checkout: Path) -> None:
    expected = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.stdout.strip() != expected:
        raise ValueError(f"Hermes checkout must be exactly {expected}")
    dirty = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if dirty.stdout.strip():
        raise ValueError("Hermes tracked sources must be clean for compatibility evidence")


def record_environment(checkout: Path, interpreter: Path, env: dict[str, str]) -> None:
    probe = (
        "import importlib.metadata as m,json,platform;"
        "print(json.dumps({'python':platform.python_version(),"
        "'packages':sorted((d.metadata['Name'],d.version) for d in m.distributions())}))"
    )
    result = subprocess.run(
        [str(interpreter), "-c", probe],
        cwd=checkout,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observed = json.loads(result.stdout)
    if observed["python"].split(".")[:2] != ["3", "14"]:
        raise ValueError("The recorded Hermes baseline requires a Python 3.14 test interpreter")
    evidence = {
        "python": observed["python"],
        "hermes_uv_lock_sha256": hashlib.sha256((checkout / "uv.lock").read_bytes()).hexdigest(),
        "installed_package_count": len(observed["packages"]),
        "installed_packages_sha256": hashlib.sha256(
            json.dumps(observed["packages"], separators=(",", ":")).encode()
        ).hexdigest(),
        "environment_origin": "caller-supplied; prepare with pinned Hermes pm.build_env",
        "lock_environment_equivalence_attested": False,
    }
    print("Compatibility environment: " + json.dumps(evidence, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes", type=Path, help="Exact pinned Hermes source checkout")
    parser.add_argument("--hermes-python", type=Path, help="Its PM-built test interpreter")
    args = parser.parse_args()
    if bool(args.hermes) != bool(args.hermes_python):
        parser.error("--hermes and --hermes-python are required together")
    with tempfile.TemporaryDirectory(prefix="personal-agent-check-") as home:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": home,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
        run([sys.executable, "-m", "pytest", "tests/unit", "-q"], cwd=ROOT, env=env)
        run([sys.executable, "-m", "ruff", "check", "."], cwd=ROOT, env=env)
        run([sys.executable, "-m", "ruff", "format", "--check", "."], cwd=ROOT, env=env)
        run([sys.executable, "-m", "ty", "check"], cwd=ROOT, env=env)
        run([sys.executable, "scripts/check_docs.py"], cwd=ROOT, env=env)
        if args.hermes:
            checkout = args.hermes.resolve()
            verify_checkout(checkout)
            record_environment(checkout, args.hermes_python.absolute(), env)
            env["HERMES_PYTHON"] = str(args.hermes_python.absolute())
            run(
                [
                    "bash",
                    str(checkout / "scripts/run_tests.sh"),
                    str(ROOT / "tests/contracts/test_native_plugin.py"),
                    "--file-retries",
                    "0",
                    "-q",
                    "--tb=short",
                ],
                cwd=checkout,
                env=env,
                timeout=600,
            )
            print("Unit, lint, type, bilingual docs and pinned Hermes contract checks passed.")
        else:
            print("Unit/lint/type/docs checks passed. Hermes compatibility NOT RUN; use --hermes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
