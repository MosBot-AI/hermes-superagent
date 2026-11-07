#!/usr/bin/env python3
"""Print an offline fixture report. Does not run Hermes or call any provider."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personal_agent.routing_shadow import ShadowFixtureError, evaluate_shadow_fixture  # noqa: E402


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ShadowFixtureError("invalid_shadow_fixture")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Synthetic JSON fixture (at most 64 KiB)")
    args = parser.parse_args()
    try:
        with args.fixture.open("rb") as source:
            content = source.read(65537)
        if len(content) > 65536:
            raise ShadowFixtureError("invalid_shadow_fixture")
        report = evaluate_shadow_fixture(
            json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
        )
    except OSError, ValueError, RecursionError:
        # Do not echo source contents or paths into a potentially retained report.
        print(json.dumps({"status": "invalid", "reason": "invalid_shadow_fixture"}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "advisory" else 1


if __name__ == "__main__":
    raise SystemExit(main())
