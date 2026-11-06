"""Non-authorizing observations of documented slash-command source fields.

A recognizable transport actor is not a verified domain owner or receiving Bot.
This module cannot construct VerifiedReadContext, issue grants or read storage.
"""

import re
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class ActorObservation:
    """Only diagnostic flags, deliberately excluding identity strings and secrets."""

    source_present: bool
    candidate_recognized: bool
    platform: str
    reason: str


def observe_actor(*, platform: object = "", source: object = None) -> ActorObservation:
    """Duck-type the public source projection, including hosted IPC Records.

    Never consult private adapter references, display names, request-body claims
    or session environment fallbacks. A valid observation still denies access.
    """
    if source is None:
        return ActorObservation(False, False, "unknown", "source_unavailable")
    if type(platform) is not str or platform != "telegram":
        return ActorObservation(True, False, "unsupported", "unsupported_platform")
    try:
        source_platform = getattr(source, "platform", None)
        if isinstance(source_platform, Enum):
            source_platform = source_platform.value
        if type(source_platform) is not str or source_platform != platform:
            return ActorObservation(True, False, "telegram", "source_platform_mismatch")
        if getattr(source, "chat_type", None) != "dm":
            return ActorObservation(True, False, "telegram", "private_chat_required")
        if getattr(source, "is_bot", None) is not False:
            return ActorObservation(True, False, "telegram", "human_actor_required")
        if getattr(source, "delivered_via_upstream_relay", None) is not False:
            return ActorObservation(True, False, "telegram", "relay_source_unsupported")
        if getattr(source, "profile_route_rejected", None) is not False:
            return ActorObservation(True, False, "telegram", "profile_route_unverified")
        for field in ("thread_id", "parent_chat_id", "scope_id", "guild_id", "detached_route"):
            if getattr(source, field, None) not in (None, ""):
                return ActorObservation(True, False, "telegram", "private_chat_required")
        user = getattr(source, "user_id", None)
        chat = getattr(source, "chat_id", None)
        if (
            type(user) is not str
            or type(chat) is not str
            or re.fullmatch(r"[1-9][0-9]{0,19}", user) is None
            or user != chat
        ):
            return ActorObservation(True, False, "telegram", "actor_ids_unavailable")
    except Exception:
        return ActorObservation(True, False, "telegram", "source_malformed")
    # The public object has runtime profile, not verified receiving Bot/account.
    # No set of these public fields can satisfy that missing provenance contract.
    return ActorObservation(True, True, "telegram", "receiving_transport_unverified")


def build_access_diagnostic(
    raw_args: object = "",
    *,
    platform: object = "",
    source: object = None,
    session_id: object = "",
    session_key: object = "",
) -> dict:
    """Always deny protected access; caller/session text cannot become authority."""
    del session_id, session_key
    observation = observe_actor(platform=platform, source=source)
    valid_args = (
        type(raw_args) is str and len(raw_args) <= 32 and raw_args.strip() in ("", "status")
    )
    return {
        "schema_version": "personal.access-diagnostic.v1",
        "status": "blocked",
        "decision": "deny",
        "reason": observation.reason if valid_args else "invalid_arguments",
        "actor_observation": {
            "source_present": observation.source_present,
            "candidate_recognized": observation.candidate_recognized,
            "platform": observation.platform,
        },
        "missing_contracts": [
            "verified_receiving_transport",
            "owner_binding",
            "current_read_policy",
        ],
        "protected_reads_enabled": False,
        "primary_binding_enabled": False,
        "scope": "diagnostic_only_no_authentication_or_grant",
    }
