"""Explicit operator review syntax never defaults to indefinite canonical retention."""

import pytest

from personal_agent.conversation_memory import parse_command
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_tool_contract import normalize_memory_tool_request
from personal_agent.status import build_status

ID = "00000000-0000-4000-8000-000000000001"


def test_candidate_review_commands_bind_id_revision_and_retention_choice():
    assert parse_command(f"candidate-show {ID}") == ("candidate_get", {"candidate_id": ID})
    assert parse_command("candidate-list --limit 3") == (
        "candidate_list",
        {"limit": 3, "after": None},
    )
    assert parse_command(f"candidate-accept {ID} --expected-revision 1 --keep") == (
        "candidate_accept",
        {"candidate_id": ID, "expected_revision": 1, "expires_at": None},
    )
    assert (
        parse_command(
            f"candidate-accept {ID} --expected-revision 1 --expires-at 2030-01-01T00:00:00Z"
        )[1]["expires_at"]
        == "2030-01-01T00:00:00Z"
    )
    assert parse_command(f"candidate-discard {ID} --expected-revision 1") == (
        "candidate_discard",
        {"candidate_id": ID, "expected_revision": 1},
    )
    assert parse_command("candidate-purge-expired") == ("candidate_purge_expired", {})


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "--keep",
        "--expected-revision 1",
        "--expected-revision 1 --keep --expires-at 2030-01-01T00:00:00Z",
        "--expected-revision 1 --expires-at tomorrow",
        "--expected-revision 1 --keep --content changed",
        "--expected-revision 1 --keep --approved true",
    ],
)
def test_candidate_accept_requires_exact_explicit_review_fields(suffix):
    with pytest.raises(MemoryError):
        parse_command(f"candidate-accept {ID} {suffix}")


@pytest.mark.parametrize("action", ["candidate_propose", "candidate_accept", "candidate_discard"])
def test_existing_model_memory_tools_cannot_reach_candidate_review(action):
    for name in ("personal_memory_read", "personal_memory_write"):
        with pytest.raises(MemoryError):
            normalize_memory_tool_request(name, {"action": action, "candidate_id": ID})


def test_candidate_status_is_configuration_not_observed_consent_or_extraction():
    result = build_status(
        mode="local_tasks",
        local_conversation=True,
        local_memory=True,
        memory_model_tools=True,
        memory_candidates=True,
    )["local_memory"]
    assert result["candidate_workflow_implemented"] is True
    assert result["candidate_capture_configured"] is True
    assert result["candidate_capture_activation_observed"] is False
    assert result["candidate_acceptance_requires_native_review"] is True
    assert result["candidate_pending_expiry_days"] == 7
    assert result["candidate_expiry_cleanup"] == (
        "lazy_on_successful_candidate_operation_or_explicit_purge_not_background"
    )
    assert result["automatic_extraction"] is False
    assert result["native_compression_checkpoint"] is False


@pytest.mark.parametrize("value", [True, 1, "true", None, {}])
def test_candidate_status_refuses_missing_or_invalid_prerequisites(value):
    with pytest.raises(ValueError):
        build_status(memory_candidates=value)
