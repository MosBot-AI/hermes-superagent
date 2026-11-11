"""Compose original retained deadlines with registered recall and reviewed cleanup."""

import argparse
import json
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from acceptance.memory import retained, runner
from personal_agent import memory_expiry, memory_storage
from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_sdk import source_request_identity

ROOT = runner.ROOT
FIXTURE = ROOT / "tests/fixtures/retained_source_expiry.json"


@contextmanager
def opened(home, clock, source_kind="explicit_local_operator"):
    # The official host runner can carry a context-local profile override. Use the
    # supported host API so both the plugin and host storage resolve the same profile;
    # an environment-only switch cannot override that context.
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(home)
    try:
        with (
            patch.object(memory_expiry, "utc_now", return_value=clock),
            memory_storage.open_memory_backend(
                home, "synthetic-expiry", source_kind=source_kind
            ) as b,
        ):
            yield MemoryService(b)
    finally:
        reset_hermes_home_override(token)


def requests(fixture):
    result = []
    for row in fixture["sources"]:
        key = row["id"]
        source = {
            "identity": retained._hash("expiry:" + key),
            "fingerprint": retained._hash(row["content"]),
            "role": row["role"],
        }
        if key == "legacy":
            source["receipt_id"] = retained._hash("receipt:" + key)
        else:
            source.update(kind="observed_native_snapshot", observation_id=retained._hash(key))
        result.append(
            {
                "request_id": key,
                "consumer_id": key,
                "expected_sequence": 0,
                "content": row["content"],
                "topic": "synthetic expiry",
                "expires_at": fixture["deadline"],
                "retention": "independent_snapshot",
                "source": source,
            }
        )
    return result


def check_receipt(request, receipt):
    expected = {"kind": "retained_native_snapshot", **request["source"]}
    runner.require(
        receipt["source"] == expected
        and receipt["state"] == "accepted"
        and receipt["request_id"] == request["request_id"]
        and receipt["consumer_id"] == request["consumer_id"]
        and receipt["source_sequence"] == request["expected_sequence"] + 1,
        "original receipt provenance mismatch",
    )
    record = receipt["record"]
    runner.require(
        record["status"] == "active"
        and record["revision"] == 1
        and record["operation"] == "remember"
        and record["request_id"] == "source.accept." + retained._hash(request["request_id"]),
        "original receipt is not historical active revision one",
    )


def check_preview(preview, oracle, selected):
    runner.require(
        preview["items"] == [oracle[rid] for rid in selected],
        "cleanup preview differs from complete canonical SQL oracle",
    )
    runner.require(
        preview["selected_count"] == preview["eligible_count"] == len(selected)
        and preview["remaining_count"] == 0,
        "cleanup preview counts changed",
    )
    runner.require(
        len(json.dumps(preview, ensure_ascii=True, sort_keys=True)) <= 64000,
        "complete cleanup preview budget overflow",
    )


def check_forgotten_fts(home):
    with sqlite3.connect(retained._path(home).as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT r.record_id FROM records r JOIN memory_fts f ON f.rowid=r.sequence "
            "WHERE r.status='forgotten'"
        ).fetchall()
    runner.require(not rows, "forgotten payload remains in FTS")


def evidence(home):
    """Direct SQL evidence, independent of source-status and maintenance digests."""
    with sqlite3.connect(retained._path(home).as_uri() + "?mode=ro", uri=True) as connection:
        return retained._logical_tables(connection)


def unchanged(home, baseline):
    runner.require(evidence(home) == baseline, "logical state/receipts/cursors changed")


def canonical(home, clock):
    with sqlite3.connect(retained._path(home).as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute("SELECT * FROM records")]
    for row in rows:
        row.pop("sequence")
    return {
        row["record_id"]: {**row, "expired": bool(row["expires_at"] and row["expires_at"] <= clock)}
        for row in rows
    }


