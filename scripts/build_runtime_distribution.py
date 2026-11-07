#!/usr/bin/env python3
"""Export an auditable standalone plugin from a committed source, without installing it."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

SPEC = "packaging/runtime-files.json"
BUILDER = "scripts/build_runtime_distribution.py"
ROOT_FILES = {
    "__init__.py",
    "plugin.yaml",
    "pyproject.toml",
    "compatibility.json",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "THIRD_PARTY_NOTICES-zh.md",
    "docs/runtime-distribution.md",
    "docs/runtime-distribution-zh.md",
}


def git(repo, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(repo), *args], timeout=30
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def payload(repo, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source must be a full lowercase commit SHA")
    if git(repo, "cat-file", "-t", commit).strip() != b"commit":
        raise ValueError("source must identify a commit")
    entries = {}
    for record in git(repo, "ls-tree", "-rz", commit).split(b"\0"):
        if record:
            header, name = record.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            entries[name.decode()] = (mode, kind, oid)

    def blob(path):
        if path not in entries or entries[path][:2] != ("100644", "blob"):
            raise ValueError(f"missing or unsafe source file: {path}")
        return git(repo, "cat-file", "blob", entries[path][2])

    spec_bytes = blob(SPEC)
    spec = json.loads(spec_bytes)
    files = spec.get("files")
    if (
        set(spec) != {"schema_version", "files"}
        or spec["schema_version"] != 1
        or not isinstance(files, list)
        or not all(isinstance(p, str) for p in files)
        or files != sorted(set(files))
    ):
        raise ValueError("invalid explicit file specification")
    runtime = {p for p in entries if p.startswith("personal_agent/")}
    if any(not re.fullmatch(r"personal_agent/[a-z_]+\.py", p) for p in runtime):
        raise ValueError("unexpected runtime file")
    if set(files) != ROOT_FILES | runtime:
        raise ValueError("undeclared runtime addition or unexpected package file")
    builder = blob(BUILDER)
    if builder != Path(__file__).read_bytes():
        raise ValueError("run the exact builder from the pinned source commit")
    data = {path: blob(path) for path in files}
    manifest = {
        "schema_version": 1,
        "package": "hermes-personal-agent",
        "version": tomllib.loads(data["pyproject.toml"].decode())["project"]["version"],
        "source_repository": "https://github.com/MosBot-AI/hermes-superagent",
        "source_commit": commit,
        "source_tree": git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip(),
        "builder": {"path": BUILDER, "sha256": digest(builder)},
        "specification": {"path": SPEC, "sha256": digest(spec_bytes)},
        "compatibility": json.loads(data["compatibility.json"]),
        "files": [
            {"path": p, "source_path": p, "bytes": len(b), "mode": "100644", "sha256": digest(b)}
            for p, b in data.items()
        ],
        "excluded": [
            "research docs",
            "tests",
            "scripts",
            "experiments",
            "optional provider packaging",
        ],
    }
    data["PROVENANCE.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    return data


def build(repo, commit, destination):
    data = payload(repo, commit)
    destination = Path(destination).absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("destination must not traverse symlinks")
    # Exclusive creation: never merge into or overwrite an existing tree.
    destination.mkdir(mode=0o755)
    try:
        for path, content in data.items():
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content)
            target.chmod(0o644)
    except BaseException:
        shutil.rmtree(destination)
        raise


def verify(repo, commit, destination):
    expected = payload(repo, commit)
    destination = Path(destination).absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("unsafe distribution path")
    actual = set()
    expected_dirs = {
        str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."
    }
    for path in destination.rglob("*"):
        if path.is_symlink():
            raise ValueError("distribution contains symlink")
        if path.is_dir():
            if path.relative_to(destination).as_posix() not in expected_dirs:
                raise ValueError("unexpected distribution directory")
            continue
        relative = path.relative_to(destination).as_posix()
        if (
            not path.is_file()
            or path.stat().st_mode & 0o7777 != 0o644
            or relative not in expected
            or path.read_bytes() != expected[relative]
        ):
            raise ValueError(f"distribution integrity mismatch: {relative}")
        actual.add(relative)
    if actual != set(expected):
        raise ValueError("distribution files missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    (verify if args.verify else build)(args.repo, args.source_commit, args.output_dir)


if __name__ == "__main__":
    main()
