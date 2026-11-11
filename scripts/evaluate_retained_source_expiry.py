#!/usr/bin/env python3
"""Run synthetic original-source expiry composition on the pinned native host."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acceptance.memory.expiry import main  # noqa: E402

if __name__ == "__main__":
    main()