def verify_sample(sample, oracle, clock, identifiers, expected):
    runner.require(sample["records"] == oracle, "canonical SQL oracle mismatch")
    runner.require(len(sample["rows"]) == 1, "missing recall probe")
    row = sample["rows"][0]
    runner.require(set(row["retrieved"]) == set(expected), "stale or missing recall")
    raw = json.dumps(row["context"], ensure_ascii=True) if row["context"] else None
    runner.check_context(raw, oracle, clock)
    runner.require(row["context"] is not None, "non-vacuity: permanent anchor disappeared")
    actual = {item["record_id"] for item in row["context"]["memory"]["items"]}
    runner.require(actual == {identifiers[key] for key in expected}, "incorrect envelope IDs")


def refuse(service, operation, payload, code):
    try:
        service.execute(operation, payload)
    except MemoryError as error:
        runner.require(error.code == code, f"expected {code}, got {error.code}")
    else:
        raise AssertionError("unsafe operation succeeded: " + operation)


def verify_terminal(home, clock, sources, receipts, cleanup, cleanup_receipt):
    baseline = evidence(home)
    check_forgotten_fts(home)
    outcomes = []
    with opened(home, clock) as service:
        runner.require(
            service.execute("forget_expired", cleanup)
            == {
                "data": cleanup_receipt,
                "replayed": True,
            },
            "cleanup exact retry changed",
        )
        for request, receipt in zip(sources, receipts, strict=True):
            check_receipt(request, receipt)
            status = service.execute("source_status", source_request_identity(request))["data"]
            runner.require(status["decision"] == receipt, "historical source receipt changed")
            runner.require(
                status["current"]
                == {
                    "record_id": receipt["record"]["record_id"],
                    "revision": 2,
                    "status": "forgotten",
                    "expired": False,
                }
                and status["suppressed"],
                "terminal current state/suppression changed",
            )
            cursor = service.execute("source_cursor", {"consumer_id": request["consumer_id"]})
            runner.require(
                cursor["data"]["through_sequence"] == 1 and cursor["data"]["pending"] is None,
                "source cursor changed",
            )
            outcomes.append(
                {"request_id": request["request_id"], "status": status, "cursor": cursor["data"]}
            )
            for operation in ("source_stage", "source_accept"):
                runner.require(
                    service.execute(operation, request)
                    == {
                        "data": receipt,
                        "replayed": True,
                    },
                    "historical retry changed",
                )
            fresh = deepcopy(request)
            fresh.update(request_id=request["request_id"] + "-new", expected_sequence=1)
            refuse(service, "source_stage", fresh, "source_identity_conflict")
            # Switch provenance route, identity, observation/receipt, consumer and request.
            fresh["consumer_id"] += "-other"
            fresh["expected_sequence"] = 0
            fresh["source"] = {
                "identity": retained._hash(fresh["request_id"]),
                "fingerprint": request["source"]["fingerprint"],
                "role": "user",
                **(
                    {"kind": "observed_native_snapshot", "observation_id": "a" * 64}
                    if request["request_id"] == "legacy"
                    else {"receipt_id": "b" * 64}
                ),
            }
            refuse(service, "source_stage", fresh, "source_suppressed")
    with opened(home, clock, "activated_session_model") as service:
        for request in sources:
            refuse(
                service,
                "candidate_propose",
                {
                    "request_id": "candidate-" + request["request_id"],
                    "content": "Derived draft",
                    "quote": request["content"],
                    "quote_start": 0,
                    "source_digest": request["source"]["fingerprint"],
                    "source_turn": "c" * 64,
                },
                "candidate_source_suppressed",
            )
    unchanged(home, baseline)
    return outcomes


