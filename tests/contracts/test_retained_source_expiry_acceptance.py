"""Run the original-deadline composition in the ordinary pinned-host CI lane."""

import tempfile
from pathlib import Path

import hermes_cli.plugins
from hermes_constants import (
    get_hermes_home_override,
    reset_hermes_home_override,
    set_hermes_home_override,
)

from acceptance.memory.expiry import evaluate


def test_registered_recall_retained_original_expiry_and_recovery(tmp_path, monkeypatch):
    hermes = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    # Exercise an inherited task-local profile context under bare pytest too,
    # and verify the supported context manager restores it.
    # The official runner can use /var/tmp as an alias of /tmp. Always exercise
    # an aliased temporary root so canonical profile binding is not platform-lucky.
    real_temp = tmp_path / "real-temp"
    real_temp.mkdir()
    alias = tmp_path / "temp-alias"
    alias.symlink_to(real_temp.resolve(), target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(alias))
    inherited = str(tmp_path / "inherited-host-profile")
    token = set_hermes_home_override(inherited)
    try:
        report = evaluate(hermes)
        assert get_hermes_home_override() == inherited
    finally:
        reset_hermes_home_override(token)
    assert not Path(inherited).exists()
    assert report["passed"]
    assert [stage["id"] for stage in report["stages"]] == [
        "before",
        "deadline",
        "after",
        "cleanup",
        "normal-repack",
        "interrupted-repack",
    ]
    assert len({pid for stage in report["stages"] for pid in stage["process_ids"]}) == 12
