"""Native cached attention review: local snapshots only, no native/model refresh."""

import builtins
import importlib
import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native
from test_local_task_cli import PLUGIN_ID
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host

ON = "2030-01-10"
OLD = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())
FRESH = int(datetime(2030, 1, 9, tzinfo=UTC).timestamp())


def module(host, name):
    return importlib.import_module(
        host.manager._plugins[PLUGIN_ID].module.__name__ + ".personal_agent." + name
    )


def seed(
    host,
    *,
    status="review",
    outcome="current",
    observed_at=OLD,
    title="Synthetic attention",
    project="Demo",
):
    storage = module(host, "task_cli")
    with storage.open_task_store(host.home) as store:
        task = store.run(
            "capture",
            {
                "title": title,
                "details": "PRIVATE DETAIL NOT FOR REVIEW",
                "request_id": str(uuid4()),
                **({"project": project} if project else {}),
            },
        )["data"]
        if status is False:
            return task
        handoff_id = str(uuid4())
        return store.sync_native(
            {
                "task_id": task["id"],
                "handoff_id": handoff_id,
                "expected_revision": 1,
                "request_id": str(uuid4()),
            },
            lambda current: {
                "handoff_id": handoff_id,
                "card_id": "t_12345678",
                "outcome": outcome,
                "status": status,
                "observed_at": observed_at,
                "exported_revision": 1,
            },
        )["data"]


def snapshot(host):
    with sqlite3.connect(database(host.home)) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {name: conn.execute("SELECT * FROM " + name).fetchall() for name in names}


def trap_refresh(monkeypatch):
    original = builtins.__import__
    dynamic = importlib.import_module
    forbidden = ("native_kanban", "kanban_handoff_storage", "kanban_handoff_store")

    def check(name, fromlist=()):
        if any(
            part in name or any(part in str(item) for item in (fromlist or ()))
            for part in forbidden
        ):
            raise AssertionError("Cached review must not import native/ledger modules")
        if name.startswith(
            ("hermes_cli.kanban", "openai", "anthropic", "run_agent", "agent.llm_transport")
        ):
            raise AssertionError("Cached review must not access native host board")

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        check(name, fromlist)
        return original(name, globals, locals, fromlist, level)

    def guarded_dynamic(name, package=None):
        check(name)
        return dynamic(name, package)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(importlib, "import_module", guarded_dynamic)


def review(host, flags=""):
    result = command(host, f"native-review --on {ON} {flags}")
    assert result["status"] == "ok", result
    return result["data"]


def test_native_review_counts_overlap_and_no_storage_or_native_access(host, monkeypatch):
    seed(host)
    seed(host, status="done", observed_at=FRESH)
    seed(host, status=None, outcome="identity_unavailable")
    seed(host, status="running", observed_at=FRESH)
    seed(host, status=False)
    closed = seed(host, status="archived")
    command(
        host, f"complete {closed['id']} --expected-revision 2 --request-id done --note explicit"
    )
    before = snapshot(host)
    trap_refresh(monkeypatch)
    result = review(host)
    assert result["counts"] == {
        "total_active": 5,
        "active_observed": 4,
        "active_unobserved": 1,
        "unique_attention": 3,
        "awaiting_review": 1,
        "board_closed": 1,
        "identity_issue": 1,
        "stale": 2,
    }
    assert (
        sum(result["counts"][key] for key in result["buckets"])
        > result["counts"]["unique_attention"]
    )
    assert "PRIVATE DETAIL" not in json.dumps(result)
    assert snapshot(host) == before
    assert not (host.home / "plugin-data" / PLUGIN_ID / "kanban-handoff").exists()


def test_tiny_budget_keeps_counts_and_whole_chinese_titles(host, monkeypatch):
    title = "茶与咖啡的选择" * 30
    for _ in range(7):
        seed(host, title=title)
    before = snapshot(host)
    trap_refresh(monkeypatch)
    result = review(host, "--max-chars 2048 --per-bucket-limit 2")
    assert len(json.dumps(result, ensure_ascii=True, sort_keys=True)) <= 2048
    assert result["counts"]["awaiting_review"] == 7 and result["counts"]["stale"] == 7
    for bucket in result["buckets"].values():
        assert bucket["total"] == len(bucket["items"]) + bucket["omitted"]
        for item in bucket["items"]:
            assert item["title"] == title
            assert set(item) == {
                "id",
                "title",
                "revision",
                "project",
                "due_date",
                "work_status",
                "native_progress",
            }
    assert snapshot(host) == before


