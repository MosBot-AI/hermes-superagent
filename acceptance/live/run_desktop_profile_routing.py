"""Run a real Desktop or Webapp acceptance case from a prepared Hermes checkout."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

from scripts.check import ROOT, verify_checkout

DESKTOP_TESTS = ROOT / "tests/desktop"
GATEWAY_FIXTURE = "desktop_native_gateway_fixture.ts"
APPIMAGE_FIXTURE = "desktop_bot_appimage.ts"
CANONICAL_FIXTURE = "desktop_bot_canonical_fixture.py"
CANONICAL_OBSERVER = "desktop_bot_canonical_observer.ts"
CANONICAL_FIXTURES = (GATEWAY_FIXTURE, CANONICAL_FIXTURE, CANONICAL_OBSERVER, APPIMAGE_FIXTURE)
INSTALL_AMBIGUITY_SPEC = "desktop_install_ambiguity_ipc.spec.ts"
CANONICAL_CASE = "bot-canonical"
SSH_CASE = "bot-canonical-ssh"
SSH_ALIAS_CASE = "bot-canonical-ssh-alias"
SSH_SPEC = "desktop_bot_ssh.spec.ts"
SSH_FIXTURES = (GATEWAY_FIXTURE, CANONICAL_OBSERVER, APPIMAGE_FIXTURE)
SAVED_TOKEN_CASE = "bot-canonical-saved-token"
COMPRESSED_LOCAL_CASE = "compressed-history-adoption"
COMPRESSED_SAVED_CASE = "compressed-history-saved-token"
COMPRESSED_SPEC = "desktop_compressed_adoption.spec.ts"
COMPRESSED_FIXTURES = (
    GATEWAY_FIXTURE,
    "desktop_compressed_adoption_fixture.py",
    CANONICAL_OBSERVER,
    APPIMAGE_FIXTURE,
)
APPIMAGE_CASES = (
    CANONICAL_CASE,
    SSH_CASE,
    SSH_ALIAS_CASE,
    SAVED_TOKEN_CASE,
    COMPRESSED_LOCAL_CASE,
    COMPRESSED_SAVED_CASE,
)
WEBAPP_SIGNOUT_CASE = "active-webapp-sign-out"
PROPOSAL = ROOT / "experiments/bot-webapp-canonical"
CASES = {
    "profile-routing": (
        "desktop_profile_route_ipc.spec.ts",
        (GATEWAY_FIXTURE,),
        "profile routing",
    ),
    CANONICAL_CASE: (
        "desktop_bot_canonical_refusal.spec.ts",
        CANONICAL_FIXTURES,
        "Bot Mode canonical chat",
    ),
    SSH_CASE: (SSH_SPEC, SSH_FIXTURES, "OpenSSH Bot Mode"),
    SSH_ALIAS_CASE: (SSH_SPEC, SSH_FIXTURES, "OpenSSH Bot Mode profile alias"),
    SAVED_TOKEN_CASE: (
        "desktop_bot_saved_token_refusal.spec.ts",
        CANONICAL_FIXTURES,
        "saved Webapp token Bot Mode",
    ),
    "profile-retirement": (
        "desktop_profile_retirement_ipc.spec.ts",
        (GATEWAY_FIXTURE, "desktop_profile_retirement_fixture.py", CANONICAL_OBSERVER),
        "saved Webapp profile retirement",
    ),
    COMPRESSED_LOCAL_CASE: (
        COMPRESSED_SPEC,
        COMPRESSED_FIXTURES,
        "local compressed Bot Mode history",
    ),
    COMPRESSED_SAVED_CASE: (
        COMPRESSED_SPEC,
        COMPRESSED_FIXTURES,
        "saved Webapp token compressed Bot Mode history",
    ),
    WEBAPP_SIGNOUT_CASE: (
        "desktop_webapp_signout.spec.ts",
        (GATEWAY_FIXTURE, CANONICAL_OBSERVER),
        "serving Webapp sign-out",
    ),
    "install-marker-collision": (
        INSTALL_AMBIGUITY_SPEC,
        (GATEWAY_FIXTURE, CANONICAL_OBSERVER),
        "copied installation marker",
    ),
    "install-copy-ambiguity": (
        INSTALL_AMBIGUITY_SPEC,
        (GATEWAY_FIXTURE, CANONICAL_OBSERVER),
        "stopped installation copy",
    ),
}
CASE_TITLE_FILTERS = {
    SSH_CASE: "opens the named canonical chat over OpenSSH$",
    SSH_ALIAS_CASE: "opens the canonical chat behind an OpenSSH profile alias$",
    COMPRESSED_LOCAL_CASE: "compressed Bot Chat over the local private ticket$",
    COMPRESSED_SAVED_CASE: "compressed Bot Chat over the saved Webapp token$",
    "install-marker-collision": (
        "copied install marker collapses discovery while exact sources stay distinct$"
    ),
    "install-copy-ambiguity": "stopped home copy scopes equal canonical IDs to distinct sources$",
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
if [ -n "${HERMES_E2E_SSH_STATE:-}" ]; then
    account_home="$HERMES_E2E_SSH_STATE/account"
    # OpenSSH resolves its home through the account database, independently of HOME.
    awk -F: -v uid="$(id -u)" -v home="$account_home" '
        BEGIN { OFS=FS }
        $3 == uid { $6=home; matches++ }
        { print }
        END { if (matches != 1) exit 1 }
    ' /etc/passwd >"$HERMES_E2E_SSH_STATE/passwd"
    mount --bind "$HERMES_E2E_SSH_STATE/passwd" /etc/passwd
    test "$(getent passwd "$(id -u)" | cut -d: -f6)" = "$account_home"
    if [ -d /etc/ssh/ssh_config.d ]; then
        mount -t tmpfs -o mode=755,size=1m tmpfs /etc/ssh/ssh_config.d
    fi
    for f in /etc/ssh/ssh_config /etc/bash.bashrc /etc/ssh/sshrc; do
        if [ -e "$f" ]; then
            test -f "$f" && test ! -L "$f"
            mount --bind "$HERMES_E2E_SSH_STATE/empty" "$f"
        fi
    done
fi
if [ -n "${HERMES_E2E_APPIMAGE:-}" ]; then
    (
        cd "$HERMES_E2E_APPIMAGE_WORK"
        setpriv --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs \
            "$HERMES_E2E_APPIMAGE" --appimage-extract >appimage-extract.log 2>&1
    )
fi
# Keep a shell as PID 1 so Xvfb can signal its xvfb-run parent on readiness.
setpriv --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs \
  xvfb-run -a -e /dev/stderr --server-args='-screen 0 1280x1024x24 -nolisten tcp' "$@"
exit $?
"""


