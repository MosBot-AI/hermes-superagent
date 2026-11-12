"""Run a real Electron acceptance case from a prepared Hermes checkout."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

from scripts.check import ROOT, verify_checkout

DESKTOP_TESTS = ROOT / "tests/desktop"
GATEWAY_FIXTURE = "desktop_native_gateway_fixture.ts"
CASES = {
    "profile-routing": (
        "desktop_profile_route_ipc.spec.ts",
        (GATEWAY_FIXTURE,),
        "profile routing",
    ),
    "bot-canonical": (
        "desktop_bot_canonical_refusal.spec.ts",
        (GATEWAY_FIXTURE, "desktop_bot_canonical_fixture.py"),
        "Bot Mode canonical chat",
    ),
}
CONFIG = """export default {
  testDir: '.',
  testMatch: %s,
  outputDir: process.env.HERMES_E2E_OUTPUT,
  timeout: 150_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: 'json',
  use: { trace: 'off', screenshot: 'off', video: 'off' },
}
"""
NAMESPACE_SETUP = r"""
mount -t tmpfs -o mode=1777,size=32m,nr_inodes=8192 tmpfs /tmp
ip link set lo up
test "$(ip -o link show | wc -l)" -eq 1
test -z "$(ip -4 route show default)"
test -z "$(ip -6 route show default)"
# Keep a shell as PID 1 so Xvfb can signal its xvfb-run parent on readiness.
setpriv --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs \
  xvfb-run -a -e /dev/stderr --server-args='-screen 0 1280x1024x24 -nolisten tcp' "$@"
