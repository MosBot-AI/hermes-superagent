"""Offline distribution integrity; no installer, activation or provider calls."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "runtime_builder", ROOT / "scripts/build_runtime_distribution.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "offline fixture",
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    files = json.loads((ROOT / builder.SPEC).read_text())["files"]
    for name in [*files, builder.SPEC, builder.BUILDER]:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
        path.chmod(0o644)
    return repo, commit(repo)


def test_reproducible_and_uncommitted_ignored(source, tmp_path):
    repo, sha = source
    (repo / "plugin.yaml").write_text("uncommitted tampering")
    first, second = tmp_path / "one", tmp_path / "two"
    builder.build(repo, sha, first)
    builder.build(repo, sha, second)
    builder.verify(repo, sha, first)
    assert {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()} == {
        p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()
    }
    assert "default: read_only" in (first / "plugin.yaml").read_text()
    assert "text_worker" not in (first / "__init__.py").read_text()
    assert not (first / "experiments").exists()
    manifest = json.loads((first / "PROVENANCE.json").read_text())
    assert manifest["source_commit"] == sha
    assert manifest["source_tree"] == git(repo, "rev-parse", "HEAD^{tree}")
    assert len(manifest["files"]) == 45


@pytest.mark.parametrize(
    "kind", ["bytes", "extra", "missing", "mode", "symlink", "manifest", "fifo", "directory"]
)
def test_tampering_rejected(source, tmp_path, kind):
    repo, sha = source
    out = tmp_path / "out"
    builder.build(repo, sha, out)
    target = out / "plugin.yaml"
    if kind == "bytes":
        target.write_text("bad")
    elif kind == "extra":
        (out / "extra").write_text("bad")
    elif kind == "missing":
        target.unlink()
    elif kind == "mode":
        target.chmod(0o755)
    elif kind == "symlink":
        target.unlink()
        target.symlink_to(repo / "plugin.yaml")
    elif kind == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif kind == "directory":
        (out / "undeclared").mkdir()
    else:
        (out / "PROVENANCE.json").write_text("{}")
    with pytest.raises(ValueError):
        builder.verify(repo, sha, out)


@pytest.mark.parametrize("kind", ["addition", "symlink", "executable", "missing", "builder"])
def test_source_rejected(source, tmp_path, kind):
    repo, _ = source
    target = repo / "personal_agent/plugin.py"
    if kind == "addition":
        (repo / "personal_agent/unreviewed.py").write_text("pass")
    elif kind == "symlink":
        target.unlink()
        target.symlink_to("tasks.py")
    elif kind == "executable":
        target.chmod(0o755)
    elif kind == "missing":
        target.unlink()
    else:
        (repo / builder.BUILDER).write_text("# altered builder")
    sha = commit(repo)
    with pytest.raises(ValueError):
        builder.build(repo, sha, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_destination_and_revision_refusals(source, tmp_path):
    repo, sha = source
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        builder.build(repo, sha, existing)
    link = tmp_path / "link"
    link.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError):
        builder.build(repo, sha, link / "new")
    with pytest.raises(ValueError):
        builder.build(repo, "HEAD", tmp_path / "out")


def test_git_replace_cannot_substitute_pinned_source(source, tmp_path):
    repo, original = source
    original_tree = git(repo, "rev-parse", f"{original}^{{tree}}")
    original_manifest = (repo / "plugin.yaml").read_bytes()
    (repo / "plugin.yaml").write_text("substituted content")
    replacement = commit(repo)
    git(repo, "replace", original, replacement)
    # Establish that ordinary Git reads really are being redirected.
    assert git(repo, "show", f"{original}:plugin.yaml") == "substituted content"
    output = tmp_path / "export"
    builder.build(repo, original, output)
    builder.verify(repo, original, output)
    assert (output / "plugin.yaml").read_bytes() == original_manifest
    provenance = json.loads((output / "PROVENANCE.json").read_text())
    assert provenance["source_commit"] == original
    assert provenance["source_tree"] == original_tree
