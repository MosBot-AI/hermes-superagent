"""Exercise ignore behavior without creating operating-system metadata files."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def repository(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, timeout=10)
    shutil.copy2(Path(__file__).resolve().parents[2] / ".gitignore", tmp_path / ".gitignore")
    return tmp_path


@pytest.mark.parametrize(
    "paths",
    [
        [
            ".DS_Store",
            "nested/.DS_Store",
            "nested/._photo",
            ".AppleDouble/meta",
            ".Spotlight-V100/index",
            ".Trashes/501/file",
            "Network Trash Folder/item",
        ],
        [
            "Thumbs.db",
            "nested/thumbs.db",
            "Thumbs.db:encryptable",
            "ehthumbs_vista.db",
            "nested/Desktop.ini",
            "$RECYCLE.BIN/entry",
            "python.exe.stackdump",
        ],
    ],
)
def test_operating_system_files_are_ignored(repository, paths):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=repository,
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == paths


def test_source_and_project_metadata_remain_trackable(repository):
    paths = [
        "personal_agent/plugin.py",
        "plugin.yaml",
        "pyproject.toml",
        "docs/12-foundation-progress.md",
        ".github/workflows/check.yml",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=repository,
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert not result.stdout