exit $?
"""


def verify_build(host, python, node, env):
    verify_checkout(host)
    compatibility = json.loads((ROOT / "compatibility.json").read_text(encoding="utf-8"))
    node_version = json.loads((host / "pm/lock.json").read_text(encoding="utf-8"))["packages"][
        "node"
    ]["version"]
    actual_node = subprocess.check_output([node, "--version"], env=env, text=True, timeout=10)
    if actual_node.strip() != f"v{node_version}":
        raise ValueError(f"Prepared Desktop requires Node {node_version}")
    actual_python = subprocess.check_output(
        [python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        env=env,
        text=True,
        timeout=10,
    )
    if actual_python.strip() != compatibility["python"]:
        raise ValueError(f"Prepared Hermes requires Python {compatibility['python']}")

    desktop = host / "apps/desktop"
    stamp = json.loads((desktop / "build/install-stamp.json").read_text(encoding="utf-8"))
    if stamp["commit"] != compatibility["hermes_commit"] or stamp["dirty"] is not False:
        raise ValueError("Desktop build stamp must match the clean pinned Hermes commit")
    for asset in ("dist/electron-main.mjs", "dist-webapp/index.html"):
        if not (desktop / asset).is_file():
            raise ValueError(f"Prepared Hermes checkout is missing {asset}")
    subprocess.run(
        [node, host / "scripts/build/electron-runtime.mjs", "--source", host, "--no-install"],
        cwd=host,
        env=env,
        check=True,
        timeout=15,
    )
    return desktop


def isolated_environment(work, python, node):
    for name in ("user", "tmp", "core", "xdg", "bundled"):
        (work / name).mkdir(mode=0o700)
    absent_bus = f"unix:path={work / 'xdg' / 'no-dbus'}"
    return {
        "PATH": os.pathsep.join((str(node.parent), str(python.parent), os.defpath)),
        "HOME": str(work / "user"),
        "USERPROFILE": str(work / "user"),
        "TMPDIR": str(work / "tmp"),
        "XDG_RUNTIME_DIR": str(work / "xdg"),
        "XDG_CACHE_HOME": str(work / "cache"),
        "XDG_CONFIG_HOME": str(work / "config"),
        "XDG_DATA_HOME": str(work / "data"),
        "XDG_STATE_HOME": str(work / "state"),
        "DBUS_SESSION_BUS_ADDRESS": absent_bus,
        "DBUS_SYSTEM_BUS_ADDRESS": absent_bus,
        "HERMES_E2E_CORE_ROOT": str(work / "core"),
        "HERMES_E2E_OUTPUT": str(work / "results"),
        "HERMES_E2E_PYTHON": str(python),
        "HERMES_HOME": str(work / "hermes"),
        "HERMES_RUNTIME_DIR": str(work / "runtime"),
        "HERMES_BUNDLED_PLUGINS": str(work / "bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "CI": "true",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }


@contextmanager
def stage_probe(core, spec, fixtures):
    with ExitStack() as cleanup:
        for name in (*fixtures, spec):
            data = (DESKTOP_TESTS / name).read_bytes()
            destination = core / name
            with destination.open("xb") as stream:
                cleanup.callback(destination.unlink)
                stream.write(data)
        config = cleanup.enter_context(
            tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=core, prefix=".e07-desktop-", suffix=".ts"
            )
        )
        config.write(CONFIG % json.dumps(spec))
        config.flush()
        yield config.name


def run_probe(host, python, node, work, spec, fixtures):
    env = isolated_environment(work, python, node)
    desktop = verify_build(host, python, node, env)
    cli = desktop / "node_modules/@playwright/test/cli.js"
    if not cli.is_file():
        raise ValueError("Install the pinned Desktop workspace dependencies before running")
    with (
        stage_probe(desktop / "e2e/core", spec, fixtures) as config,
        (work / "playwright.json").open("xb") as report,
        (work / "launcher.log").open("xb") as diagnostics,
    ):
        with subprocess.Popen(
            [
                "unshare",
                "--user",
                "--map-current-user",
                "--keep-caps",
                "--net",
                "--pid",
                "--mount-proc",
                "--fork",
                "--kill-child=SIGKILL",
                "sh",
                "-eu",
                "-c",
                NAMESPACE_SETUP,
                "desktop-acceptance",
                node,
                cli,
                "test",
                "--config",
                config,
            ],
            cwd=desktop,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=report,
            stderr=diagnostics,
            start_new_session=True,
        ) as process:
            try:
                status = process.wait(timeout=210)
            finally:
                if process.poll() is None:
                    # unshare's death signal kills PID 1 and the remaining fixture processes.
                    process.kill()
                    process.wait(timeout=10)
    if status:
        raise ValueError(f"Isolated Electron acceptance exited {status}")
    stats = json.loads((work / "playwright.json").read_bytes()).get("stats", {})
    if stats.get("expected") != 1 or any(
        stats.get(key) != 0 for key in ("unexpected", "flaky", "skipped")
    ):
        raise ValueError("Expected one passing Electron acceptance case")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes", type=Path, required=True, help="Prepared pinned checkout")
    parser.add_argument("--hermes-python", type=Path, required=True, help="Hermes interpreter")
    parser.add_argument("--node", type=Path, required=True, help="Pinned Hermes Node executable")
    parser.add_argument("--scratch", type=Path, default=Path("/var/tmp"), help="Short temp parent")
    parser.add_argument("--case", choices=CASES, default="profile-routing", help="Acceptance case")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This acceptance requires Linux namespaces and Xvfb")
    inputs = (args.hermes, args.hermes_python, args.node, args.scratch)
    if any(
        location.is_relative_to("/tmp")
        for path in inputs
        for location in (path.absolute(), path.resolve())
    ):
        parser.error("Keep the checkout, tools and scratch outside the fixture's private /tmp")

    spec, fixtures, description = CASES[args.case]
    work = Path(tempfile.mkdtemp(prefix="e07-ipc-", dir=args.scratch)).resolve()
    try:
        run_probe(
            args.hermes.resolve(),
            args.hermes_python.absolute(),
            args.node.absolute(),
            work,
            spec,
            fixtures,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"{exc}\nPrivate diagnostics: {work}\n")
    except KeyboardInterrupt:
        parser.exit(130, f"Acceptance interrupted. Private diagnostics: {work}\n")
    shutil.rmtree(work)
    print(f"One real Electron {description} case passed")


if __name__ == "__main__":
    main()
