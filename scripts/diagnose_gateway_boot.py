#!/usr/bin/env python3
"""Plan, or explicitly run, pinned upstream credential-free Gateway diagnostics."""

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import check

ROOT = Path(__file__).resolve().parents[1]


def diagnostic_launcher(interpreter: Path) -> str:
    """Only restore the traceback lost by the control listener's warning boundary."""
    executable = str(interpreter.absolute())
    if any(character.isspace() for character in executable):
        raise ValueError("diagnostic interpreter path must contain no whitespace")
    return f"""#!{executable}
import logging
import runpy
import sys

if sys.argv[1:] != ["-m", "gateway.run"]:
    raise SystemExit("diagnostic launcher only supports -m gateway.run")
original_factory = logging.getLogRecordFactory()
def diagnostic_factory(*args, **kwargs):
    record = original_factory(*args, **kwargs)
    if (record.name == "gateway.control_socket"
            and str(record.msg).startswith("Gateway control socket failed to start:")
            and not record.exc_info and sys.exc_info()[0] is not None):
        record.exc_info = sys.exc_info()
    return record
logging.setLogRecordFactory(diagnostic_factory)
sys.argv = ["gateway.run"]
runpy.run_module("gateway.run", run_name="__main__")
"""


def environment_summary() -> dict[str, str]:
    """Read only non-secret process policy indicators; these do not identify a cause."""
    result = {"platform": sys.platform}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            key, _, value = line.partition(":")
            if key in {"NoNewPrivs", "Seccomp", "Seccomp_filters"}:
                result[key] = value.strip()
    except OSError:
        pass
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--hermes-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new private evidence directory")
    parser.add_argument("--deadline", type=float, default=30)
    parser.add_argument(
        "--run-native",
        action="store_true",
        help="run only after this environment is confirmed to permit official native transport",
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.deadline) or not 0 < args.deadline <= 300:
        parser.error("--deadline must be finite and in (0, 300]")
    host = args.hermes.resolve()
    interpreter = args.hermes_python.absolute()
    check.verify_checkout(host)
    launcher = diagnostic_launcher(interpreter)
    probe = host / "evals/shared_gateway/normal_boot.py"
    if not probe.is_file() or not interpreter.is_file():
        parser.error("pinned upstream bootstrap probe and interpreter must exist")
    plan = {
        "host_sha": json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"],
        "environment": environment_summary(),
        "native_execution_requested": args.run_native,
        "scope": "credential-free normal bootstrap descriptor, not authenticated task acceptance",
        "limitations": [
            "EPERM alone does not identify the failed syscall or security policy",
            "process policy indicators do not establish historical failure causality",
            "no model call, plugin installation, client task or restart recovery is tested",
            "do not retry a denied operation or switch environments to evade a restriction",
        ],
    }
    if not args.run_native:
        print(json.dumps(plan, indent=2))
        return 0
    if os.name != "posix":
        parser.error("upstream probe requires native POSIX")
    # Never overwrite prior evidence. The upstream probe supplies a disposable home,
    # allowlisted environment, owned process-group cleanup and descriptor verdict.
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    (args.output / "PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")
    wrapper = args.output.resolve() / "diagnostic-python"
    wrapper.write_text(launcher)
    wrapper.chmod(0o700)
    command = [
        str(interpreter),
        str(probe),
        "--repo",
        str(host),
        "--python",
        str(wrapper),
        "--output",
        str(args.output.resolve() / "BOOT.json"),
        "--deadline",
        str(args.deadline),
    ]
    # The probe itself never inherits credentials; it launches the Gateway with a
    # stricter PATH/LANG/TZ allowlist and fresh HOME/USERPROFILE/HERMES_HOME.
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    result = subprocess.run(command, cwd=host, env=env, stdin=subprocess.DEVNULL, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