def fresh_terminal(home, hermes, request):
    result = subprocess.run(
        [sys.executable, "-m", "acceptance.memory.expiry", "--verify-child", str(home)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=30,
        cwd=ROOT,
        env={
            "PATH": os.defpath,
            "HOME": str(home.parent / "os-home"),
            "PYTHONPATH": os.pathsep.join((str(ROOT), str(hermes))),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        },
    )
    runner.require(result.returncode == 0, "fresh terminal verification failed: " + result.stderr)
    return json.loads(result.stdout)


def pending_refuses(home):
    with patch.object(memory_storage, "current_profile_home", lambda: home):
        try:
            with memory_storage.open_existing_memory_reader(home, "synthetic-expiry"):
                raise AssertionError("pending maintenance admitted ordinary reader")
        except MemoryError as error:
            runner.require(error.code == "memory_maintenance_pending", "wrong recovery boundary")


def evaluate(hermes, fixture_path=FIXTURE):
    with (
        patch.object(socket, "create_connection", runner.deny_network),
        patch.object(socket.socket, "connect", runner.deny_network),
        patch.object(socket.socket, "connect_ex", runner.deny_network),
    ):
        return _evaluate(hermes, fixture_path)


def _evaluate(hermes, fixture_path):
    from test_local_task_cli import install

    from scripts.check import verify_checkout

    verify_checkout(hermes)
    sys.path.insert(0, str(hermes))
    fixture = json.loads(fixture_path.read_text())
    sources = requests(fixture)
    stages = []
    with tempfile.TemporaryDirectory(prefix="hermes-retained-expiry-") as directory:
        home = (Path(directory) / "profile").resolve()
        install(home)
        home.chmod(0o700)
        (home / "config.yaml").write_text(
            json.dumps(
                {
                    "plugins": {
                        "enabled": ["hermes-personal-agent"],
                        "entries": {
                            "hermes-personal-agent": {
                                "settings": {
                                    "mode": "local_tasks",
                                    "local_conversation": True,
                                    "local_memory": True,
                                    "memory_model_tools": True,
                                    "local_model_tools": True,
                                }
                            }
                        },
                    },
                    "delegation": {"backend": "default"},
                }
            )
        )
        receipts = []
        with opened(home, fixture["accepted_at"]) as service:
            service.execute("source_stage", sources[0])
            receipts.append(service.execute("source_accept", sources[0])["data"])
        with sqlite3.connect(retained._path(home), isolation_level=None) as connection:
            retained._legacy_layout(connection)
            legacy = connection.execute("SELECT * FROM retained_source_decisions").fetchall()
        # Only the supported writable opener migrates the historical schema fixture.
        with opened(home, fixture["accepted_at"]) as service:
            runner.require(
                service.execute("source_accept", sources[0])["data"] == receipts[0],
                "migration rewrote receipt",
            )
            service.execute("source_stage", sources[1])
            receipts.append(service.execute("source_accept", sources[1])["data"])
            anchor = service.execute(
                "remember",
                {
                    "request_id": "anchor",
                    "content": fixture["anchor"],
                },
            )["data"]["record_id"]
        for request, receipt in zip(sources, receipts, strict=True):
            check_receipt(request, receipt)
        with sqlite3.connect(retained._path(home)) as connection:
            runner.require(
                connection.execute("PRAGMA user_version").fetchone() == (13,), "migration missing"
            )
            migrated = connection.execute(
                "SELECT request_id,consumer_id,source_sequence,request_digest,source_identity,"
                "source_fingerprint,source_role,source_receipt,state,record_id,receipt,suppressed "
                "FROM retained_source_decisions WHERE request_id='legacy'"
            ).fetchall()
            runner.require(migrated == legacy, "legacy migration evidence changed")
        identifiers = {
            r["request_id"]: receipt["record"]["record_id"]
            for r, receipt in zip(sources, receipts, strict=True)
        }
        identifiers["anchor"] = anchor

        def recall(label, clock, expected):
            baseline, oracle = evidence(home), canonical(home, clock)
            for source in sources:
                record = oracle[identifiers[source["request_id"]]]
                forgotten = label in {"cleanup", "normal-repack", "interrupted-repack"}
                expected_fields = {
                    "content": None if forgotten else source["content"],
                    "topic": None if forgotten else source["topic"],
                    "source": None if forgotten else "explicit_local_operator",
                    "session_ref": None if forgotten else "synthetic-expiry",
                    "expires_at": None if forgotten else fixture["deadline"],
                    "revision": 2 if forgotten else 1,
                    "status": "forgotten" if forgotten else "active",
                }
                runner.require(
                    all(record[k] == v for k, v in expected_fields.items()),
                    "fixed fixture canonical state mismatch",
                )
            if "retry-guard" in identifiers:
                guard = oracle[identifiers["retry-guard"]]
                runner.require(
                    guard["status"] == "active" and guard["revision"] == 1,
                    "historical cleanup retry consumed another batch",
                )
            request = {
                "operation": "read",
                "clock": clock,
                "identifiers": identifiers,
                "queries": [{"id": "expiry", "query": fixture["query"], "relevant": expected}],
            }
            samples = [runner.process(home, hermes, request) for _ in range(2)]
            for sample in samples:
                verify_sample(sample, oracle, clock, identifiers, expected)
            runner.require(samples[0]["pid"] != samples[1]["pid"], "not a fresh restart")
            runner.compare(samples[0]["rows"], samples[1]["rows"])
            unchanged(home, baseline)
            stages.append(
                {
                    "id": label,
                    "clock": clock,
                    "passed": True,
                    "process_ids": [s["pid"] for s in samples],
                    "rows": samples[0]["rows"],
                    "logical_sha256": retained._hash(json.dumps(baseline, sort_keys=True)),
                }
            )

        baseline = evidence(home)
        for label in ("before", "deadline", "after"):
            clock = fixture[label]
            recall(label, clock, list(identifiers) if label == "before" else ["anchor"])
            with opened(home, clock) as service:
                for request, receipt in zip(sources, receipts, strict=True):
                    status = service.execute("source_status", source_request_identity(request))[
                        "data"
                    ]
                    runner.require(status["decision"] == receipt, "expiry changed receipt")
                    runner.require(
                        status["current"]
                        == {
                            "record_id": receipt["record"]["record_id"],
                            "revision": 1,
                            "status": "active",
                            "expired": label != "before",
                        },
                        "expiry changed stored status/revision",
                    )
            unchanged(home, baseline)
        with opened(home, fixture["after"]) as service:
            preview = service.execute("expired_preview", {"before": fixture["deadline"]})["data"]
            check_preview(
                preview,
                canonical(home, fixture["after"]),
                [identifiers["legacy"], identifiers["observed"]],
            )
            cleanup = {
                "request_id": "reviewed-cleanup",
                "before": preview["before"],
                "limit": preview["limit"],
                "expected_snapshot": preview["snapshot"],
            }
            service.execute(
                "correct",
                {
                    "record_id": anchor,
                    "request_id": "invalidate-preview",
                    "expected_revision": 1,
                    "content": fixture["anchor"],
                },
            )
            stale_baseline = evidence(home)
            refuse(service, "forget_expired", cleanup, "retention_snapshot_conflict")
            unchanged(home, stale_baseline)
            preview = service.execute("expired_preview", {"before": fixture["deadline"]})["data"]
            runner.require(
                {i["record_id"] for i in preview["items"]}
                == {identifiers["legacy"], identifiers["observed"]},
                "wrong cleanup batch",
            )
            check_preview(
                preview,
                canonical(home, fixture["after"]),
                [identifiers["legacy"], identifiers["observed"]],
            )
            cleanup["expected_snapshot"] = preview["snapshot"]
            cleanup_receipt = service.execute("forget_expired", cleanup)["data"]
            runner.require(cleanup_receipt["forgotten_count"] == 2, "incomplete cleanup")
        check_forgotten_fts(home)
        with opened(home, fixture["after"]) as service:
            identifiers["retry-guard"] = service.execute(
                "remember",
                {
                    "request_id": "retry-guard",
                    "content": "Synthetic retained expiry later batch.",
                    "expires_at": fixture["deadline"],
                },
            )["data"]["record_id"]
        for label in ("cleanup", "normal-repack", "interrupted-repack"):
            if label != "cleanup":
                baseline = evidence(home)
                name = "normal" if label == "normal-repack" else "retained"
                watermark = retained._maintain(home, "preview")["watermark"]
                retained._maintain(home, "prepare", name=name, expected_watermark=watermark)
                pending_refuses(home)
                if label == "interrupted-repack":
                    result = retained._process(home, "interrupt")
                    runner.require(result.returncode == 73, "missing cutover interruption")
                    runner.require(
                        retained._maintain(home, "status", name="retained")["pending"],
                        "missing recovery boundary",
                    )
                    pending_refuses(home)
                    result = retained._maintain(home, "recover", name="retained")
                else:
                    result = retained._maintain(home, "commit", name=name)
                runner.require(result["phase"] == "completed", "incomplete repack")
                unchanged(home, baseline)
            terminal = {
                "clock": fixture["after"],
                "sources": sources,
                "receipts": receipts,
                "cleanup": cleanup,
                "cleanup_receipt": cleanup_receipt,
            }
            terminal_result = fresh_terminal(home, hermes, terminal)
            recall(label, fixture["after"], ["anchor"])
            stages[-1]["terminal_process_id"] = terminal_result["pid"]
            stages[-1]["terminal_verification"] = terminal_result["outcomes"]
    return {
        "passed": True,
        "scope": fixture["scope"],
        "stages": stages,
        "schema_migration": "12_to_13_supported_writable_opener",
        "original_source_receipts": receipts,
        "reviewed_cleanup_receipt": cleanup_receipt,
        "checks": [
            "fixed_fixture_and_sql_oracle",
            "complete_registered_hook_envelope",
            "before_exact_after_original_expiry",
            "no_expiry_or_recall_state_mutation",
            "stale_preview_refusal",
            "current_reviewed_cleanup",
            "historical_retry_leaves_later_batch",
            "historical_receipts_and_source_cursors",
            "exact_identity_and_cross_route_fingerprint_suppression",
            "current_input_candidate_suppression",
            "fresh_process_restart",
            "normal_and_interrupted_repack",
            "pending_maintenance_reader_refusal",
        ],
        "fixture_sha256": runner.sha(fixture_path),
        "harness_sha256": {
            str(p.relative_to(ROOT)): runner.sha(p)
            for p in (
                Path(__file__),
                ROOT / "acceptance/memory/runner.py",
                ROOT / "acceptance/memory/retained.py",
                ROOT / "scripts/evaluate_retained_source_expiry.py",
                ROOT / "tests/contracts/test_local_task_cli.py",
                ROOT / "tests/contracts/test_local_conversation_tasks.py",
                ROOT / "tests/contracts/test_session_memory_tools.py",
                ROOT / "tests/contracts/test_session_memory_recall.py",
                ROOT / "tests/contracts/test_retained_source_expiry_acceptance.py",
                ROOT / "tests/unit/test_retained_source_expiry_acceptance.py",
            )
        },
        "source_sha256": {
            str(p.relative_to(ROOT)): runner.sha(p)
            for p in sorted((ROOT / "personal_agent").glob("*.py"))
        },
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "environment": {
            "python": sys.version,
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
        },
        "hermes_commit": json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "tests/contracts"))
    print(json.dumps(evaluate(args.hermes.resolve()), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-child":
        socket.create_connection = runner.deny_network
        socket.socket.connect = runner.deny_network
        socket.socket.connect_ex = runner.deny_network
        outcomes = verify_terminal(Path(sys.argv[2]), **json.load(sys.stdin))
        print(json.dumps({"pid": os.getpid(), "outcomes": outcomes}))
    else:
        main()
