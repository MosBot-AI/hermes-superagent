"""Real patched-store processes, synthetic data, no ticker/model/delivery."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOST = Path(os.environ["CRON_PROPOSAL_HOST"])
CHILD = r"""
import json, os, socket, sys
from pathlib import Path

sys.path.insert(0, os.environ["CRON_PROPOSAL_HOST"])


def deny(*a, **k):
    raise AssertionError("network forbidden")


socket.socket.connect = deny
socket.create_connection = deny
from cron import jobs, scheduler
from cron import create_requests as cr

assert (
    Path(jobs.__file__).resolve().is_relative_to(Path(os.environ["CRON_PROPOSAL_HOST"]))
)
steps = json.load(sys.stdin)
result = []
for step in steps:
    try:
        op = step.pop("op")
        if op == "create":
            result.append(scheduler.create_job_with_scheduler_registration(**step))
        elif op == "list":
            result.append(jobs.list_jobs(include_disabled=True))
        elif op == "pause":
            result.append(jobs.pause_job(step["id"]))
        elif op == "remove":
            result.append(jobs.remove_job(step["id"]))
        elif op == "finish_sweep":
            from datetime import timedelta

            jobs.mark_job_run(step["id"], True)
            with jobs._jobs_lock():
                rows = jobs.load_jobs()
                removed = set()
                jobs._sweep_completed_oneshots(
                    rows, jobs._hermes_now() + timedelta(days=8), removed_ids=removed
                )
                jobs.save_jobs(rows, removed_ids=removed)
            result.append(True)
        elif op == "nested":
            from cron.jobs import use_cron_store

            with jobs._jobs_lock():
                with use_cron_store(Path(os.environ["HERMES_HOME"]) / "other"):
                    with jobs._jobs_lock():
                        pass
        elif op == "drop":
            with jobs._jobs_lock():
                rows = jobs.load_jobs()
                jobs.save_jobs(
                    [j for j in rows if j["id"] != step["id"]], removed_ids={step["id"]}
                )
            result.append(True)
        elif op == "loader_forbidden":
            import cron.scheduler_provider as sp

            sp.resolve_cron_scheduler = lambda: (_ for _ in ()).throw(
                AssertionError("resolver called")
            )
            result.append(True)
        elif op == "oversized_save":
            cr.MAX_STORE_BYTES = step["limit"]
            with jobs._jobs_lock():
                rows = jobs.load_jobs()
                rows[0]["padding"] = ["x"] * step["count"]
                jobs.save_jobs(rows)
        elif op == "lockfail":
            jobs._acquire_flock = lambda *a: False
            result.append(True)
        elif op == "capacity":
            cr.MAX_REQUESTS = step["n"]
            result.append(True)
        elif op == "crash":
            before = step["before"]
            original = jobs.atomic_replace

            def replace(*a, **k):
                if before:
                    os._exit(71)
                value = original(*a, **k)
                os._exit(72)

            jobs.atomic_replace = replace
        elif op == "external":
            import cron.scheduler_provider as sp

            class External(sp.InProcessCronScheduler):
                pass

            Path(os.environ["HERMES_HOME"]).mkdir(parents=True, exist_ok=True)
            (Path(os.environ["HERMES_HOME"]) / "config.yaml").write_text(
                "cron: {provider: external-synthetic}\n"
            )
        else:
            raise AssertionError(op)
    except Exception as e:
        result.append({"error": str(e)})
