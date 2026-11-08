"""Offline diagnostics tests: never start a Gateway or a real socket."""

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import diagnose_gateway_boot as diagnostic  # noqa: E402


def test_launcher_preserves_exception_and_executes_only_official_module(monkeypatch):
    import runpy

    seen = []
    previous = logging.getLogRecordFactory()

    def module(name, run_name):
        assert (name, run_name) == ("gateway.run", "__main__")
        try:
            raise PermissionError(1, "synthetic operation denied")
        except PermissionError:
            record = logging.getLogRecordFactory()(
                "gateway.control_socket",
                logging.WARNING,
                __file__,
                1,
                "Gateway control socket failed to start: %s",
                ("error",),
                None,
            )
            seen.append(record)
        unrelated = logging.getLogRecordFactory()(
            "other",
            logging.INFO,
            __file__,
            1,
            "unchanged",
            (),
            None,
        )
        assert unrelated.exc_info is None

    monkeypatch.setattr(runpy, "run_module", module)
    monkeypatch.setattr(sys, "argv", ["diagnostic-python", "-m", "gateway.run"])
    try:
        exec(diagnostic.diagnostic_launcher(Path(sys.executable)), {})
    finally:
        logging.setLogRecordFactory(previous)
    assert seen[0].exc_info[0] is PermissionError
    assert seen[0].exc_info[1].errno == 1
    assert seen[0].exc_info[2] is not None


def test_launcher_refuses_arbitrary_module(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["diagnostic-python", "-m", "another.module"])
    with pytest.raises(SystemExit, match="only supports"):
        exec(diagnostic.diagnostic_launcher(Path(sys.executable)), {})


def test_launcher_rejects_whitespace_path():
    with pytest.raises(ValueError, match="whitespace"):
        diagnostic.diagnostic_launcher(Path("/tmp/a b/python"))


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    host = tmp_path / "host"
    probe = host / "evals/shared_gateway/normal_boot.py"
    probe.parent.mkdir(parents=True)
    probe.write_text("# synthetic")
    monkeypatch.setattr(diagnostic.check, "verify_checkout", lambda path: None)
    return [
        "--hermes",
        str(host),
        "--hermes-python",
        sys.executable,
        "--output",
        str(tmp_path / "evidence"),
    ]


def test_default_only_plans_without_starting_or_writing(prepared, monkeypatch, capsys):
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *a, **k: pytest.fail("executed"))
    assert diagnostic.main(prepared) == 0
    assert not Path(prepared[-1]).exists()
    assert '"native_execution_requested": false' in capsys.readouterr().out


@pytest.mark.parametrize("deadline", ["0", "-1", "nan", "inf", "301"])
def test_invalid_deadline_fails_before_host_or_execution(prepared, deadline):
    with pytest.raises(SystemExit):
        diagnostic.main([*prepared, "--deadline", deadline])


def test_explicit_run_delegates_upstream_and_does_not_forward_secrets(prepared, monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")
    monkeypatch.setenv("HERMES_HOME", "/must/not/inherit")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert set(kwargs["env"]) <= {"PATH", "LANG", "TZ"}
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "HERMES_HOME" not in kwargs["env"]
        assert command[1].endswith("evals/shared_gateway/normal_boot.py")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(diagnostic.subprocess, "run", run)
    assert diagnostic.main([*prepared, "--run-native"]) == 1
    output = Path(prepared[-1])
    assert (output.stat().st_mode & 0o777) == 0o700
    assert (output / "diagnostic-python").stat().st_mode & 0o777 == 0o700
    assert (output / "PLAN.json").exists()
    with pytest.raises(FileExistsError):
        diagnostic.main([*prepared, "--run-native"])
    assert len(calls) == 1


def test_real_logger_renders_traceback_without_changing_failure(monkeypatch):
    import io
    import runpy

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger = logging.getLogger("gateway.control_socket")
    previous_factory = logging.getLogRecordFactory()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

    def module(*args, **kwargs):
        try:
            raise PermissionError(1, "synthetic bind-stage failure")
        except PermissionError as exc:
            logger.warning("Gateway control socket failed to start: %s", exc)
        return {"result": False}

    monkeypatch.setattr(runpy, "run_module", module)
    monkeypatch.setattr(sys, "argv", ["diagnostic-python", "-m", "gateway.run"])
    try:
        exec(diagnostic.diagnostic_launcher(Path(sys.executable)), {})
    finally:
        logging.setLogRecordFactory(previous_factory)
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()
    rendered = stream.getvalue()
    assert "Gateway control socket failed to start" in rendered
    assert "Traceback (most recent call last)" in rendered
    assert "PermissionError: [Errno 1] synthetic bind-stage failure" in rendered
    assert "raise PermissionError" in rendered
