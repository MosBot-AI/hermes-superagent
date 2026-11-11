#!/usr/bin/env python3
"""Compare current automatic behavior in two frozen evaluator result sets.

Run evaluate_memory_recall.py in each clean revision for both fixtures, and
save as {base,candidate}-{chinese_recall_eval,automatic_recall_holdout}.json.
Also run evaluate_longitudinal_memory.py in each revision and save as
{base,candidate}-longitudinal.json. This tool never uses baseline_1740a85.
"""

import argparse
import hashlib
import json
from pathlib import Path

STRATEGY = "candidate_conservative"
FIXTURES = ("chinese_recall_eval", "automatic_recall_holdout")


def compare_rows(before, after):
    """Expose pair losses even when aggregate gains conceal a regression."""
    old = {row["id"]: row for row in before}
    new = {row["id"]: row for row in after}
    if len(old) != len(before) or len(new) != len(after) or old.keys() != new.keys():
        raise ValueError("query identities differ or repeat")
    changes = []
    for key, first in old.items():
        second = new[key]
        if first["query"] != second["query"] or first["relevant"] != second["relevant"]:
            raise ValueError("query text or frozen relevance changed")
        relevant = set(first["relevant"])
        left, right = set(first["retrieved"]), set(second["retrieved"])
        if first["retrieved"] != second["retrieved"]:
            changes.append(
                {
                    "id": key,
                    "lost_relevant": sorted((left - right) & relevant),
                    "gained_relevant": sorted((right - left) & relevant),
                    "added_irrelevant": sorted((right - left) - relevant),
                    "removed_irrelevant": sorted((left - right) - relevant),
                    "before": first,
                    "after": second,
                }
            )
    return {
        "changed_queries": changes,
        "regressed_query_ids": [r["id"] for r in changes if r["lost_relevant"]],
        "new_irrelevant_query_ids": [r["id"] for r in changes if r["added_irrelevant"]],
    }


def summarize_longitudinal(report):
    """Retain run identity, metrics and invariant evidence without repeated contexts."""
    return {
        **report,
        "stages": [
            {
                key: value
                for key, value in stage.items()
                if key not in {"rows", "repeat_rows", "repack_rows"}
            }
            for stage in report["stages"]
        ],
    }


def summarize_prior(report):
    """Keep historical losses and hashes, not duplicate unchanged query envelopes."""
    if "fixtures" not in report:
        return report
    result = {**report, "fixtures": {}, "longitudinal": dict(report["longitudinal"])}
    for name, fixture in report["fixtures"].items():
        result["fixtures"][name] = dict(fixture)
        for version in ("base", "candidate"):
            source = fixture[version]
            result["fixtures"][name][version] = {
                **source,
                "automatic_behavior": {
                    key: value
                    for key, value in source["automatic_behavior"].items()
                    if key != "rows"
                },
            }
    for version in ("base", "candidate"):
        result["longitudinal"][version] = summarize_longitudinal(report["longitudinal"][version])
    for change in result["longitudinal"]["stage_changes"]:
        for row in change["changed_queries"]:
            for version in ("before", "after"):
                row[version] = {
                    key: value for key, value in row[version].items() if key != "context"
                }
    return result


def reference_base(report, path):
    """Verify historical evidence matches rerun source and semantic retrieval outcomes."""
    raw = path.read_bytes()
    historical = json.loads(raw)
    for key in ("fixture_sha256", "source_sha256", "harness_sha256"):
        if report[key] != historical[key]:
            raise ValueError("historical base identity mismatch: " + key)
    if [s["id"] for s in report["stages"]] != [s["id"] for s in historical["stages"]]:
        raise ValueError("historical base stages differ")
    for current, old in zip(report["stages"], historical["stages"], strict=True):
        if current["metrics_all_37"] != old["metrics_all_37"]:
            raise ValueError("historical base metrics differ")
        if compare_rows(old["rows"], current["rows"])["changed_queries"]:
            raise ValueError("historical base outcomes differ")
    return {
        **summarize_longitudinal(report),
        "full_evidence_reference": {
            "path": "docs/" + path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "historical_head": historical["head"],
            "verified": "Same production/harness hashes, fixture, metrics and all query outcomes. "
            "Historical timestamps, process identifiers and timings are not this rerun.",
        },
    }


def build_report(
    directory,
    fixture_names=FIXTURES,
    *,
    prior_comparisons=(),
    notes=(),
    base_longitudinal_reference=None,
):
    artifacts = {}

    def read(name):
        raw = (directory / name).read_bytes()
        artifacts[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    report = {
        "scope": "Synthetic retrieval only; no models, deployment or population claims.",
        "selected_strategy": STRATEGY,
        "strategy_explanation": "The historical evaluator calls current automatic behavior "
        "candidate_conservative in BOTH revisions. baseline_1740a85 is not the base comparator.",
        "evaluation_notes": list(notes),
        "prior_comparisons": [],
        "fixtures": {},
        "longitudinal": {},
        "input_artifact_sha256": artifacts,
        "comparison_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    for fixture in fixture_names:
        before = read(f"base-{fixture}.json")
        after = read(f"candidate-{fixture}.json")
        if before["fixture_sha256"] != after["fixture_sha256"]:
            raise ValueError("fixture hashes differ")
        selected = {}
        for label, source in (("base", before), ("candidate", after)):
            selected[label] = {key: value for key, value in source.items() if key != "systems"}
            selected[label]["automatic_behavior"] = source["systems"][STRATEGY]
            selected[label]["latency_definition"] = source["latency_definition"].replace(
                "Synthetic 28-record corpus", f"Synthetic {source['records']}-record corpus"
            )
        report["fixtures"][fixture] = {
            **selected,
            **compare_rows(before["systems"][STRATEGY]["rows"], after["systems"][STRATEGY]["rows"]),
        }
    before = read("base-longitudinal.json")
    after = read("candidate-longitudinal.json")
    if before["fixture_sha256"] != after["fixture_sha256"]:
        raise ValueError("longitudinal fixture hashes differ")
    if [s["id"] for s in before["stages"]] != [s["id"] for s in after["stages"]]:
        raise ValueError("longitudinal stages differ")
    report["longitudinal"] = {
        "base": reference_base(before, base_longitudinal_reference)
        if base_longitudinal_reference
        else before,
        "candidate": after,
        "stage_changes": [
            {"id": first["id"], **compare_rows(first["rows"], second["rows"])}
            for first, second in zip(before["stages"], after["stages"], strict=True)
        ],
    }
    for path in prior_comparisons:
        raw = path.read_bytes()
        report["prior_comparisons"].append(
            {
                "filename": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "report": summarize_prior(json.loads(raw)),
            }
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument(
        "--additional-fixture",
        action="append",
        default=[],
        help="Additional independently frozen fixture basename; repeat as needed",
    )
    parser.add_argument("--prior-comparison", type=Path, action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--base-longitudinal-reference", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build_report(
                args.results_dir,
                (*FIXTURES, *args.additional_fixture),
                prior_comparisons=args.prior_comparison,
                notes=args.note,
                base_longitudinal_reference=args.base_longitudinal_reference,
            ),
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
