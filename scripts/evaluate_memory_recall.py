#!/usr/bin/env python3
"""Offline fixed-label record retrieval comparison, never model answer evaluation."""

import argparse
import hashlib
import json
import math
import os
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from personal_agent.local_memory import create_backend  # noqa: E402
from personal_agent.memory_backend import MemoryError, MemoryService, _text  # noqa: E402
from personal_agent.memory_lifecycle import literal_terms  # noqa: E402
from personal_agent.memory_query import filter_automatic_recall  # noqa: E402


def baseline_terms(query):
    """Frozen literal_terms implementation from baseline 1740a85."""
    if type(query) is not str or len(query) > 2048 or query.lstrip().startswith("/"):
        return []
    try:
        _text(query, 2048, empty=True, multiline=True)
    except MemoryError:
        return []
    terms = []
    for term in re.findall(r"[^\W_]+(?:[-_][^\W_]+)*", query):
        if len(term) <= 128 and term not in terms:
            terms.append(term)
            if len(terms) == 8:
                break
    return terms


@contextmanager
def opened(path, *, readonly=False):
    uri = path.as_uri() + "?mode=ro" if readonly else str(path)
    conn = sqlite3.connect(uri, uri=readonly, isolation_level=None)
    backend = create_backend()
    try:
        method = backend.open_readonly if readonly else backend.open
        method(conn, namespace_id="synthetic-eval", session_ref="eval")
        yield MemoryService(backend)
    finally:
        backend.close()
        conn.close()


def populate(path, fixture):
    identifiers = {}
    with opened(path) as service:
        for record in fixture["records"]:
            request = {key: record[key] for key in ("content", "topic")}
            request["request_id"] = "remember-" + record["id"]
            expiry = fixture["expiry"].get(record["id"])
            if expiry:
                request["expires_at"] = expiry
            identifiers[record["id"]] = service.execute("remember", request)["data"]["record_id"]
        for mutation in fixture["mutations"]:
            request = {
                "record_id": identifiers[mutation["id"]],
                "expected_revision": 1,
                "request_id": mutation["op"] + "-" + mutation["id"],
            }
            if "content" in mutation:
                request["content"] = mutation["content"]
            service.execute(mutation["op"], request)
    return {value: key for key, value in identifiers.items()}


def retrieve(service, strategy, query, reverse):
    tokenizer = baseline_terms if strategy == "baseline_1740a85" else literal_terms
    terms = tokenizer(query)
    if not terms:
        return terms, []
    data = service.execute("recall", {"queries": terms, "limit": 6, "max_chars": 4976})["data"]
    if strategy == "candidate_conservative":
        data = filter_automatic_recall(data, query, terms)
    return terms, [reverse[item["record_id"]] for item in data["items"]]


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def metrics(rows):
    result = {}
    for k in (1, 3, 6):
        tp = sum(len(set(row["retrieved"][:k]) & set(row["relevant"])) for row in rows)
        returned = sum(len(row["retrieved"][:k]) for row in rows)
        relevant = sum(len(row["relevant"]) for row in rows)
        result[str(k)] = {
            "micro_precision_returned": tp / returned if returned else None,
            "micro_recall": tp / relevant,
            "precision_fixed_k": tp / (k * len(rows)),
            "true_positives": tp,
            "returned": returned,
            "relevant": relevant,
        }
    positives = [row for row in rows if row["relevant"]]
    negatives = [row for row in rows if not row["relevant"]]
    result.update(
        {
            "positive_queries": len(positives),
            "negative_queries": len(negatives),
            "positive_empty": sum(not row["retrieved"] for row in positives),
            "positive_zero_hit": sum(
                not set(r["retrieved"]) & set(r["relevant"]) for r in positives
            ),
            "negative_false_recall": sum(bool(row["retrieved"]) for row in negatives),
            "queries_with_irrelevant_results": sum(
                bool(set(row["retrieved"]) - set(row["relevant"])) for row in rows
            ),
        }
    )
    return result


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", type=Path, default=ROOT / "tests/fixtures/chinese_recall_eval.json"
    )
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    raw = args.fixture.read_bytes()
    fixture = json.loads(raw)
    report = {
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": fixture["scope"],
        "clock": fixture["clock"],
        "records": len(fixture["records"]),
        "queries": len(fixture["queries"]),
        "repeats": args.repeats,
        "environment": {
            "head": git("rev-parse", "HEAD"),
            "production_source_sha256": {
                str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((ROOT / "personal_agent").glob("*.py"))
            },
            "worktree_diff_sha256": hashlib.sha256(
                git("diff", "--", "personal_agent").encode()
            ).hexdigest(),
            "python": sys.version,
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "cpu_model": next(
                (
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                platform.processor(),
            )
            if Path("/proc/cpuinfo").exists()
            else platform.processor(),
        },
        "latency_definition": "Milliseconds, nearest-rank percentiles. Cold = fresh read-only "
        "connection + schema validation + tokenization + recall + close; "
        "OS page cache NOT flushed. "
        "Warm = tokenization + recall on retained connection. No model, lifecycle admission or "
        "context envelope. Synthetic 28-record corpus, not production latency.",
        "systems": {},
    }
    with tempfile.TemporaryDirectory(prefix="hermes-recall-eval-") as temporary:
        path = Path(temporary) / "records.sqlite3"
        with patch("personal_agent.memory_expiry.utc_now", return_value=fixture["clock"]):
            reverse = populate(path, fixture)
            for name in ("baseline_1740a85", "experiment_ungated", "candidate_conservative"):
                rows, cold, warm = [], [], []
                with opened(path, readonly=True) as service:
                    for query in fixture["queries"]:
                        terms, ids = retrieve(service, name, query["query"], reverse)
                        rows.append(
                            {
                                **query,
                                "terms": terms,
                                "retrieved": ids,
                                "missed": sorted(set(query["relevant"]) - set(ids)),
                                "irrelevant": sorted(set(ids) - set(query["relevant"])),
                            }
                        )
                    for _ in range(args.repeats):
                        for query in fixture["queries"]:
                            start = time.perf_counter_ns()
                            retrieve(service, name, query["query"], reverse)
                            warm.append((time.perf_counter_ns() - start) / 1e6)
                            start = time.perf_counter_ns()
                            with opened(path, readonly=True) as reader:
                                retrieve(reader, name, query["query"], reverse)
                            cold.append((time.perf_counter_ns() - start) / 1e6)
                report["systems"][name] = {
                    "metrics": metrics(rows),
                    "rows": rows,
                    "latency_ms": {
                        label: {
                            "p50": percentile(samples, 0.5),
                            "p95": percentile(samples, 0.95),
                            "n": len(samples),
                        }
                        for label, samples in (("cold_connection", cold), ("warm", warm))
                    },
                }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
