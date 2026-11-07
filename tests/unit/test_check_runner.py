"""Checks preserve external plugin imports through a hermetic host runner."""

import subprocess
import sys

import pytest

from scripts import check


@pytest.mark.parametrize("sentinel", [42, 0])
def test_native_contracts_import_the_plugin_after_environment_scrub(
    tmp_path, monkeypatch, sentinel
):
    root = tmp_path / "external plugin"
    contracts = root / "tests" / "contracts"
    contracts.mkdir(parents=True)
    (root / "personal_agent").mkdir()
    (root / "personal_agent" / "__init__.py").write_text(f"SENTINEL = {sentinel}\n")
    (contracts / "test_import.py").write_text(
        "from personal_agent import SENTINEL\ndef test_import():\n    assert SENTINEL == 42\n"
    )
    checkout = tmp_path / "host checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    # Model the host's documented env -i boundary, retaining only pytest argv.
    (scripts / "run_tests.sh").write_text(
        '#!/bin/sh\ncontract_path="$1"\nshift 3\n'
        'if [ "$1" = "--" ]; then shift; fi\n'
        'exec env -i PATH="$PATH" HOME="$HOME" '
        '"$HERMES_PYTHON" -m pytest "$contract_path" "$@"\n'
    )
    monkeypatch.setattr(check, "ROOT", root)
    monkeypatch.setattr(check, "verify_checkout", lambda checkout: None)
    monkeypatch.setattr(check, "record_environment", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["check.py", "--hermes", str(checkout), "--hermes-python", sys.executable],
    )
    actual_run = check.run
    executed = []

    def native_only(command, **kwargs):
        if command[0] == "bash":
            executed.append(command)
            actual_run(command, **kwargs)

    monkeypatch.setattr(check, "run", native_only)
    if sentinel == 42:
        assert check.main() == 0
    else:
        with pytest.raises(subprocess.CalledProcessError) as error:
            check.main()
        assert error.value.returncode == 1
    assert len(executed) == 1