def verify_proposal(host, base, env):
    manifest = json.loads((PROPOSAL / "manifest.json").read_bytes())
    patch = (PROPOSAL / "bot-webapp-canonical.patch").read_bytes()
    if manifest["base"] != base or hashlib.sha256(patch).hexdigest() != manifest["patch_sha256"]:
        raise ValueError(
            "Saved-token proposal manifest does not match the compatibility pin and patch"
        )

    def git(*args):
        return subprocess.check_output(
            ["git", "--no-replace-objects", "-C", host, *args], env=env, timeout=10
        )

    ancestry = git("rev-list", "--parents", "-n", "1", "HEAD").decode().split()
    if len(ancestry) != 2 or ancestry[1] != base:
        raise ValueError(
            "Prepared proposal must be a direct single-parent commit on the Hermes pin"
        )
    commit = ancestry[0]
    if git("rev-parse", "HEAD^{tree}").decode().strip() != manifest["proposal_tree"]:
        raise ValueError("Prepared proposal tree does not match the reviewed source")
    if git("status", "--porcelain", "--untracked-files=normal") or any(
        not entry.startswith(b"H ") for entry in git("ls-files", "-v", "-z").split(b"\0") if entry
    ):
        raise ValueError("Prepared proposal checkout must be clean with a normal tracked index")
    actual_patch = git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--binary",
        "--full-index",
        "--no-renames",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base,
        commit,
        "--",
    )
    if actual_patch != patch:
        raise ValueError("Prepared proposal commit does not contain the exact reviewed patch")
    return commit


def verify_build(host, python, node, env, *, review_proposal=False, packaged=False):
    compatibility = json.loads((ROOT / "compatibility.json").read_text(encoding="utf-8"))
    expected_commit = compatibility["hermes_commit"]
    if review_proposal:
        expected_commit = verify_proposal(host, expected_commit, env)
    else:
        verify_checkout(host)
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
    if packaged:
        return desktop, expected_commit

    stamp = json.loads((desktop / "build/install-stamp.json").read_text(encoding="utf-8"))
    if stamp["commit"] != expected_commit or stamp["dirty"] is not False:
        raise ValueError("Desktop build stamp must match the verified clean source commit")
    for product, output in (("desktop", "dist"), ("webapp", "dist-webapp")):
        current = subprocess.check_output(
            [
                node,
                host / "scripts/build/freshness.mjs",
                "--source",
                host,
                "--product",
                product,
                "--out",
                desktop / output,
            ],
            cwd=host,
            env=env,
            timeout=30,
        )
        if current.strip() != b"true":
            raise ValueError(f"Prepared Hermes {product} build is missing or stale")
    subprocess.run(
        [node, host / "scripts/build/electron-runtime.mjs", "--source", host, "--no-install"],
        cwd=host,
        env=env,
        check=True,
        timeout=15,
    )
    return desktop, expected_commit


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


