"""Synthetic longitudinal evidence through production recall, never model evaluation."""

import argparse
import hashlib
import importlib
import io
import json
import logging
import math
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(value):
    """Only fresh expiry evaluation time is non-durable; preserve all other fields."""
    value = deepcopy(value)
    if value:
        value["memory"].pop("evaluated_at", None)
    return value


def check_context(raw, records, clock):
    if raw is None:
        return None
    require(raw.isascii() and len(raw) <= 6000, "full ASCII JSON envelope overflow")
    data = json.loads(raw)
    require(data["schema_version"] == "personal.memory.session_recall.v1", "wrong schema")
    require("not instructions" in data["notice"], "missing untrusted-data notice")
    memory = data["memory"]
    require(0 < len(memory["items"]) <= 6, "record count overflow")
    ids = [item["record_id"] for item in memory["items"]]
    require(len(set(ids)) == len(ids), "duplicate returned IDs")
    require(
        memory["items_json_chars"]
        == len(json.dumps(memory["items"], ensure_ascii=True, sort_keys=True)),
        "incorrect items budget metadata",
    )
    require(
        memory["matched_records"] == len(ids) + memory["omitted_records"],
        "incorrect omission metadata",
    )
    require(
        0 <= memory["skipped_for_budget"] <= memory["omitted_records"],
        "incorrect budget omission metadata",
    )
    require(memory["max_chars"] == 4976, "changed record budget")
    if "automatic_filter" in memory:
        filtering = memory["automatic_filter"]
        require(
            filtering["minimum_matched_terms"] == 2 and filtering["refilled"] is False,
            "incorrect filter metadata",
        )
        require(
            0 <= filtering["filtered_returned_records"] <= memory["omitted_records"],
            "incorrect filter omission metadata",
        )
    for item in memory["items"]:
        require(item["record_id"] in records, "unknown returned ID")
        current = records[item["record_id"]]
        require(current["status"] == "active", "forgotten record recalled")
        require(not current["expires_at"] or current["expires_at"] > clock, "expired recall")
        for key in (
            "content",
            "topic",
            "revision",
            "source",
            "expires_at",
            "status",
            "created_at",
            "updated_at",
            "session_ref",
            "expired",
        ):
            require(item[key] == current[key], f"stale or truncated payload: {key}")
    return data


def compare(before, after):
    require(len(before) == len(after), "changed query count after restart/repack")
    for left, right in zip(before, after, strict=True):
        require(left["id"] == right["id"], "changed query order")
        require(
            normalized(left["context"]) == normalized(right["context"]),
            "changed logical context after restart/repack",
        )
        require(left["envelope_chars"] == right["envelope_chars"], "changed envelope budget")


def check_health(rows):
    require(
        any(row["context"] for row in rows),
        "non-vacuity: admitted hook returned no context for entire stage",
    )


def metrics(rows):
    retrieved = sum(len(row["retrieved"]) for row in rows)
    relevant = sum(len(row["relevant"]) for row in rows)
    hits = sum(len(set(row["retrieved"]) & set(row["relevant"])) for row in rows)
    return {
        "precision_returned": hits / retrieved if retrieved else None,
        "recall": hits / relevant if relevant else None,
        "hits": hits,
        "returned": retrieved,
        "relevant": relevant,
        "queries_with_misses": sum(bool(row["missed"]) for row in rows),
        "visible_envelope_omissions": sum(row["omitted_records"] or 0 for row in rows),
        "no_envelope_omissions_unknown": sum(row["omitted_records"] is None for row in rows),
        "negative_queries": sum(not row["relevant"] for row in rows),
        "negative_queries_with_results": sum(
            not row["relevant"] and bool(row["retrieved"]) for row in rows
        ),
        "positive_empty_queries": sum(
            bool(row["relevant"]) and not row["retrieved"] for row in rows
        ),
    }


def deny_network(*_args, **_kwargs):
    raise AssertionError("Synthetic acceptance forbids network connections")


