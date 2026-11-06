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
        def with_current_record(self, *args, **kwargs):
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
        "durable_read_audit_implemented": False,
        "scope": "Internal fenced snapshot coordination only; no live authority or task reader.",
    }
    _, diagnostic = invoke(command, capsys, "access")
    assert diagnostic["decision"] == "deny"
    assert set(manager._plugin_commands) == {"personal-access"}
    assert manager._plugins[PLUGIN_ID].tools_registered == ["personal_agent_status"]
    assert not (home / "plugin-data").exists()
