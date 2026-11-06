"""Untrusted and incomplete source observations never grant access or echo IDs."""

import json
from enum import Enum
from types import SimpleNamespace

import pytest

from personal_agent.identity import build_access_diagnostic, observe_actor


class Platform(Enum):
    TELEGRAM = "telegram"


def source(**changes):
    return SimpleNamespace(
        **{
            "platform": Platform.TELEGRAM,
            "user_id": "123456789",
            "chat_id": "123456789",
            "chat_type": "dm",
            "is_bot": False,
            "delivered_via_upstream_relay": False,
            "profile_route_rejected": False,
            **changes,
        }
    )


def test_candidate_never_grants_access_or_uses_private_receiver():
    candidate = source()
    candidate._transport_adapter_ref = "private-receiver-secret"
    candidate.owner_id = "self-claimed-owner"
    candidate.profile = "synthetic-private-profile"
    result = build_access_diagnostic(
        platform="telegram",
        source=candidate,
        session_id="private-session",
        session_key="private-route",
    )
    assert result["actor_observation"]["candidate_recognized"] is True
    assert result["reason"] == "receiving_transport_unverified"
    assert result["decision"] == "deny" and result["status"] == "blocked"
    assert result["protected_reads_enabled"] is False
    assert result["primary_binding_enabled"] is False
    serialized = json.dumps(result)
    for secret in ["123456789", "private", "self-claimed-owner", "synthetic"]:
        assert secret not in serialized


@pytest.mark.parametrize("platform", ["local", "cli", "tui", "desktop", "discord", None, True, {}])
def test_unsupported_platform(platform):
    assert observe_actor(platform=platform, source=source()).reason == "unsupported_platform"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"platform": "discord"}, "source_platform_mismatch"),
        ({"chat_type": "group"}, "private_chat_required"),
        ({"chat_type": "channel"}, "private_chat_required"),
        ({"thread_id": "thread"}, "private_chat_required"),
        ({"scope_id": "scope"}, "private_chat_required"),
        ({"parent_chat_id": "parent"}, "private_chat_required"),
        ({"detached_route": "detached"}, "private_chat_required"),
        ({"is_bot": True}, "human_actor_required"),
        ({"is_bot": 0}, "human_actor_required"),
        ({"delivered_via_upstream_relay": True}, "relay_source_unsupported"),
        ({"profile_route_rejected": True}, "profile_route_unverified"),
        ({"user_id": None}, "actor_ids_unavailable"),
        ({"user_id": 123456789}, "actor_ids_unavailable"),
        ({"user_id": "owner-name"}, "actor_ids_unavailable"),
        ({"user_id": "123", "chat_id": "456"}, "actor_ids_unavailable"),
        ({"user_id": "0", "chat_id": "0"}, "actor_ids_unavailable"),
        ({"user_id": "1" * 21, "chat_id": "1" * 21}, "actor_ids_unavailable"),
    ],
)
def test_incomplete_or_wrong_sources(changes, reason):
    result = observe_actor(platform="telegram", source=source(**changes))
    assert not result.candidate_recognized and result.reason == reason


def test_missing_source_and_mapping_cannot_be_an_owner():
    assert build_access_diagnostic()["reason"] == "source_unavailable"
    result = build_access_diagnostic(platform="telegram", source=vars(source()))
    assert result["actor_observation"]["candidate_recognized"] is False
    assert result["decision"] == "deny"


def test_raising_source_is_redacted():
    class BadSource:
        @property
        def platform(self):
            raise RuntimeError("Synthetic private token")

    result = build_access_diagnostic(platform="telegram", source=BadSource())
    assert result["reason"] == "source_malformed"
    assert "Synthetic" not in json.dumps(result)


@pytest.mark.parametrize(
    "args", [None, True, {}, "approve", "--owner secret", "status extra", " " * 33]
)
def test_command_text_never_provides_identity(args):
    result = build_access_diagnostic(args, platform="telegram", source=source())
    assert result["reason"] == "invalid_arguments" and result["decision"] == "deny"
    assert "secret" not in json.dumps(result)
