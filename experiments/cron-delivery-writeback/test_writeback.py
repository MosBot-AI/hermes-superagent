"""Real native queue and scheduler bookkeeping under isolated process loss."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from cron import delivery_queue, executions, jobs, scheduler

DEATH_CODE = 73
CHILD = """
import os
import sys
from pathlib import Path

from cron import delivery_outcome, delivery_queue

cut, retention = sys.argv[1:]

def refuse_network(event, args):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto"}:
        os._exit(74)

sys.addaudithook(refuse_network)
if retention == "pruned":
    delivery_queue.MAX_TERMINAL_DELIVERIES = 0
if cut == "after_queue_commit":
    delivery_outcome.settle_quietly = lambda *args: os._exit(73)
if cut == "after_job_write":
    original = delivery_outcome._settle_job_record
    def settle_then_exit(*args):
        assert original(*args)
        os._exit(73)
    delivery_outcome._settle_job_record = settle_then_exit

def send(job, content, for_failure):
    if cut == "before_acceptance":
        os._exit(73)
    # Separate from every native database. Appending twice is visible even when
    # the native destination would deduplicate the same execution.
    with (Path(os.environ["HERMES_HOME"]) / "synthetic-accepted").open("ab") as stream:
        stream.write(b"one\\n")
        stream.flush()
        os.fsync(stream.fileno())
    if cut == "after_acceptance":
        os._exit(73)
    return None

