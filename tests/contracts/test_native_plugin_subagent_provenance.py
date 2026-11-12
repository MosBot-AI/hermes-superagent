"""Real turn-bound subagent provenance in both native plugin modes."""

import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests/fixtures/native_plugin_subagent_probe.py"


def isolated_probe(host, root, profile, mode, scenario):
    os_home = root / "user"
    # The native live-DB guard always reserves HOME/.hermes, even under a test HOME.
    home = root / "install" / "profiles" / profile
    scratch, runtime, bundled, guard = (
        root / profile / name for name in ("scratch", "runtime", "bundled", "guard")
    )
    for directory in (home, scratch, runtime, bundled, guard):
        directory.mkdir(mode=0o700, parents=True)
    (guard / "sitecustomize.py").write_text(
        "from native_plugin_subagent_probe import install_fence\ninstall_fence()\n",
        encoding="utf-8",
    )
    relay_config = root / profile / "relay-plugins.toml"
    relay_config.write_text(
        "version = 1\n\n[plugins.policy.defaults]\nallowed = false\n", encoding="utf-8"
    )
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ}
    env.update(
        HOME=str(os_home),
        USERPROFILE=str(os_home),
        HERMES_HOME=str(home),
        HERMES_RUNTIME_DIR=str(runtime),
        HERMES_BUNDLED_PLUGINS=str(bundled),
        HERMES_ENABLE_PROJECT_PLUGINS="0",
        HERMES_NEMO_RELAY_PLUGINS_TOML=str(relay_config),
        HERMES_PROVENANCE_FENCE=str(guard),
        HERMES_PROVENANCE_MODE=mode,
        HERMES_TEST_ISOLATION="1",
        TMPDIR=str(scratch),
        XDG_CONFIG_HOME=str(home / "xdg-config"),
        XDG_CACHE_HOME=str(home / "xdg-cache"),
        XDG_DATA_HOME=str(home / "xdg-data"),
        XDG_STATE_HOME=str(home / "xdg-state"),
        XDG_RUNTIME_DIR=str(runtime),
        PYTHONPATH=os.pathsep.join(map(str, (guard, PROBE.parent, host))),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        PYTHONUNBUFFERED="1",
    )
    log_path = root / profile / "probe.log"
    with log_path.open("wb") as log:
        log_path.chmod(0o600)
        with subprocess.Popen(
            [sys.executable, str(PROBE), scenario],
            cwd=scratch,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            umask=0o077,
        ) as process:
            status = None
            try:
                status = process.wait(timeout=55)
            except subprocess.TimeoutExpired:
                pytest.fail(
                    f"{mode} {scenario} timed out; private diagnostics: {log_path}", pytrace=False
                )
            finally:
                if status != 0:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=8)
    assert status == 0, f"{mode} {scenario} failed; private diagnostics: {log_path}"
    assert (guard / f"active-{process.pid}").is_file()
    assert len(tuple(guard.glob("active-*"))) == (2 if mode == "host" else 1)
    (state,) = tuple(home.glob("plugin-data/*/state.json"))
    return state


@pytest.mark.skipif(os.name != "posix", reason="fixture cleanup requires POSIX process groups")
@pytest.mark.parametrize("mode", ["in_process", "host"])
def test_native_plugin_subagent_and_profile_provenance(tmp_path, mode):
    import hermes_cli.plugins

    host = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    pin = json.loads((ROOT / "compatibility.json").read_bytes())["hermes_commit"]
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=host, text=True, timeout=10
    ).strip()
    assert actual == pin
    tracked = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=host, text=True, timeout=10
    )
    assert tracked == "", "the pinned Hermes checkout has clean tracked files"

    scout_state = isolated_probe(host, tmp_path, "scout", mode, "turn")
    assert json.loads(scout_state.read_bytes()) == {"scope-marker": "scout-only"}
    if mode == "host":
        reviewer_state = isolated_probe(host, tmp_path, "reviewer", mode, "state")
        assert reviewer_state.parent.name == scout_state.parent.name
        assert json.loads(reviewer_state.read_bytes()) == {"scope-marker": "reviewer-only"}
        assert json.loads(scout_state.read_bytes()) == {"scope-marker": "scout-only"}
    assert not tuple((tmp_path / "install").glob("plugin-data/*/state.json"))
