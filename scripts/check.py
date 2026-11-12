#!/usr/bin/env python3
"""Run offline checks; optional pinned-host contracts fail rather than skip."""

import argparse
import hashlib
import json
import os
import shlex
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


def check_desktop_routes(checkout: Path, node: Path, env: dict[str, str]) -> None:
    lock = (checkout / "pm" / "lock.json").read_bytes()
    expected = json.loads(lock)["packages"]["node"]["version"]
    version = subprocess.check_output(
        [str(node), "--version"], cwd=ROOT, env=env, text=True, timeout=10
    ).strip()
    if version != f"v{expected}":
        raise ValueError(f"Hermes Desktop routing checks require Node {expected}, got {version}")
    evidence = {"node": expected, "hermes_pm_lock_sha256": hashlib.sha256(lock).hexdigest()}
    print("Desktop route environment: " + json.dumps(evidence, sort_keys=True), flush=True)
    run(
        [
            str(node),
            "--permission",
            f"--allow-fs-read={ROOT}",
            f"--allow-fs-read={checkout}",
            "--test",
            "--test-isolation=none",
            "tests/desktop/test_profile_route_composition.mjs",
        ],
        cwd=ROOT,
        env={**env, "HERMES_DESKTOP_CHECKOUT": str(checkout)},
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes", type=Path, help="Exact pinned Hermes source checkout")
    parser.add_argument("--hermes-python", type=Path, help="Its PM-built test interpreter")
    parser.add_argument("--hermes-node", type=Path, help="Its pinned Node for Desktop route checks")
    args = parser.parse_args()
    if bool(args.hermes) != bool(args.hermes_python):
        parser.error("--hermes and --hermes-python are required together")
    if args.hermes_node and not args.hermes:
        parser.error("--hermes-node requires --hermes and --hermes-python")
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
        run(
            [
                sys.executable,
                "-c",
                "import json,sqlite3,sys; print('Check runtime: ' + json.dumps("
                "{'executable':sys.executable,'python':sys.version,'sqlite':sqlite3.sqlite_version},"
                "sort_keys=True))",
            ],
            cwd=ROOT,
            env=env,
        )
        run([sys.executable, "-m", "pytest", "tests/unit", "-q"], cwd=ROOT, env=env)
        run([sys.executable, "-m", "ruff", "check", "."], cwd=ROOT, env=env)
        run([sys.executable, "-m", "ruff", "format", "--check", "."], cwd=ROOT, env=env)
        run([sys.executable, "-m", "ty", "check"], cwd=ROOT, env=env)
        run([sys.executable, "scripts/check_docs.py"], cwd=ROOT, env=env)
        if args.hermes:
            checkout = args.hermes.resolve()
            verify_checkout(checkout)
            if args.hermes_node:
                check_desktop_routes(checkout, args.hermes_node.absolute(), env)
            record_environment(checkout, args.hermes_python.absolute(), env)
            env["HERMES_PYTHON"] = str(args.hermes_python.absolute())
            run(
                [
                    "bash",
                    str(checkout / "scripts/run_tests.sh"),
                    str(ROOT / "tests/contracts"),
                    "--file-retries",
                    "0",
                    "--",
                    # The host runner scrubs PYTHONPATH with env -i. Pass both
                    # import roots through pytest's per-file configuration;
                    # quote each path because pytest splits this value itself.
                    "-o",
                    f"pythonpath={shlex.quote(str(checkout))} {shlex.quote(str(ROOT))}",
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
        if not args.hermes_node:
            print("Hermes Desktop route contracts NOT RUN; use --hermes-node with the pinned host.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