delivery_queue.drain(send)
"""


@pytest.fixture
def run(tmp_path, monkeypatch):
    from gateway.config import GatewayConfig, Platform, PlatformConfig

    home = tmp_path / "profile"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HERMES_HOME", str(home))
    config = GatewayConfig()
    config.platforms[Platform.TELEGRAM] = PlatformConfig(enabled=True)
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: config)
    monkeypatch.setattr(
        scheduler, "run_job", lambda job, **kw: (True, "synthetic output", "reminder", None)
    )
    job = jobs.create_job(prompt="Synthetic", schedule="every 1h", deliver="telegram:fixture")
    scheduler.run_one_job(job)
    record = executions.latest_execution(job["id"])
    assert record["status"] == "completed" and record["delivery_outcome"] == "queued"
    assert delivery_queue.get_status(record["id"])["status"] == "pending"
    return home, job, record


def cut_process(home, cut, retention="full"):
    checkout = Path(delivery_queue.__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", CHILD, cut, retention],
        cwd=checkout,
        env={
            "HOME": str(home),
            "HERMES_HOME": str(home),
            "PATH": os.defpath,
            "PYTHONPATH": str(checkout),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
            "TZ": "UTC",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == DEATH_CODE, result


def resume(monkeypatch):
    attempts = []

    def record_unexpected_send(*args, **kwargs):
        attempts.append("send")
        return "unexpected replay"

    monkeypatch.setattr(scheduler, "_deliver_result", record_unexpected_send)
    assert scheduler.drain_delivery_queue({}, None) == 0
    assert scheduler.drain_delivery_queue({}, None) == 0
    assert attempts == []


def accepted_count(home):
    path = home / "synthetic-accepted"
    return len(path.read_bytes().splitlines()) if path.exists() else 0


def test_clean_pin_loses_terminal_writeback_when_delivery_process_exits(run, monkeypatch):
    home, job, record = run
    cut_process(home, "after_queue_commit")
    assert accepted_count(home) == 1
    assert delivery_queue.get_status(record["id"])["status"] == "delivered"
    resume(monkeypatch)
    assert executions.get_execution(record["id"])["delivery_outcome"] == "queued"
    assert jobs.get_job(job["id"])["last_status"] == "delivery_queued"
    assert accepted_count(home) == 1


def test_clean_pin_reports_unknown_queue_receipt_as_failed_execution_delivery(run, monkeypatch):
    home, _, record = run
    cut_process(home, "after_acceptance")
    resume(monkeypatch)
    assert delivery_queue.get_status(record["id"])["status"] == "unknown"
    assert executions.get_execution(record["id"])["delivery_outcome"] == "failed"
    assert accepted_count(home) == 1


@pytest.mark.parametrize(
    ("cut", "expected_count", "outcome"),
    [
        ("before_acceptance", 0, "unknown"),
        ("after_acceptance", 1, "unknown"),
        ("after_queue_commit", 1, "delivered"),
        ("after_job_write", 1, "delivered"),
    ],
)
def test_candidate_recovers_metadata_with_no_send_replay(
    run, monkeypatch, capsys, cut, expected_count, outcome
):
    from hermes_cli.cron import _last_run_display, cron_runs

    home, job, record = run
    cut_process(home, cut)
    assert executions.get_execution(record["id"])["delivery_outcome"] == "queued"
    resume(monkeypatch)
    queue = delivery_queue.get_status(record["id"])
    assert queue["status"] == outcome
    assert executions.get_execution(record["id"])["delivery_outcome"] == outcome
    saved = jobs.get_job(job["id"])
    assert saved["last_status"] == ("delivery_failed" if outcome == "unknown" else "ok")
    if outcome == "unknown":
        assert "unknown" in saved["last_delivery_error"]
        latest = next(item for item in jobs.list_jobs() if item["id"] == job["id"])
        assert "delivery outcome unknown" in _last_run_display(latest).lower()
    capsys.readouterr()
    cron_runs(job["id"])
    assert f"delivery={outcome}" in capsys.readouterr().out
    assert accepted_count(home) == expected_count


def test_candidate_recovers_from_terminal_tombstone(run, monkeypatch):
    home, job, record = run
    cut_process(home, "after_queue_commit", "pruned")
    tombstone = delivery_queue.get_status(record["id"])
    assert tombstone["status"] == "delivered" and "job_json" not in tombstone
    resume(monkeypatch)
    assert executions.get_execution(record["id"])["delivery_outcome"] == "delivered"
    assert jobs.get_job(job["id"])["last_status"] == "ok"
    assert accepted_count(home) == 1


def test_candidate_updates_old_execution_without_replacing_newer_job_summary(run, monkeypatch):
    home, job, old = run
    cut_process(home, "after_queue_commit")
    scheduler.run_one_job(jobs.get_job(job["id"]))
    new = executions.latest_execution(job["id"])
    assert old["id"] != new["id"]
    sent = []

    def refuse_new(job, content, **kwargs):
        sent.append(content)
        return "synthetic refusal for the newer execution"

    monkeypatch.setattr(scheduler, "_deliver_result", refuse_new)
    assert scheduler.drain_delivery_queue({}, None) == 1
    assert scheduler.drain_delivery_queue({}, None) == 0
    assert sent == ["reminder"]
    assert executions.get_execution(old["id"])["delivery_outcome"] == "delivered"
    assert executions.get_execution(new["id"])["delivery_outcome"] == "failed"
    assert jobs.get_job(job["id"])["last_delivery_error"] == (
        "synthetic refusal for the newer execution"
    )
    assert accepted_count(home) == 1


def test_candidate_reconciles_a_wait_timeout_after_claim(run, monkeypatch):
    home, _, record = run
    claimed = delivery_queue.claim_next()
    assert claimed["execution_id"] == record["id"]
    assert "unknown" in delivery_queue._terminalize_wait_timeout(record["id"])
    resume(monkeypatch)
    assert executions.get_execution(record["id"])["delivery_outcome"] == "unknown"
    assert accepted_count(home) == 0


def test_candidate_rejects_wrong_job_id_before_writing_any_outcome(run, monkeypatch):
    from cron.delivery_outcome import settle_queued_delivery

    home, job, record = run
    cut_process(home, "after_queue_commit")
    assert settle_queued_delivery("other-job", record["id"]) is False
    assert executions.get_execution(record["id"])["delivery_outcome"] == "queued"
    assert jobs.get_job(job["id"])["last_status"] == "delivery_queued"
    resume(monkeypatch)
    assert executions.get_execution(record["id"])["delivery_outcome"] == "delivered"


def test_candidate_retains_unknown_receipt_that_arrives_before_firer_bookkeeping(run, monkeypatch):
    home, job, old = run
    cut_process(home, "after_queue_commit")
    resume(monkeypatch)
    enqueue = delivery_queue.enqueue

    def enqueue_then_interrupt(execution_id, *args, **kwargs):
        queued = enqueue(execution_id, *args, **kwargs)
        cut_process(home, "after_acceptance")
        assert delivery_queue.recover_abandoned() == 1
        assert executions.get_execution(execution_id)["status"] == "running"
        return queued

    monkeypatch.setattr(delivery_queue, "enqueue", enqueue_then_interrupt)
    scheduler.run_one_job(jobs.get_job(job["id"]))
    latest = executions.latest_execution(job["id"])
    assert latest["id"] != old["id"]
    assert latest["status"] == "completed" and latest["delivery_outcome"] == "unknown"
    assert delivery_queue.get_status(latest["id"])["status"] == "unknown"
    resume(monkeypatch)
    assert accepted_count(home) == 2
