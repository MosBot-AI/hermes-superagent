"""Exact-pin operator cron contracts, not a public plugin CRUD SDK.

Every host call runs in a fresh credential-free process and disposable profile.
No ticker, agent/model or external delivery runs. Ledger claims below are explicit
API fixtures, never fabricated successful jobs. One constant-output no_agent
script exercises the actual manual execution path and its local-only receipt.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONSTANT_OUTPUT = "synthetic native cron receipt"


def _child_main():
    import io
    import re
    import socket
    from contextlib import redirect_stdout

    forbidden = []
    processes = []
    home = Path(os.environ["HERMES_HOME"])
    script = home / "scripts" / "constant.py"

    def deny_network(*_args, **_kwargs):
        forbidden.append("network")
        raise AssertionError("No network in native cron contracts")

    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network

    def audit(event, args):
        if event == "subprocess.Popen":
            argv = args[1]
            # The native consumer probes gateway liveness via this read-only
            # service query. No start/stop command, worker or shell is permitted.
            status_argv = list(argv)
            if status_argv[:2] == ["systemctl", "--user"]:
                status_argv.pop(1)
            if (
                len(status_argv) == 6
                and status_argv[:2] == ["systemctl", "list-units"]
                and re.fullmatch(r"hermes-gateway-[0-9a-f]{8}", status_argv[2])
                and status_argv[3:] == ["--plain", "--no-legend", "--no-pager"]
            ):
                return
            # The only execution child allowed is the reviewed constant script.
            if list(argv) != [sys.executable, str(script)]:
                forbidden.append("process: " + repr(argv))
                raise AssertionError("No workers, commands or ticker in cron contracts")
            processes.append(list(argv))
        elif event == "os.system":
            forbidden.append(event)
            raise AssertionError("No shell in cron contracts")

    sys.addaudithook(audit)
    with redirect_stdout(io.StringIO()):
        from cron import cancellation, executions, jobs, scheduler, scheduler_provider
        from tools.cronjob_tools import cronjob

        # No managed gateway topology may silently hand this test to a worker.
        from tools.process_registry import restart_safe_gateway_child_argv

        assert (
            restart_safe_gateway_child_argv(
                [sys.executable], unit_suffix="synthetic-check", require_restart_safe_scope=False
            ).mode
            == "in_process"
        )
        results = []
        last_job = None
        last_execution = None
        for step in json.load(sys.stdin):
            if "tool" in step:
                arguments = dict(step["tool"])
                if arguments.get("job_id") == "$job":
                    arguments["job_id"] = last_job
                result = json.loads(cronjob(**arguments))
                if arguments["action"] == "create" and result.get("job_id"):
                    last_job = result["job_id"]
            elif "get" in step:
                job_id = last_job if step["get"] == "$job" else step["get"]
                result = jobs.get_job(job_id)
            elif "runs_cli" in step:
                from hermes_cli.cron import cron_runs

                job_id = last_job if step["runs_cli"] == "$job" else step["runs_cli"]
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    cron_runs(job_id=job_id, limit=20)
                result = stdout.getvalue()
            elif "history" in step:
                job_id = last_job if step["history"] == "$job" else step["history"]
                result = executions.list_executions(job_id=job_id)
            elif "fixture_claim" in step:
                job_id = last_job if step["fixture_claim"] == "$job" else step["fixture_claim"]
                # An abandoned claim fixture, not a dispatched/executed job.
                result = executions.create_execution(job_id, source="synthetic-api-fixture")
                last_execution = result["id"]
            elif "cancel_marker" in step:
                result = {
                    "requested": cancellation.cancel_requested(last_execution),
                    "reason": cancellation.CancelRequest(last_execution).reason,
                }
            elif "recover" in step:
                result = executions.recover_interrupted_executions()
            elif "receipt" in step:
                execution_id = (
                    last_execution if step["receipt"] == "$execution" else step["receipt"]
                )
                result = executions.get_execution(execution_id)
            elif "raw_list" in step:
                result = jobs.list_jobs(include_disabled=True)
            elif "fail_registration" in step:
                # Only the external trigger boundary is synthetic. The real
                # consumer, persistence and partial-failure exception are intact.
                class FailingProvider(scheduler_provider.InProcessCronScheduler):
                    def register_job(self, job):
                        assert jobs.get_job(job["id"]) is not None
                        raise RuntimeError("synthetic registration failure")

                scheduler_provider.resolve_cron_scheduler = FailingProvider
                result = {"synthetic_registration_failure": True}
            elif "registration_exception" in step:
                try:
                    scheduler.create_job_with_scheduler_registration(
                        **step["registration_exception"]
                    )
                except scheduler.CronSchedulerRegistrationError as exc:
                    result = exc.to_dict()
                    last_job = result["job_id"]
                else:
                    raise AssertionError("Expected real persisted-but-unregistered exception")
            else:
                raise AssertionError("Unknown test operation")
            results.append(result)
        assert not forbidden, forbidden
        assert "run_agent" not in sys.modules, "No model agent may be imported"
    print(json.dumps({"results": results, "script_processes": processes}))


def restart(home, *steps):
    import hermes_cli

    # Fixture housekeeping stamp avoids native detached scratch maintenance.
    # This is not a job/run receipt and no existing scratch data is supplied.
    scratch = home / "cache" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    (scratch / ".last_prune").touch()
    env = {
        "PATH": os.defpath,
        "HOME": str(home.parent / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(home / "runtime"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": os.pathsep.join(
            (str(Path(hermes_cli.__file__).resolve().parents[1]), str(Path(__file__).parent))
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    completed = subprocess.run(
        [sys.executable, "-c", "from test_native_cron_lifecycle import _child_main; _child_main()"],
        cwd=home,
        env=env,
        input=json.dumps(steps),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture
def profile(tmp_path):
    home = tmp_path / "profile"
    home.mkdir(mode=0o700)
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "cron": {"provider": "builtin", "script_timeout_seconds": 5},
                "plugins": {"enabled": []},
            }
        )
    )
    return home


def tool(action, **kwargs):
    return {"tool": {"action": action, **kwargs}}


def create(**kwargs):
    return tool(
        "create",
        **{
            "name": "Synthetic paused schedule",
            "prompt": "Summarize the synthetic fixture only.",
            "schedule": "every 1d",
            "deliver": "local",
            "paused": True,
            **kwargs,
        },
    )


def test_real_paused_cron_lifecycle_survives_restarts(profile):
    first = restart(profile, create(), tool("list"), tool("list", include_disabled=True))
    created, active, all_jobs = first["results"]
    assert created["success"] is True
    job_id = created["job_id"]
    assert created["job"]["enabled"] is False and created["job"]["state"] == "paused"
    assert created["deliver"] == "local"
    assert "created paused" in created["message"].lower()
    assert active["count"] == 0 and all_jobs["count"] == 1
    assert all_jobs["jobs"][0]["job_id"] == job_id
    assert first["script_processes"] == []
    second = restart(
        profile,
        {"get": job_id},
        tool("resume", job_id=job_id),
        tool("list"),
        tool("pause", job_id=job_id, reason="Synthetic review hold"),
        {"history": job_id},
    )["results"]
    assert second[0]["id"] == job_id and second[0]["state"] == "paused"
    assert second[1]["job"]["enabled"] is True and second[2]["count"] == 1
    assert second[3]["job"]["paused_reason"] == "Synthetic review hold"
    assert second[4] == []
    third = restart(profile, {"get": job_id}, tool("remove", job_id=job_id), {"get": job_id})
    assert third["results"][0]["state"] == "paused"
    assert third["results"][1]["removed_job"]["id"] == job_id
    assert third["results"][2] is None
    assert restart(profile, tool("list", include_disabled=True))["results"][0]["count"] == 0


def test_cron_profiles_have_independent_jobs_and_receipts(profile, tmp_path):
    created, claim = restart(profile, create(), {"fixture_claim": "$job"})["results"]
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    (other / "config.yaml").write_text('{"cron":{"provider":"builtin"}}')
    empty = restart(
        other,
        tool("list", include_disabled=True),
        {"get": created["job_id"]},
        {"history": created["job_id"]},
        {"receipt": claim["id"]},
    )
    assert empty["results"][0]["jobs"] == [] and empty["results"][1] is None
    assert empty["results"][2] == [] and empty["results"][3] is None
    own_job, own_history = restart(
        profile, {"get": created["job_id"]}, {"history": created["job_id"]}
    )["results"]
    assert own_job["id"] == created["job_id"] and own_history == [claim]
    assert claim["source"] == "synthetic-api-fixture" and claim["status"] == "claimed"


def test_duplicate_creates_are_not_idempotent_and_names_can_be_ambiguous(profile):
    rows = restart(
        profile,
        create(),
        create(),
        tool("pause", job_id="Synthetic paused schedule"),
        tool("list", include_disabled=True),
    )["results"]
    ids = {rows[0]["job_id"], rows[1]["job_id"]}
    assert len(ids) == 2
    assert rows[2]["success"] is False and "ambiguous" in rows[2]["error"]
    assert {match["id"] for match in rows[2]["matches"]} == ids
    assert {job["job_id"] for job in rows[3]["jobs"]} == ids


@pytest.mark.parametrize("action", ["remove", "pause", "resume", "cancel", "run"])
def test_missing_job_is_a_failure_without_new_jobs(profile, action):
    result = restart(profile, tool(action, job_id="missing-synthetic"), {"raw_list": True})
    assert result["results"][0]["success"] is False
    assert "not found" in result["results"][0]["error"]
    assert result["results"][1] == [] and result["script_processes"] == []


@pytest.mark.parametrize(
    "kwargs,part",
    [
        ({"schedule": "not-a-schedule"}, "schedule"),
        ({"paused": "yes"}, "boolean"),
        ({"paused": False, "paused_reason": "invalid"}, "requires paused"),
        ({"prompt": "", "skills": []}, "requires either prompt"),
        ({"no_agent": True}, "requires a script"),
        ({"timezone": "Invalid/Fixture"}, "timezone"),
        ({"script": "../outside.py"}, "script"),
    ],
)
def test_invalid_create_has_no_persisted_effect(profile, kwargs, part):
    result, jobs = restart(profile, create(**kwargs), {"raw_list": True})["results"]
    assert result["success"] is False and part.lower() in result["error"].lower()
    assert jobs == []


def test_registration_partial_failure_keeps_job_and_warns_against_recreate(profile):
    result, saved, history = restart(
        profile,
        {"fail_registration": True},
        create(paused=False),
        {"get": "$job"},
        {"history": "$job"},
    )["results"][1:]
    assert result["success"] is False
    assert result["job_saved"] is True and result["scheduler_registered"] is False
    assert result["retry_create"] is False
    assert saved["id"] == result["job_id"] and saved["enabled"] is True
    assert history == []
    reopened = restart(profile, {"get": result["job_id"]}, tool("list", include_disabled=True))
    assert reopened["results"][0] == saved
    assert reopened["results"][1]["count"] == 1


def test_actual_registration_exception_exposes_partial_commit_contract(profile):
    rows = restart(
        profile,
        {"fail_registration": True},
        {
            "registration_exception": {
                "prompt": "Synthetic registration boundary",
                "schedule": "every 1d",
                "deliver": "local",
            }
        },
        {"get": "$job"},
    )["results"]
    assert rows[1]["job_saved"] is True
    assert rows[1]["scheduler_registered"] is False and rows[1]["retry_create"] is False
    assert rows[2]["id"] == rows[1]["job_id"]


def test_cancel_without_attempt_is_noop_and_preserves_schedule(profile):
    rows = restart(
        profile, create(), {"get": "$job"}, tool("cancel", job_id="$job"), {"get": "$job"}
    )["results"]
    assert rows[2]["success"] is True and rows[2]["cancelled"] is False
    assert rows[2]["execution_id"] is None
    assert rows[1] == rows[3]


def test_cancel_claim_fixture_is_request_not_terminal_cancellation(profile):
    rows = restart(
        profile,
        create(paused=False),
        {"get": "$job"},
        {"fixture_claim": "$job"},
        tool("cancel", job_id="$job", reason="First synthetic request"),
        {"cancel_marker": True},
        tool("cancel", job_id="$job", reason="Second request"),
        {"cancel_marker": True},
        {"receipt": "$execution"},
        {"get": "$job"},
    )["results"]
    assert rows[2]["source"] == "synthetic-api-fixture" and rows[2]["status"] == "claimed"
    assert rows[3]["cancelled"] is True and rows[3]["status"] == "claimed"
    assert rows[3]["execution_id"] == rows[2]["id"]
    assert rows[4]["requested"] is True and rows[6] == rows[4]
    assert rows[7]["status"] == "claimed" and rows[7]["finished_at"] is None
    assert rows[1] == rows[8]
    assert rows[8]["enabled"] is True and rows[8]["next_run_at"]
    marker = profile / "cron" / "cancels" / (rows[2]["id"] + ".cancel")
    assert marker.read_text() == "First synthetic request"


def test_dead_process_claim_recovers_unknown_without_job_retry(profile):
    created, claim = restart(profile, create(), {"fixture_claim": "$job"})["results"]
    job_id, execution_id = created["job_id"], claim["id"]
    before, repaired, receipt, again, jobs = restart(
        profile,
        {"receipt": execution_id},
        {"recover": True},
        {"receipt": execution_id},
        {"recover": True},
        {"raw_list": True},
    )["results"]
    assert before["status"] == "claimed" and before["pid"] == claim["pid"]
    assert repaired == 1 and again == 0
    assert receipt["status"] == "unknown" and receipt["finished_at"]
    assert receipt["started_at"] is None and receipt["delivery_outcome"] is None
    assert len(jobs) == 1 and jobs[0]["id"] == job_id
    assert jobs[0]["latest_execution"] == receipt
    assert jobs[0]["last_run_at"] is None
    removed, absent, retained, cli_history = restart(
        profile,
        tool("remove", job_id=job_id),
        {"get": job_id},
        {"history": job_id},
        {"runs_cli": job_id},
    )["results"]
    assert removed["success"] is True and absent is None
    assert retained == [receipt]
    assert execution_id in cli_history and "unknown" in cli_history
    assert f"job={job_id}" in cli_history and "synthetic-api-fixture" in cli_history


@pytest.mark.parametrize("reader", ["get", "list"])
def test_queries_repair_only_explicit_disposable_corruption_fixture(profile, reader):
    created = restart(profile, create())["results"][0]
    path = profile / "cron" / "jobs.json"
    canonical = json.loads(path.read_text())
    # Explicit corruption fixture: no host DB or receipt is manufactured. The
    # native query repairs a bare-list legacy shape back to the canonical dict.
    path.write_text(json.dumps(canonical["jobs"]))
    assert isinstance(json.loads(path.read_text()), list)
    step = {"get": created["job_id"]} if reader == "get" else tool("list", include_disabled=True)
    response = restart(profile, step)["results"][0]
    assert response["id"] == created["job_id"] if reader == "get" else response["count"] == 1
    repaired = json.loads(path.read_text())
    assert isinstance(repaired, dict) and len(repaired["jobs"]) == 1
    assert repaired["jobs"][0]["id"] == created["job_id"]


def test_real_constant_script_has_local_completion_receipt_not_delivery(profile):
    scripts = profile / "scripts"
    scripts.mkdir(mode=0o700)
    script = scripts / "constant.py"
    script.write_text(f"print({CONSTANT_OUTPUT!r})\n")
    response = restart(
        profile,
        create(prompt="", no_agent=True, script=script.name, interpreter=sys.executable),
        tool("run", job_id="$job"),
        {"history": "$job"},
        tool("resume", job_id="$job"),
        tool("run", job_id="$job"),
        tool("pause", job_id="$job", reason="Test finished; no ticker"),
        {"history": "$job"},
        {"get": "$job"},
    )
    created, paused_run, no_runs, _, run, _, receipts, job = response["results"]
    assert paused_run["job"]["executed"] is False and no_runs == [], response
    assert run["job"]["executed"] is True and run["job"]["execution_success"] is True, response
    assert response["script_processes"] == [[sys.executable, str(script)]]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["job_id"] == created["job_id"] and receipt["status"] == "completed"
    assert receipt["started_at"] and receipt["finished_at"] and receipt["error"] is None
    assert receipt["delivery_outcome"] == "suppressed"
    # A manual local fire is not evidence of a scheduled occurrence or delivery.
    assert receipt["scheduled_instant"] is None
    assert job["last_status"] == "ok" and job["enabled"] is False
    outputs = list((profile / "cron" / "output" / created["job_id"]).glob("*.md"))
    assert len(outputs) == 1 and CONSTANT_OUTPUT in outputs[0].read_text()
    assert not (profile / "state.db").exists()
    reopened, history, cli_history = restart(
        profile,
        {"get": created["job_id"]},
        {"history": created["job_id"]},
        {"runs_cli": created["job_id"]},
    )["results"]
    assert reopened == job and history == receipts
    assert receipt["id"] in cli_history and "completed" in cli_history
    assert f"job={created['job_id']}" in cli_history


def test_exact_pin_public_plugin_api_does_not_offer_native_crud_sdk():
    import hermes_cli

    host = Path(hermes_cli.__file__).resolve().parents[1]
    expected = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    observed = subprocess.run(
        ["git", "-C", str(host), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    assert observed == expected
    declared = json.loads((host / "hermes_cli" / "data" / "plugin_api.json").read_text())
    entries = {entry for group in declared["groups"] for entry in group["entries"]}
    assert "cron.execution_identity" in entries
    for module in (
        "hermes_cli.projects_db",
        "hermes_cli.kanban_db",
        "cron.jobs",
        "cron.executions",
    ):
        assert not any(entry == module or entry.startswith(module + ":") for entry in entries)
