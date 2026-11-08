"""Native package/default gates only; no real identity or summary-read adapter."""

import importlib

import pytest
from test_local_task_cli import PLUGIN_ID, configure, entry, invoke
from test_local_task_cli import native as native


@pytest.mark.parametrize("mode", ["default", "read_only", "local_tasks"])
def test_actual_native_package_keeps_all_read_admission_surfaces_closed(native, capsys, mode):
    home, manager = native
    configure(home, mode)
    command = entry(manager)
    module_name = manager._plugins[PLUGIN_ID].module.__name__
    api = importlib.import_module(module_name + ".personal_agent.read_admission")
    authorization = importlib.import_module(module_name + ".personal_agent.authorization")

    class ForbiddenStore:
        def with_audited_read(self, *args, **kwargs):
            pytest.fail("No production adapter may access the store")

    request = authorization.ReadRequest(
        "personal.tasks.read", "exact_tasks", ("synthetic-task",), "tasks.summary"
    )
    for service in (
        api.ReadAdmissionService(ForbiddenStore()),
        api.ReadAdmissionService(ForbiddenStore(), enabled=True),
    ):
        with pytest.raises(api.ReadAdmissionError, match="unavailable"):
            service.read(
                {"owner_id": "fake-owner", "profile_id": "fake-profile", "enrollment_id": "fake"},
                request,
                live_handle={"approved": True, "owner": "fake-owner"},
            )
    _, status = invoke(command, capsys, "status")
    assert status["read_admission"] == {
        "coordinator_implemented": True,
        "production_adapters_available": False,
        "default_enabled": False,
        "durable_read_audit_implemented": True,
        "scope": (
            "Internal prepared-snapshot audit only; "
            "no live authority, task reader or delivery proof."
        ),
    }
    _, diagnostic = invoke(command, capsys, "access")
    assert diagnostic["decision"] == "deny"
    assert set(manager._plugin_commands) == {"personal-access"}
    assert manager._plugins[PLUGIN_ID].tools_registered == ["personal_agent_status"]
    assert not (home / "plugin-data").exists()


def test_actual_native_internal_audit_persists_without_enabling_admission(native, capsys):
    from datetime import UTC, datetime

    home, manager = native
    command = entry(manager)
    module_name = manager._plugins[PLUGIN_ID].module.__name__
    storage = importlib.import_module(module_name + ".personal_agent.enrollment_storage")
    enrollment = importlib.import_module(module_name + ".personal_agent.enrollment")
    api = importlib.import_module(module_name + ".personal_agent.read_admission")
    authorization = importlib.import_module(module_name + ".personal_agent.authorization")
    key = {"owner_id": "synthetic", "profile_id": "synthetic", "enrollment_id": "draft"}
    request = authorization.ReadRequest(
        "personal.tasks.read", "exact_tasks", ("synthetic-task",), "tasks.summary"
    )
    with storage.open_enrollment_store(home, enabled=True) as store:
        store.run(
            "create",
            {
                **key,
                "transport_id": "synthetic",
                "transport_receiver_id": "bot",
                "principal_id": "actor",
                "scope": {
                    "operation": request.operation,
                    "target": request.target,
                    "resource_ids": request.resource_ids,
                    "data_scope": request.data_scope,
                },
            },
        )
        assert (
            store.with_audited_read(
                key,
                expected_revision=1,
                expected_enrollment_revision=1,
                expected_epoch=0,
                operation=lambda record: enrollment.PreparedRead(
                    "synthetic detached result", datetime(2026, 1, 1, tzinfo=UTC), 1
                ),
            )
            == "synthetic detached result"
        )
    with storage.open_enrollment_store(home, enabled=True) as store:
        item = store.read_admission_history(key)["items"][0]
        assert item["outcome"] == "snapshot_prepared"
        assert item["resource_count"] == 1
        assert "synthetic-task" not in str(item)
        assert store.run("get", key)["state"] == "pending"
        with pytest.raises(api.ReadAdmissionError, match="unavailable"):
            api.ReadAdmissionService(store, enabled=True).read(key, request, live_handle=item)
    _, diagnostic = invoke(command, capsys, "access")
    assert diagnostic["decision"] == "deny"
    assert not (home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3").exists()