def run_probe(
    host,
    python,
    node,
    work,
    spec,
    fixtures,
    *,
    title_filter=None,
    review_proposal=False,
    chromium=None,
    appimage=None,
):
    env = isolated_environment(work, python, node)
    if chromium is not None:
        env["HERMES_E2E_CHROMIUM"] = str(chromium)
    if spec == SSH_SPEC:
        ssh_state = work / "ssh"
        ssh_state.mkdir(mode=0o700)
        (ssh_state / "account").mkdir(mode=0o700)
        (ssh_state / "account" / ".ssh").mkdir(mode=0o700)
        (ssh_state / "empty").touch(mode=0o600)
        env["HERMES_E2E_SSH_STATE"] = str(ssh_state)
    if spec == CASES[SAVED_TOKEN_CASE][0]:
        env["HERMES_E2E_BOT_WEBAPP_EXPECTATION"] = "proposal" if review_proposal else "baseline"
    desktop, expected_commit = verify_build(
        host, python, node, env, review_proposal=review_proposal, packaged=appimage is not None
    )
    if appimage is not None:
        env["HERMES_E2E_APPIMAGE"] = str(appimage)
        env["HERMES_E2E_APPIMAGE_WORK"] = str(work)
        env["HERMES_E2E_PACKAGED_COMMIT"] = expected_commit
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
                "--mount",
                "--propagation",
                "private",
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
                *(("--grep", title_filter) if title_filter else ()),
            ],
            cwd=desktop,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=report,
            stderr=diagnostics,
            start_new_session=True,
        ) as process:
            try:
                status = process.wait(timeout=330 if appimage is not None else 210)
            finally:
                if process.poll() is None:
                    # unshare's death signal kills PID 1 and the remaining fixture processes.
                    process.kill()
                    process.wait(timeout=10)
    if status:
        raise ValueError(f"Isolated browser or Electron acceptance exited {status}")
    stats = json.loads((work / "playwright.json").read_bytes()).get("stats", {})
    if stats.get("expected") != 1 or any(
        stats.get(key) != 0 for key in ("unexpected", "flaky", "skipped")
    ):
        raise ValueError("Expected one passing browser or Electron acceptance case")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes", type=Path, required=True, help="Prepared pinned checkout")
    parser.add_argument("--hermes-python", type=Path, required=True, help="Hermes interpreter")
    parser.add_argument("--node", type=Path, required=True, help="Pinned Hermes Node executable")
    parser.add_argument("--chromium", type=Path, help="Prepared Chromium executable for Webapp")
    parser.add_argument(
        "--appimage", type=Path, help="Local bundled AppImage matching the selected Hermes checkout"
    )
    parser.add_argument("--scratch", type=Path, default=Path("/var/tmp"), help="Short temp parent")
    parser.add_argument("--case", choices=CASES, default="profile-routing", help="Acceptance case")
    parser.add_argument(
        "--review-proposal",
        action="store_true",
        help="Verify a separately built saved-token proposal",
    )
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This acceptance requires Linux namespaces and Xvfb")
    if args.case in (SSH_CASE, SSH_ALIAS_CASE):
        if any(
            not shutil.which(command, path="/usr/bin:/bin")
            for command in ("/usr/sbin/sshd", "ssh", "ssh-keygen")
        ):
            parser.error(f"--case {args.case} requires OpenSSH server and client")
        # The account home is also used as a literal in the OpenSSH configuration.
        if not re.fullmatch(r"[a-zA-Z0-9_./-]+", str(args.scratch.resolve())):
            parser.error(f"--case {args.case} requires a simple absolute scratch path")
    if args.review_proposal and args.case != SAVED_TOKEN_CASE:
        parser.error(f"--review-proposal requires --case {SAVED_TOKEN_CASE}")
    if (args.chromium is not None) != (args.case == WEBAPP_SIGNOUT_CASE):
        parser.error(f"--chromium is required only for --case {WEBAPP_SIGNOUT_CASE}")
    inputs = (args.hermes, args.hermes_python, args.node, args.scratch)
    if args.chromium is not None:
        inputs += (args.chromium,)
        if not args.chromium.is_file() or not os.access(args.chromium, os.X_OK):
            parser.error("--chromium must identify an executable file")
    if args.appimage is not None:
        if args.case not in APPIMAGE_CASES:
            parser.error(f"--appimage requires --case {' or '.join(APPIMAGE_CASES)}")
        if not args.appimage.is_file() or not os.access(args.appimage, os.X_OK):
            parser.error("--appimage must identify an executable file")
        inputs += (args.appimage,)
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
            title_filter=CASE_TITLE_FILTERS.get(args.case),
            review_proposal=args.review_proposal,
            chromium=args.chromium.absolute() if args.chromium is not None else None,
            appimage=args.appimage.resolve() if args.appimage is not None else None,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"{exc}\nPrivate diagnostics: {work}\n")
    except KeyboardInterrupt:
        parser.exit(130, f"Acceptance interrupted. Private diagnostics: {work}\n")
    shutil.rmtree(work)
    variant = " proposal" if args.review_proposal else ""
    product = "Chromium" if args.case == WEBAPP_SIGNOUT_CASE else "Electron"
    if args.appimage is not None:
        product = "packaged Electron"
    print(f"One real {product} {description}{variant} case passed")


if __name__ == "__main__":
    main()