@contextmanager
def observe_errors(production_prefix):
    """Observe swallowed exceptions/logs without replacing any production callable."""
    errors = []
    previous = sys.gettrace()

    def trace(frame, event, arg):
        if not frame.f_globals.get("__name__", "").startswith(production_prefix):
            return None
        if event == "exception" and not isinstance(arg[1], (StopIteration, GeneratorExit)):
            errors.append(arg[0].__name__)
        return trace

    class Failures(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR or (
                record.levelno >= logging.WARNING
                and "hook" in record.getMessage().lower()
                and (
                    "fail" in record.getMessage().lower() or "error" in record.getMessage().lower()
                )
            ):
                errors.append(record.name + ":" + record.levelname)

    handler = Failures()
    logging.getLogger().addHandler(handler)
    sys.settrace(trace)
    try:
        yield
    finally:
        sys.settrace(previous)
        logging.getLogger().removeHandler(handler)
    require(not errors, "unexpected swallowed recall failure: " + repr(errors))


def child(request):
    """Fresh allowlisted process; real host turn/classifier, no plugin install or listener."""
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    from unittest.mock import patch

    import test_local_conversation_tasks as local
    import test_session_memory_tools as session
    from hermes_cli.plugins import get_plugin_manager
    from test_local_task_cli import PLUGIN_ID
    from test_session_memory_recall import collect

    home = Path(os.environ["HERMES_HOME"])

    def load(manager):
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        require(loaded.enabled and loaded.error is None, "plugin loading failed")
        require(bool(loaded.hooks_registered), "production recall hook not registered")

    local.load = load
    with redirect_stdout(io.StringIO()):
        manager = get_plugin_manager()
        host = local.make_host(home, manager)
    prefix = manager._plugins[PLUGIN_ID].module.__name__ + ".personal_agent."
    storage = importlib.import_module(prefix + "memory_storage")
    MemoryService = importlib.import_module(prefix + "memory_backend").MemoryService
    open_memory_backend = storage.open_memory_backend
    open_existing_memory_reader = storage.open_existing_memory_reader
    recall = manager._plugin_commands["personal-memory-tools"]["handler"].__self__
    turn = session.turn

    def command(verb):
        result = session.activate(host, verb)
        require(result["status"] == "ok", result)
        return result

    with patch(prefix + "memory_expiry.utc_now", return_value=request["clock"]):
        if request["operation"] == "write":
            results = []
            with open_memory_backend(home, host.ref.session_id) as backend:
                service = MemoryService(backend)
                for operation, payload in request["steps"]:
                    expected = payload.pop("_expected_error", None)
                    try:
                        result = service.execute(operation, payload)
                    except Exception as error:
                        if expected:
                            require(
                                getattr(error, "code", None) == expected,
                                f"expected {expected}, got {error}",
                            )
                            result = {"error": expected}
                        else:
                            raise
                    else:
                        require(not expected, f"expected refusal {expected}")
                    results.append(result)
            return results
        if request["operation"] == "repack":
            maintain = importlib.import_module(prefix + "memory_maintenance").maintain
            preview = maintain(home, "maintenance_preview", {})["data"]
            prepared = maintain(
                home,
                "maintenance_prepare",
                {"name": request["name"], "expected_watermark": preview["watermark"]},
            )
            completed = maintain(home, "maintenance_commit", {"name": request["name"]})
            return {"preview": preview, "prepared": prepared, "completed": completed}
        with open_existing_memory_reader(home, host.ref.session_id) as backend:
            records = {
                rid: backend.execute("get", {"record_id": rid})
                for rid in request["identifiers"].values()
            }
        reverse = {value: key for key, value in request["identifiers"].items()}
        # Restart must not inherit activation. Test actual live-turn refusal before opt-in.
        with turn(host):
            require(
                recall.turn_context(
                    session_id=host.ref.session_id,
                    task_id="native-task",
                    user_message=request["queries"][0]["query"],
                )
                is None,
                "activation survived restart",
            )
        command("enable-read")
        command("recall-on")
        rows = []
        for query in request["queries"]:
            with turn(host):
                start = time.perf_counter_ns()
                with observe_errors(prefix):
                    raw = collect(host, query["query"]) or None
                elapsed = (time.perf_counter_ns() - start) / 1e6
            context = check_context(raw, records, request["clock"])
            memory = context["memory"] if context else {}
            ids = [reverse[item["record_id"]] for item in memory.get("items", [])]
            relevant = query["relevant"]
            rows.append(
                {
                    **query,
                    "retrieved": ids,
                    "missed": sorted(set(relevant) - set(ids)),
                    "irrelevant": sorted(set(ids) - set(relevant)),
                    "context": context,
                    "envelope_chars": len(raw) if raw else 0,
                    "omitted_records": memory.get("omitted_records"),
                    "elapsed_ms": elapsed,
                }
            )
        command("recall-off")
        with turn(host):
            require(
                recall.turn_context(
                    session_id=host.ref.session_id,
                    task_id="native-task",
                    user_message=request["queries"][0]["query"],
                )
                is None,
                "recall-off failed",
            )
        recall.close()
        return {"rows": rows, "records": records, "pid": os.getpid()}


def process(home, hermes, request):
    env = {
        "PATH": os.defpath,
        "HOME": str(home.parent / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(home.parent / "runtime"),
        "HERMES_BUNDLED_PLUGINS": str(home.parent / "bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(hermes), str(ROOT / "tests/contracts"))),
    }
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=env,
        cwd=ROOT,
        timeout=120,
    )
    require(result.returncode == 0, result.stderr)
    return json.loads(result.stdout)


def source_payload(record, sequence):
    source = record["source"]
    # Fixture provenance names are synthetic labels, deterministically encoded as SDK digests.
    return {
        "request_id": "seed-" + record["id"],
        "consumer_id": source["consumer_id"],
        "expected_sequence": sequence,
        "content": record["content"],
        "topic": record["topic"],
        "expires_at": source["expires_at"],
        "retention": source["retention"],
        "source": {
            "identity": source["source_identity"],
            "fingerprint": hashlib.sha256(record["content"].encode()).hexdigest(),
            "role": source["original_role"],
            "receipt_id": hashlib.sha256(source["receipt_id"].encode()).hexdigest(),
        },
    }


def database_snapshot(home):
    path = home / "plugin-data/hermes-personal-agent/memory/records.sqlite3"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        rows = {}
        for (table,) in tables.fetchall():
            quoted = '"' + table.replace('"', '""') + '"'
            values = conn.execute(f"SELECT * FROM {quoted}").fetchall()
            rows[table] = sorted(values, key=repr)
        return {"schema": conn.execute("PRAGMA user_version").fetchone()[0], "tables": rows}


def evaluate(fixture_path, hermes):
    from test_local_task_cli import install

    from scripts.check import verify_checkout

    verify_checkout(hermes)
    fixture_hash = sha(fixture_path)
    require(
        fixture_hash == "4e504fd7b2c84bcf2418a482f5769eecf845e84b2a56cd1c6237f7c2bc5ed2dd",
        "fixture differs from independent freeze",
    )
    fixture = json.loads(fixture_path.read_text())
    report = {
        "fixture_sha256": fixture_hash,
        "fixture_commit": "ab4df957ac12eeeabb7aa81e24b0dec9eca51511",
        "scope": fixture["scope"],
        "stages": [],
        "source_sha256": {
            str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / "personal_agent").glob("*.py"))
        },
        "harness_sha256": sha(Path(__file__)),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "environment": {
            "python": sys.version,
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "hermes_commit": json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"],
        },
        "normalization": "Only memory.evaluated_at; no record, provenance or budget fields",
        "timing_scope": "Milliseconds around native pre-LLM hook collection: "
        "production admission and exception/log observation overhead, "
        "fresh read-only open/schema validation, query, filter, full envelope, final gate. "
        "Excludes process/host startup, writes, repack, oracle, models; OS cache not flushed.",
    }
    with tempfile.TemporaryDirectory(prefix="hermes-longitudinal-") as directory:
        home = Path(directory) / "profile"
        install(home)
        home.chmod(0o700)
        settings = {
            "mode": "local_tasks",
            "local_conversation": True,
            "local_memory": True,
            "memory_model_tools": True,
            "local_model_tools": True,
        }
        (home / "config.yaml").write_text(
            json.dumps(
                {
                    "plugins": {
                        "enabled": ["hermes-personal-agent"],
                        "entries": {"hermes-personal-agent": {"settings": settings}},
                    },
                    "delegation": {"backend": "default"},
                }
            )
        )
        identifiers, sources, expected_records = {}, {}, {}
        filler_count = 0
        for index, stage in enumerate(fixture["stages"]):
            clock = stage["clock"]

            def write(steps, clock=clock):
                return process(home, hermes, {"operation": "write", "clock": clock, "steps": steps})

            additions = list(fixture["records"]) if index == 0 else []
            filler = fixture["filler"]
            additions += [
                {
                    "id": filler["id_template"].format(index=n),
                    "content": filler["content_template"].format(index=n),
                    "topic": filler["topic"],
                }
                for n in range(filler_count + 1, stage["filler_count"] + 1)
            ]
            filler_count = stage["filler_count"]
            if stage["add_distractors"]:
                additions += fixture["capacity_distractors"]
            steps, positions = [], []
            for record in additions:
                expected_records[record["id"]] = {
                    "content": record["content"],
                    "topic": record["topic"],
                    "revision": 1,
                    "expires_at": record.get("expires_at"),
                    "status": "active",
                }
                if record.get("ingestion") == "retained_source":
                    payload = source_payload(record, len(sources))
                    sources[record["id"]] = payload
                    steps += [("source_stage", payload), ("source_accept", payload)]
                    positions.append((record["id"], len(steps) - 1, True))
                else:
                    payload = {
                        k: record[k] for k in ("content", "topic", "expires_at") if k in record
                    }
                    payload["request_id"] = "seed-" + record["id"]
                    steps.append(("remember", payload))
                    positions.append((record["id"], len(steps) - 1, False))
            if steps:
                results = write(steps)
                for label, position, source in positions:
                    value = results[position]["data"]
                    identifiers[label] = (value["record"] if source else value)["record_id"]
            for mutation in stage["mutations"]:
                payload = {
                    "record_id": identifiers[mutation["id"]],
                    "expected_revision": 1,
                    "request_id": stage["id"] + "-" + mutation["id"],
                }
                if "content" in mutation:
                    payload["content"] = mutation["content"]
                write([(mutation["op"], payload)])
                expected = expected_records[mutation["id"]]
                expected["revision"] += 1
                if mutation["op"] == "forget":
                    expected.update(content=None, topic=None, expires_at=None, status="forgotten")
                else:
                    expected["content"] = mutation["content"]
            baseline = database_snapshot(home)
            require(
                len(baseline["tables"]["records"]) == stage["retained_records"],
                "wrong retained population",
            )
            probes = []
            for probe in fixture["hard_invariants"]["terminal_forget_probes"]:
                if probe["stage"] == stage["id"]:
                    probes += write(
                        [
                            (
                                "correct",
                                {
                                    "record_id": identifiers[probe["id"]],
                                    "expected_revision": 2,
                                    "request_id": "probe-" + probe["id"],
                                    "content": "must never return",
                                    "_expected_error": "record_forgotten",
                                },
                            )
                        ]
                    )
            for probe in fixture["hard_invariants"]["suppressed_source_probes"]:
                if probe["stage"] != stage["id"]:
                    continue
                original = sources[probe["id"]]
                probes += write([("source_accept", original)])  # historical receipt, no write
                for changed in (False, True):
                    payload = deepcopy(original)
                    key = "probe-" + stage["id"] + "-" + probe["id"] + str(int(changed))
                    payload.update(
                        request_id=key,
                        consumer_id=key,
                        expected_sequence=0,
                        _expected_error=(
                            "source_suppressed" if changed else "source_identity_conflict"
                        ),
                    )
                    if changed:
                        payload["source"]["identity"] = hashlib.sha256(key.encode()).hexdigest()
                    probes += write([("source_stage", payload)])
            if stage["retained_records"] == 1000:
                probes += write(
                    [
                        (
                            "remember",
                            {
                                "content": "must refuse",
                                "request_id": "overflow",
                                "_expected_error": "record_limit",
                            },
                        )
                    ]
                )
            require(database_snapshot(home) == baseline, "refusal/replay mutated canonical state")
            queries = [
                {**q, "relevant": stage["relevant_overrides"].get(q["id"], q["relevant"])}
                for q in fixture["queries"]
            ]
            request = {
                "operation": "recall",
                "clock": clock,
                "queries": queries,
                "identifiers": identifiers,
            }
            first, restarted = process(home, hermes, request), process(home, hermes, request)
            check_health(first["rows"])
            for label, expected in expected_records.items():
                current = first["records"][identifiers[label]]
                require(
                    all(current[key] == value for key, value in expected.items()),
                    f"canonical state differs from fixture mutations: {label}",
                )
            require(first["pid"] != restarted["pid"], "not a fresh process")
            compare(first["rows"], restarted["rows"])
            require(first["records"] == restarted["records"], "restart changed records")
            require(database_snapshot(home) == baseline, "recall modified retained state")
            maintenance = process(
                home, hermes, {"operation": "repack", "clock": clock, "name": stage["id"]}
            )
            require(database_snapshot(home) == baseline, "repack changed logical database")
            repacked = process(home, hermes, request)
            compare(first["rows"], repacked["rows"])
            require(first["records"] == repacked["records"], "repack changed records")
            for sample in (first, restarted, repacked):
                for row in sample["rows"]:
                    require(
                        not set(row["retrieved"]) & set(stage["forbidden_record_ids"]),
                        "forbidden record in fresh recall",
                    )
                    rendered = json.dumps(row["context"], ensure_ascii=False)
                    require(
                        not any(
                            marker in rendered for marker in stage["forbidden_payload_markers"]
                        ),
                        "stale payload marker",
                    )
                    if row["id"] in fixture["hard_invariants"]["admission_query_ids"]:
                        require(row["context"] is None, "invalid query admitted")
                for label in stage["forbidden_record_ids"]:
                    record = sample["records"][identifiers[label]]
                    if label != "temporary":
                        require(
                            record["status"] == "forgotten" and record["content"] is None,
                            "forgotten payload retained",
                        )
            controls = {"old_city_probe", "empty", "slash"}
            samples = sorted(
                row["elapsed_ms"]
                for sample in (first, restarted, repacked)
                for row in sample["rows"]
            )
            report["stages"].append(
                {
                    "id": stage["id"],
                    "timing_ms": {
                        "n": len(samples),
                        "p50": samples[math.ceil(len(samples) * 0.5) - 1],
                        "p95": samples[math.ceil(len(samples) * 0.95) - 1],
                    },
                    "maximum_envelope_chars": max(row["envelope_chars"] for row in first["rows"]),
                    "clock": clock,
                    "retained_records": len(identifiers),
                    "hard_invariants_passed": True,
                    "metrics_all_37": metrics(first["rows"]),
                    "metrics_without_three_controls": metrics(
                        [r for r in first["rows"] if r["id"] not in controls]
                    ),
                    "excluded_control_ids": sorted(controls),
                    "rows": first["rows"],
                    "repeat_rows": restarted["rows"],
                    "repack_rows": repacked["rows"],
                    "process_ids": [first["pid"], restarted["pid"], repacked["pid"]],
                    "repack": maintenance,
                    "probe_outcomes": probes,
                    "logical_database_sha256": hashlib.sha256(
                        json.dumps(baseline, sort_keys=True, default=lambda x: x.hex()).encode()
                    ).hexdigest(),
                }
            )
    from acceptance.memory.retained import run_retained_repack_acceptance

    with tempfile.TemporaryDirectory(prefix="hermes-retained-acceptance-") as directory:
        report["retained_source_maintenance"] = run_retained_repack_acceptance(Path(directory))
    report["retained_harness_sha256"] = sha(ROOT / "acceptance/memory/retained.py")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hermes", type=Path)
    parser.add_argument(
        "--fixture", type=Path, default=ROOT / "tests/fixtures/longitudinal_memory_recall.json"
    )
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(json.load(sys.stdin)), ensure_ascii=True))
    else:
        if not args.hermes:
            parser.error("--hermes exact clean pinned checkout is required")
        sys.path.insert(0, str(ROOT / "tests/contracts"))
        print(
            json.dumps(evaluate(args.fixture, args.hermes.resolve()), ensure_ascii=True, indent=2)
        )


if __name__ == "__main__":
    main()