def test_cached_review_does_not_require_handoff_enabled_or_board(host, monkeypatch):
    seed(host)
    config = json.loads((host.home / "config.yaml").read_text())
    settings = config["plugins"]["entries"][PLUGIN_ID]["settings"]
    settings["kanban_handoff"] = False
    settings["kanban_handoff_board"] = ""
    (host.home / "config.yaml").write_text(json.dumps(config))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(host.home / "never-create-board"))
    trap_refresh(monkeypatch)
    assert review(host)["counts"]["unique_attention"] == 1
    assert not (host.home / "never-create-board").exists()


def test_native_model_read_requires_activation_and_write_rejects(host, monkeypatch):
    seed(host)
    args = {"action": "native_review", "on": ON}
    with turn(host):
        assert call(host, args)["status"] == "error"
    activate(host, "enable-read")
    before = snapshot(host)
    trap_refresh(monkeypatch)
    with turn(host):
        result = call(host, args)
        assert result["status"] == "ok", result
        assert result["data"]["counts"]["unique_attention"] == 1
        assert call(host, args, write=True)["status"] == "error"
    activate(host, "enable-write")
    with turn(host):
        assert call(host, args, write=True)["status"] == "error"
        assert call(host, args)["status"] == "ok"
    activate(host, "disable")
    with turn(host):
        assert call(host, args)["status"] == "error"
    assert snapshot(host) == before


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "/synthetic/foreign"},
        {"sid": "foreign"},
        {"key": "foreign"},
        {"parent": "parent"},
        {"platform": "subagent"},
    ],
)
def test_model_cached_review_cannot_cross_scope(host, change):
    seed(host)
    activate(host, "enable-read")
    before = snapshot(host)
    with turn(host, **change):
        assert call(host, {"action": "native_review", "on": ON})["status"] == "error"
    assert snapshot(host) == before


def test_exact_project_and_unassigned_filters_only_local_saved_rows(host):
    seed(host, project="Demo")
    seed(host, project="demo")
    seed(host, project=None)
    assert review(host, "--project Demo")["counts"]["total_active"] == 1
    assert review(host, "--project demo")["counts"]["total_active"] == 1
    assert review(host, "--unassigned")["counts"]["total_active"] == 1
    assert review(host, "--project Other")["counts"]["total_active"] == 0


def test_explicit_date_boundary_not_wall_clock(host):
    cutoff = int(datetime(2030, 1, 3, tzinfo=UTC).timestamp())
    seed(host, observed_at=cutoff - 1)
    seed(host, observed_at=cutoff)
    assert review(host)["counts"]["stale"] == 1
    assert review(host, "--stale-after-days 1")["counts"]["stale"] == 2


def test_native_command_cannot_be_retargeted_by_ambient_profile(host, tmp_path, monkeypatch):
    seed(host)
    before = snapshot(host)
    other = tmp_path / "foreign-profile"
    other.mkdir(mode=0o700)
    monkeypatch.setenv("HERMES_HOME", str(other))
    result = command(host, "native-review --on " + ON)
    # Real LOCAL authority restores its bound profile during dispatch rather
    # than trusting an unrelated ambient HERMES_HOME variable.
    assert result["status"] == "ok", result
    assert result["data"]["counts"]["total_active"] == 1
    assert snapshot(host) == before
    assert list(other.iterdir()) == []


def test_next_read_uses_fresh_saved_observation_without_native_refresh(host, monkeypatch):
    task = seed(host)
    assert review(host)["counts"]["awaiting_review"] == 1
    observation = {**task["native_progress"], "status": "done", "observed_at": FRESH}
    with module(host, "task_cli").open_task_store(host.home) as store:
        store.sync_native(
            {
                "task_id": task["id"],
                "handoff_id": observation["handoff_id"],
                "expected_revision": 2,
                "request_id": "fixture-second-snapshot",
            },
            lambda current: observation,
        )
    before = snapshot(host)
    trap_refresh(monkeypatch)
    result = review(host)
    assert result["counts"]["awaiting_review"] == 0
    assert result["counts"]["board_closed"] == 1 and result["counts"]["stale"] == 0
    assert result["buckets"]["board_closed"]["items"][0]["revision"] == 3
    assert snapshot(host) == before
