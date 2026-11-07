#!/usr/bin/env python3
"""Build the optional provider wheel without installing it or downloading packages.

Staging prevents the standalone plugin's pyproject from triggering host package
installation. Only project-owned source and license files enter the wheel build.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="personal-native-provider-") as temporary:
        stage = Path(temporary)
        shutil.copy2(ROOT / "packaging/native-memory-provider.toml", stage / "pyproject.toml")
        shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
        shutil.copytree(
            ROOT / "personal_agent",
            stage / "personal_agent",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import setuptools.build_meta,sys; setuptools.build_meta.build_wheel(sys.argv[1])",
                str(output),
            ],
            cwd=stage,
            check=True,
            timeout=120,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
