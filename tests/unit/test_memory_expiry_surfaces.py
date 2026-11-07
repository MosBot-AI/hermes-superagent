"""Explicit expiry controls reach the existing admitted command and tool paths."""

import pytest
from test_memory_commands import local as local
from test_session_memory_tools import access as access

from personal_agent.conversation_memory import parse_command
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_tool_contract import normalize_memory_tool_request

PAST = "2000-01-01T00:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"
RID = "abcdef01-2345-4678-9abc-def012345678"


def test_command_defaults_do_not_rewrite_legacy_receipt_requests():
    assert parse_command('remember "Keep it" --request-id same') == (
        "remember",
        {"content": "Keep it", "topic": "", "request_id": "same"},
    )
    operation, request = parse_command(f"correct {RID} --topic label --expected-revision 1")
    assert operation == "correct" and "expires_at" not in request
    assert parse_command("list") == ("list", {"limit": 20, "after": None})


def test_command_expiry_is_explicit_and_can_be_cleared_without_retyping_content(local):
    _, call, _, _, _ = local
    command = f'remember "Temporary plan" --expires-at {PAST} --request-id temporary'
    saved = call(command)
    assert saved["status"] == "ok"
    rid = saved["data"]["record_id"]
    assert call(command)["replayed"]
    assert call("list")["data"]["items"] == []
    assert call('search "Temporary"')["data"]["items"] == []
    assert call('recall "Temporary"')["data"]["items"] == []
    shown = call(f"show {rid}")["data"]
    assert shown["expired"] is True and shown["expires_at"] == PAST
    assert shown["content"] == "Temporary plan" and shown["revision"] == 1
    assert call("list --include-expired")["data"]["items"][0]["record_id"] == rid
    assert call('search "Temporary" --include-expired')["data"]["items"][0]["expired"]
    clear = f"correct {rid} --clear-expiry --expected-revision 1 --request-id clear"
    assert call(clear)["data"]["revision"] == 2
    assert call(clear)["replayed"]
    current = call('recall "Temporary"')["data"]["items"][0]
    assert current["expires_at"] is None and current["expired"] is False
    assert current["content"] == "Temporary plan"
    assert call(command)["replayed"]
    assert call(f"show {rid}")["data"]["expires_at"] is None


def test_correcting_other_fields_preserves_expiry_and_forget_clears_it(local):
    _, call, _, _, _ = local
    saved = call(f'remember "Private plan" --expires-at {FUTURE} --request-id save')
    rid = saved["data"]["record_id"]
    assert (
        call(f"correct {rid} --topic plans --expected-revision 1 --request-id label")["status"]
        == "ok"
    )
    assert call(f"show {rid}")["data"]["expires_at"] == FUTURE
    assert call(f"forget {rid} --expected-revision 2 --request-id forget")["status"] == "ok"
    tombstone = call(f"show {rid}")["data"]
    assert tombstone["expires_at"] is None and tombstone["content"] is None
    assert call("list --include-expired")["data"]["items"] == []
    assert (
        call(f"correct {rid} --clear-expiry --expected-revision 3 --request-id revive")["error"][
            "code"
        ]
        == "record_forgotten"
    )


@pytest.mark.parametrize(
    "raw",
    [
        'remember "Private plan" --expires-at 2027-02-29T00:00:00Z',
        'remember "Private plan" --expires-at 2099-01-01',
        'remember "Private plan" --expires-at 2099-01-01T00:00:00+00:00',
        'remember "Private plan" --clear-expiry',
        f"correct {RID} --expires-at {FUTURE} --clear-expiry --expected-revision 1",
        f"show {RID} --include-expired",
        'recall "Private" --include-expired',
        "export --include-expired",
    ],
)
def test_invalid_expiry_commands_are_redacted_before_storage(local, raw):
    _, call, _, _, opened = local
    result = call(raw)
    assert result["error"]["code"] == "invalid_request"
    assert result["data"] is None and not opened


def test_memory_tools_require_existing_write_activation_for_expiry_change(access):
    _, command, call, _, _, opened = access
    payload = {
        "action": "remember",
        "content": "Temporary preference",
        "expires_at": PAST,
        "request_id": "expires",
    }
    command("enable-read")
    assert call(payload, write=True)["error"]["code"] == "session_write_not_activated"
    assert not opened
    command("enable-write")
    saved = call(payload, write=True)
    assert saved["status"] == "ok"
    rid = saved["data"]["record_id"]
    assert call()["data"]["items"] == []
    expired = call({"action": "list", "include_expired": True})["data"]["items"][0]
    assert expired["record_id"] == rid and expired["expired"] is True
    clear = {
        "action": "correct",
        "record_id": rid,
        "expected_revision": 1,
        "request_id": "clear",
        "expires_at": None,
    }
    command("enable-read")
    assert call(clear, write=True)["error"]["code"] == "session_write_not_activated"
    command("enable-write")
    assert call(clear, write=True)["status"] == "ok"
    assert call()["data"]["items"][0]["expires_at"] is None


@pytest.mark.parametrize(
    "tool,payload",
    [
        ("personal_memory_read", {"action": "recall", "queries": ["x"], "include_expired": True}),
        ("personal_memory_read", {"action": "list", "include_expired": "true"}),
        (
            "personal_memory_write",
            {
                "action": "forget",
                "record_id": RID,
                "expected_revision": 1,
                "request_id": "forget",
                "expires_at": None,
            },
        ),
        (
            "personal_memory_write",
            {
                "action": "remember",
                "content": "x",
                "request_id": "r",
                "expires_at": "tomorrow",
            },
        ),
    ],
)
def test_model_contract_rejects_invented_clock_and_irrelevant_expiry_fields(tool, payload):
    with pytest.raises(MemoryError, match="invalid_request"):
        normalize_memory_tool_request(tool, payload)
