"""The independent comparison must not hide query-level regressions."""

import pytest

from scripts.compare_automatic_recall import compare_rows


def row(key="q", *, retrieved=(), relevant=("a",), query="question"):
    return {"id": key, "retrieved": list(retrieved), "relevant": list(relevant), "query": query}


def test_compare_tracks_losses_gains_and_irrelevance_separately():
    result = compare_rows(
        [row(retrieved=("a", "noise"), relevant=("a", "b"))],
        [row(retrieved=("b", "other"), relevant=("a", "b"))],
    )
    assert result["regressed_query_ids"] == ["q"]
    assert result["new_irrelevant_query_ids"] == ["q"]
    change = result["changed_queries"][0]
    assert change["lost_relevant"] == ["a"]
    assert change["gained_relevant"] == ["b"]
    assert change["removed_irrelevant"] == ["noise"]
    assert change["added_irrelevant"] == ["other"]


@pytest.mark.parametrize(
    "after",
    [
        [row("other")],
        [row(), row()],
        [row(relevant=("b",))],
        [row(query="changed")],
    ],
)
def test_compare_rejects_changed_labels_queries_or_ids(after):
    with pytest.raises(ValueError):
        compare_rows([row()], after)


def test_compare_reordering_is_not_a_lost_pair():
    result = compare_rows([row(retrieved=("a", "b"))], [row(retrieved=("b", "a"))])
    assert len(result["changed_queries"]) == 1
    assert result["regressed_query_ids"] == []
    assert compare_rows([row()], [row()])["changed_queries"] == []


def artifacts(tmp_path):
    import json

    from scripts.compare_automatic_recall import STRATEGY

    for version in ("base", "candidate"):
        for fixture in ("chinese_recall_eval", "automatic_recall_holdout"):
            (tmp_path / f"{version}-{fixture}.json").write_text(
                json.dumps(
                    {
                        "fixture_sha256": "frozen",
                        "records": 38,
                        "latency_definition": "Synthetic 28-record corpus",
                        "systems": {
                            STRATEGY: {"rows": [row(retrieved=("a",))]},
                            "baseline_1740a85": {"rows": [row(retrieved=("wrong",))]},
                        },
                    }
                )
            )
        (tmp_path / f"{version}-longitudinal.json").write_text(
            json.dumps(
                {
                    "fixture_sha256": "frozen-longitudinal",
                    "stages": [{"id": "stage", "rows": [row()]}],
                }
            )
        )


def test_build_report_selects_current_automatic_behavior(tmp_path):
    from scripts.compare_automatic_recall import build_report

    artifacts(tmp_path)
    result = build_report(tmp_path)
    for fixture in result["fixtures"].values():
        for version in ("base", "candidate"):
            assert fixture[version]["automatic_behavior"]["rows"][0]["retrieved"] == ["a"]
            assert fixture[version]["latency_definition"] == "Synthetic 38-record corpus"
    assert len(result["input_artifact_sha256"]) == 6
    assert all(len(value) == 64 for value in result["input_artifact_sha256"].values())


@pytest.mark.parametrize("name", ["chinese_recall_eval", "longitudinal"])
def test_build_report_rejects_mismatched_fixture_hash(tmp_path, name):
    import json

    from scripts.compare_automatic_recall import build_report

    artifacts(tmp_path)
    path = tmp_path / f"candidate-{name}.json"
    data = json.loads(path.read_text())
    data["fixture_sha256"] = "changed"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fixture hashes differ"):
        build_report(tmp_path)


def test_build_report_includes_additional_independent_fixture(tmp_path):
    from scripts.compare_automatic_recall import FIXTURES, build_report

    artifacts(tmp_path)
    for version in ("base", "candidate"):
        source = tmp_path / f"{version}-automatic_recall_holdout.json"
        (tmp_path / f"{version}-confirmation.json").write_bytes(source.read_bytes())
    report = build_report(tmp_path, (*FIXTURES, "confirmation"))
    assert "confirmation" in report["fixtures"]
    assert len(report["input_artifact_sha256"]) == 8


def test_build_report_preserves_prior_evidence_and_design_notes(tmp_path):
    import hashlib

    from scripts.compare_automatic_recall import build_report

    artifacts(tmp_path)
    prior = tmp_path / "earlier.json"
    prior.write_text('{"observation": "regression"}')
    report = build_report(tmp_path, prior_comparisons=[prior], notes=["Development validation"])
    assert report["evaluation_notes"] == ["Development validation"]
    assert report["prior_comparisons"] == [
        {
            "filename": "earlier.json",
            "sha256": hashlib.sha256(prior.read_bytes()).hexdigest(),
            "report": {"observation": "regression"},
        }
    ]


def test_prior_compaction_keeps_losses_and_disclosure(tmp_path):
    from scripts.compare_automatic_recall import build_report, summarize_prior

    artifacts(tmp_path)
    report = build_report(tmp_path, notes=["First fixture informed narrowing"])
    fixture = report["fixtures"]["automatic_recall_holdout"]
    fixture.update(compare_rows([row(retrieved=("a",))], [row()]))
    compact = summarize_prior(report)
    assert compact["evaluation_notes"] == report["evaluation_notes"]
    evidence = compact["fixtures"]["automatic_recall_holdout"]
    assert evidence["regressed_query_ids"] == ["q"]
    assert evidence["changed_queries"][0]["lost_relevant"] == ["a"]
    assert "rows" not in evidence["candidate"]["automatic_behavior"]
    assert compact["input_artifact_sha256"] == report["input_artifact_sha256"]


def test_base_reference_checks_identity_and_outcomes(tmp_path):
    import json

    from scripts.compare_automatic_recall import reference_base

    source = {
        "fixture_sha256": "frozen",
        "source_sha256": {"source": "digest"},
        "harness_sha256": "harness",
        "head": "historical",
        "stages": [
            {
                "id": "stage",
                "metrics_all_37": {"hits": 1},
                "rows": [row(retrieved=("a",))],
                "hard_invariants_passed": True,
            }
        ],
    }
    path = tmp_path / "historical.json"
    path.write_text(json.dumps(source))
    compact = reference_base(source, path)
    assert "rows" not in compact["stages"][0]
    assert compact["stages"][0]["hard_invariants_passed"]
    assert compact["full_evidence_reference"]["historical_head"] == "historical"
    source["stages"][0]["rows"][0]["retrieved"] = []
    with pytest.raises(ValueError, match="outcomes differ"):
        reference_base(source, path)
    source["source_sha256"] = {"source": "wrong"}
    with pytest.raises(ValueError, match="identity mismatch"):
        reference_base(source, path)
