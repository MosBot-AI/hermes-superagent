"""Stage a disposable recipient using the official installer before reply isolation."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def stage_tooling(source, destination):
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns(".staging-*", ".install.lock"),
    )
    if any(
        path.is_symlink() and not path.resolve().is_relative_to(destination)
        for path in destination.rglob("*")
    ):
        raise ValueError("The installer tooling contains an external link")


def prepare(host, root, tool_store=None, *, upstream=False):
    # The launcher uses isolated Python mode. Only add the local fixture directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from native_bot_reply_checkout import verify_checkout
    from ruamel.yaml import YAML
    from test_packaged_gateway_bot import verify_install
    from test_packaged_gateway_tasks import install_package, write_install_config

    home, user, scratch = (root / name for name in ("install-home", "install-user", "install-tmp"))
    for directory in (home, user, scratch):
        directory.mkdir(mode=0o700)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    runtime = root / "install-runtime"
    if tool_store is not None:
        stage_tooling(tool_store, runtime)
        uv_cache = tool_store.parent / "uv-cache"
        if uv_cache.is_dir():
            stage_tooling(uv_cache, root / "uv-cache")
    env.update(
        HOME=str(user),
        USERPROFILE=str(user),
        HERMES_HOME=str(home),
        HERMES_RUNTIME_DIR=str(runtime),
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

    pin = verify_checkout(host, env, upstream=upstream)
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
    selection = YAML(typ="safe").load(home / "config.yaml")["plugins"]
    if "hermes-personal-agent" not in selection.get(
        "enabled", []
    ) or "hermes-personal-agent" in selection.get("disabled", []):
        raise SystemExit("Official installer did not enable the runtime package")
    # Carry the official install and its enablement into the private Gateway home.
    # Installer-owned runtime generations and bootstrap files stay in staging.
    recipient = root / "h"
    recipient.mkdir(mode=0o700)
    shutil.move(home / "plugins", recipient / "plugins")
    shutil.move(home / "config.yaml", recipient / "config.yaml")
    (root / "source-commit").write_text(source, encoding="ascii")
    (root / "install-hermes-commit").write_text(pin, encoding="ascii")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("--tool-store", type=Path)
    parser.add_argument("--upstream-recovery-base", action="store_true")
    args = parser.parse_args()
    try:
        prepare(
            args.host.resolve(strict=True),
            args.root.resolve(strict=True),
            args.tool_store.resolve(strict=True) if args.tool_store else None,
            upstream=args.upstream_recovery_base,
        )
    except (OSError, ValueError, subprocess.SubprocessError, AssertionError) as error:
        raise SystemExit(
            f"Official disposable plugin installation failed ({type(error).__name__})"
        ) from None