assert "run_agent" not in sys.modules
print(json.dumps(result))
"""


def env(home):
    return {
        "PATH": os.defpath,
        "HOME": str(home.parent / "user"),
        "HERMES_HOME": str(home),
        "CRON_PROPOSAL_HOST": str(HOST),
        "PYTHONPATH": str(HOST),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C.UTF-8",
    }


def run(home, *steps, code=0):
    p = subprocess.run(
        [sys.executable, "-c", CHILD],
        input=json.dumps(steps),
        text=True,
        capture_output=True,
        cwd=HOST,
        env=env(home),
        timeout=40,
    )
    assert p.returncode == code, p.stderr
    return json.loads(p.stdout) if code == 0 else None


def create(**kw):
    return {
        "op": "create",
        "request_key": "synthetic.1",
        "prompt": "Synthetic only",
        "schedule": "in 30m",
        "deliver": "local",
        "paused": True,
        **kw,
    }


def test_replay_current_state_and_delete(tmp_path):
    first = run(tmp_path, create())[0]
    job = first["creation"]["job_id"]
    again = run(tmp_path, create(), {"op": "list"})
    assert again[0]["replayed"] and again[0]["creation"] == first["creation"]
    assert len(again[1]) == 1
    assert again[0]["current_job"]["schedule"] == first["current_job"]["schedule"]
    assert "conflict" in run(tmp_path, create(prompt="Changed"))[0]["error"]
    run(tmp_path, {"op": "remove", "id": job})
    removed = run(tmp_path, create())[0]
    assert removed["creation"]["state"] == "removed" and removed["current_job"] is None
    assert run(tmp_path, {"op": "list"}) == [[]]


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin", {"platform": "synthetic", "chat_id": "x"}),
        ("no_agent", True),
        ("script", "other.py"),
        ("timezone", "UTC"),
        ("paused", False),
        ("model", "x"),
        ("provider", "x"),
        ("enabled_toolsets", []),
        ("failure_deliver", "local"),
        ("catch_up", False),
        ("interpreter", "/synthetic/python"),
        ("name", "x"),
        ("repeat", 2),
        ("skills", ["x"]),
        ("context_from", ["x"]),
        ("grace_minutes", 1),
        ("base_url", "https://example.invalid"),
        ("workdir", "/tmp"),
        ("pinned", True),
        ("monitor_script", "x.py"),
        ("monitor_url", "https://example.invalid"),
        ("attach_to_session", False),
        ("reasoning_effort", "low"),
        ("skill", "x"),
    ],
)
def test_full_explicit_payload_conflicts(tmp_path, field, value):
    run(tmp_path, create())
    assert run(tmp_path, create(**{field: value}))[0]["error"] == "create_request_conflict"


def test_pause_not_reactivated_and_auto_remove(tmp_path):
    first = run(tmp_path, create(paused=False))[0]
    id = first["creation"]["job_id"]
    run(tmp_path, {"op": "pause", "id": id})
    assert not run(tmp_path, create(paused=False))[0]["enabled"]
    run(tmp_path, {"op": "drop", "id": id})
    assert run(tmp_path, create(paused=False))[0]["creation"]["state"] == "removed"


@pytest.mark.parametrize("before", [True, False])
def test_process_death_atomic_boundary(tmp_path, before):
    run(tmp_path, {"op": "crash", "before": before}, create(), code=71 if before else 72)
    result = run(tmp_path, create(), {"op": "list"})
    assert len(result[1]) == 1
    assert result[0]["replayed"] is (not before)


@pytest.mark.parametrize("distinct", [False, True])
def test_concurrent_processes(tmp_path, distinct):
    ps = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=HOST,
            env=env(tmp_path),
        )
        for _ in range(6)
    ]
    outputs = []
    for i, p in enumerate(ps):
        p.stdin.write(
            json.dumps([create(request_key=f"synthetic.{i}" if distinct else "synthetic.1")])
        )
        p.stdin.close()
    for p in ps:
        stdout = p.stdout.read()
        stderr = p.stderr.read()
        assert p.wait(timeout=40) == 0, stderr
        outputs.append(json.loads(stdout)[0])
    expected = 6 if distinct else 1
    assert len({o["creation"]["job_id"] for o in outputs}) == expected
    assert sum(not o["replayed"] for o in outputs) == expected
    assert len(run(tmp_path, {"op": "list"})[0]) == expected


def test_lock_capacity_corruption_external(tmp_path):
    assert "lock unavailable" in run(tmp_path, {"op": "lockfail"}, create())[1]["error"]
    assert not (tmp_path / "cron/jobs.json").exists()
    assert (
        run(tmp_path / "external", {"op": "external"}, create())[0]["error"]
        == "keyed_create_provider_unsupported"
    )
    assert not (tmp_path / "cron/jobs.json").exists()
    run(tmp_path, create())
    assert (
        run(tmp_path, {"op": "capacity", "n": 1}, create(request_key="two"))[1]["error"]
        == "create_request_capacity"
    )
    path = tmp_path / "cron/jobs.json"
    data = json.loads(path.read_text())
    data["create_request_version"] = 99
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert "corrupt" in run(tmp_path, create())[0]["error"]
    assert path.read_bytes() == before


def test_profile_and_legacy(tmp_path):
    a = run(tmp_path / "a", create())[0]
    b = run(tmp_path / "b", create())[0]
    assert a["creation"]["job_id"] != b["creation"]["job_id"]
    legacy = create()
    del legacy["request_key"]
    x = run(tmp_path / "a", legacy)[0]
    assert x["id"] != a["creation"]["job_id"]
    assert run(tmp_path / "a", create())[0]["replayed"]


@pytest.mark.parametrize(
    "damage", ["bool_version", "junk", "counter", "duplicate", "oversize", "nan"]
)
def test_corruption_never_repaired(tmp_path, damage):
    run(tmp_path, create())
    path = tmp_path / "cron/jobs.json"
    data = json.loads(path.read_text())
    if damage == "bool_version":
        data["create_request_version"] = True
    elif damage == "junk":
        data["jobs"].append(None)
    elif damage == "counter":
        data["jobs"][0]["repeat"]["completed"] = "bad"
    elif damage == "nan":
        data["invalid_constant"] = float("nan")
    elif damage == "oversize":
        data["padding"] = "x" * (17 * 1024 * 1024)
    raw = json.dumps(data)
    if damage == "duplicate":
        raw = raw.replace(
            '"create_request_version": 1',
            '"create_request_version": 1, "create_request_version": 1',
        )
    path.write_text(raw)
    before = path.read_bytes()
    assert "error" in run(tmp_path, create())[0]
    assert path.read_bytes() == before


def test_actual_completion_sweep_preserves_tombstone(tmp_path):
    first = run(tmp_path, create(paused=False))[0]
    result = run(
        tmp_path, {"op": "finish_sweep", "id": first["creation"]["job_id"]}, create(paused=False)
    )
    assert result[0] is True
    assert result[1]["creation"]["state"] == "removed"
    assert result[1]["current_job"] is None


def test_nested_store_and_configured_external_refused(tmp_path):
    assert "nested store switch refused" in run(tmp_path, {"op": "nested"})[0]["error"]
    (tmp_path / "config.yaml").write_text("cron:\n  provider: missing-external-provider\n")
    assert run(tmp_path, create())[0]["error"] == "keyed_create_provider_unsupported"
    assert not (tmp_path / "cron/jobs.json").exists()


def test_exact_serialized_size_refuses_before_replace(tmp_path):
    run(tmp_path, create())
    path = tmp_path / "cron/jobs.json"
    before = path.read_bytes()
    response = run(tmp_path, {"op": "oversized_save", "limit": len(before) + 5000, "count": 900})
    assert "too_large" in response[0]["error"]
    assert path.read_bytes() == before
    assert run(tmp_path, create())[0]["replayed"]


def test_keyed_path_never_calls_external_provider_resolver(tmp_path):
    result = run(tmp_path, {"op": "loader_forbidden"}, create())
    assert result[1]["creation"]["state"] == "present"
