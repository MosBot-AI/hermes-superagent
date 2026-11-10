"""Current public host observations do not create an enrollment authority."""

import pytest

from personal_agent.enrollment_ceremony import CeremonyError, EnrollmentCeremony


def test_current_source_roundtrip_drops_live_routing_identity():
    from gateway.config import Platform
    from gateway.session import SessionSource
    from gateway.session_identity import identity_of

    source = SessionSource(
        platform=Platform.TELEGRAM, chat_id="123", user_id="123", profile="runtime"
    )
    # A live gateway may attach native RoutingIdentity. Data roundtrip cannot
    # establish that live provenance; do not import private resolver into plugin.
    source._identity = object()
    restored = SessionSource.from_dict(source.to_dict())
    assert restored.profile == "runtime" and restored.user_id == "123"
    assert identity_of(restored) is None
    assert not hasattr(restored, "_identity")


def test_public_command_source_and_claims_cannot_enable_ceremony():
    from gateway.config import Platform
    from gateway.session import SessionSource
    from hermes_cli.plugin_command_dispatch import invoke_plugin_command

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", user_id="123")
    c = EnrollmentCeremony(None, None)  # no authority, never touch either store

    def handler(raw_args, **context):
        return c.run(
            "issue",
            {},
            expected_revision=1,
            expected_enrollment_revision=1,
            expected_epoch=0,
            live_handle={"approved": raw_args, **context},
        )

    with pytest.raises(CeremonyError, match="unavailable"):
        invoke_plugin_command(
            handler,
            "owner=true approved=true",
            source=source,
            platform="telegram",
            session_id="session",
            session_key="key",
        )
