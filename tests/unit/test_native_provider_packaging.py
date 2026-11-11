"""Optional packaging does not turn default plugin admission into package installation."""

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_provider_build_is_separate_and_contains_only_source(tmp_path):
    main = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "build-system" not in main
    assert "entry-points" not in main["project"]
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_native_memory_provider.py"),
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        assert "personal_agent/native_memory_provider.py" in names
        assert "personal_agent/memory_lifecycle.py" in names
        assert "personal_agent/memory_mutation_status.py" in names
        assert all(
            name.startswith(("personal_agent/", "hermes_personal_agent-0.1.0.dist-info/"))
            for name in names
        )
        metadata = next(name for name in names if name.endswith("entry_points.txt"))
        assert (
            "personal-records = personal_agent.native_memory_provider:register"
            in archive.read(metadata).decode()
        )
        for name in (
            "personal_agent/native_memory_provider.py",
            "personal_agent/memory_lifecycle.py",
        ):
            assert archive.read(name) == (ROOT / name).read_bytes()
