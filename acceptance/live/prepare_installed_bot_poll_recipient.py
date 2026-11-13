"""Stage a disposable recipient using the official installer before reply isolation."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def prepare(host, root):
    # The launcher uses isolated Python mode. Only add the local fixture directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_packaged_gateway_bot import verify_install
    from test_packaged_gateway_tasks import install_package, write_install_config

    home, user, scratch = (root / name for name in ("install-home", "install-user", "install-tmp"))
    for directory in (home, user, scratch):
        directory.mkdir(mode=0o700)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    env.update(
        HOME=str(user),
        USERPROFILE=str(user),
        HERMES_HOME=str(home),
        HERMES_RUNTIME_DIR=str(root / "install-runtime"),
        TMPDIR=str(scratch),
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_CACHE_HOME=str(root / "cache"),
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
    )

    def git(directory, *args):
        return subprocess.check_output(
            ["git", "-C", str(directory), *args], env=env, text=True, timeout=10
        ).strip()

    pin = json.loads((REPO / "compatibility.json").read_bytes())["hermes_commit"]
    if git(host, "rev-parse", "HEAD") != pin or git(host, "status", "--porcelain", "-uno"):
        raise ValueError("Hermes source must match the clean compatibility pin")
    source = git(REPO, "rev-parse", "HEAD")
    package = root / "package"
    build = [
        sys.executable,
        str(REPO / "scripts/build_runtime_distribution.py"),
        "--source-commit",
        source,
        "--output-dir",
        str(package),
    ]
    for command in (build, [*build, "--verify"]):
        subprocess.run(command, cwd=REPO, env=env, check=True, timeout=25)
    git(package, "init", "-q", "-b", "main")
    git(package, "add", ".")
    git(
        package,
        "-c",
        "user.name=Acceptance",
        "-c",
        "user.email=acceptance@example.invalid",
        "commit",
        "-qm",
        "test: stage verified runtime",
    )
    write_install_config(home)
    # The launcher bounds the whole process group, including dependency children.
    install_package(host, package, env, timeout=None)
    verify_install(home, package, source)
    # Carry the official install and its enablement into the private Gateway home.
    # Installer-owned runtime generations and bootstrap files stay in staging.
    recipient = root / "h"
    recipient.mkdir(mode=0o700)
    shutil.move(home / "plugins", recipient / "plugins")
    shutil.move(home / "config.yaml", recipient / "config.yaml")
    (root / "source-commit").write_text(source, encoding="ascii")


if __name__ == "__main__":
    try:
        prepare(*(Path(arg).resolve(strict=True) for arg in sys.argv[1:]))
    except (OSError, ValueError, subprocess.SubprocessError, AssertionError) as error:
        raise SystemExit(
            f"Official disposable plugin installation failed ({type(error).__name__})"
        ) from None
