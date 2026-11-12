"""Canonical voice-live-shaped submissions with local fixtures and no turn execution."""

import socket
from types import SimpleNamespace

import pytest
from test_native_voice_audio_asgi import run_native_async


def test_voice_live_admission_replays_queued_receipt_on_second_connection(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    for name in ("OPENAI_API_KEY", "VOICE_TOOLS_OPENAI_KEY", "HERMES_VOICE", "HERMES_VOICE_TTS"):
        monkeypatch.delenv(name, raising=False)
    (home / "config.yaml").write_text(
        '{"platform_toolsets":{"gui":[]},"model":"synthetic"}', encoding="utf-8"
    )

    import pm
    from hermes_cli import env_loader

    def unexpected_execution(*args, **kwargs):
        pytest.fail("This admission contract cannot run a turn, install an SDK or use the network")

    monkeypatch.setattr(pm, "ensure_import", unexpected_execution)
    monkeypatch.setattr(socket.socket, "bind", unexpected_execution)
    monkeypatch.setattr(socket.socket, "listen", unexpected_execution)
    with monkeypatch.context() as startup:
        # Suppress startup reads of the pinned checkout's optional developer .env.
        startup.setattr(env_loader, "load_hermes_dotenv", lambda *args, **kwargs: [])
        startup.setattr(env_loader, "apply_config_bootstrap_env", lambda *args, **kwargs: None)
        from gateway import session_finite
        from gateway.config import GatewayConfig
        from gateway.platforms.base import get_image_cache_dir
        from gateway.runtime_bootstrap import TicketStore
        from gateway.session import SessionStore
        from gateway.session_authority import SessionAuthority
        from gateway.session_controls import AuthorityConnection
        from hermes_state_runtime import begin_runtime_epoch, list_session_admissions

    monkeypatch.setattr(session_finite, "execute_finite_admission", unexpected_execution)
    session_store = SessionStore(home / "sessions", GatewayConfig())
    with session_store._db as db:
        runner = SimpleNamespace(
            _draining=False,
            session_store=session_store,
            adapters={},
            config=SimpleNamespace(multiplex_profiles=False),
            _adapter_for_source=lambda source: None,
            _resident_agent_for=lambda key: None,
            _handle_message=unexpected_execution,
        )
        profile_id = str(home)
        instance_id = "fixture-owner"
        epoch = begin_runtime_epoch(db, instance_id=instance_id)
        authority = SessionAuthority(
            runner, profile_id=profile_id, instance_id=instance_id, db=db, epoch=epoch
        )
        runner.session_authority = authority
        # Keep genuine admission/receipt handling and fence only the execution scheduler.
        monkeypatch.setattr(authority, "_schedule", lambda ref: None)
        tickets = TicketStore(instance_id, frozenset({profile_id}))

        def connect(subject):
            ticket = tickets.mint(profile_id=profile_id, subject=subject, purpose="interactive")
            grant = tickets.redeem(ticket, profile_id=profile_id, purpose="interactive")
            # This is an in-process transport fixture with identity derived from the real grant.
            return AuthorityConnection(
                authority,
                object(),
                {
                    "user_id": grant["subject"],
                    "provider": "local",
                    "profile_id": grant["profile_id"],
                    "instance_id": grant["instance_id"],
                    "capabilities": grant["capabilities"],
                    "native_bootstrap": True,
                    "profile_scope": grant["scope"],
                },
            )

        async def call(connection, method, **params):
            return await connection.dispatch({"id": 1, "method": method, "params": params})

        async def scenario():
            first = connect("fixture-desktop")
            reconnect = connect("fixture-desktop")
            stranger = connect("other-fixture-desktop")
            try:
                created = await call(
                    first,
                    "session.create",
                    request_id="voice-session",
                    source="gui",
                    cwd=str(home),
                    toolsets=[],
                )
                assert "result" in created, created
                session_id = created["result"]["session_id"]
                request = {
                    "session_id": session_id,
                    "submission_id": "synthetic-delegation-request",
                    "text": "Synthetic request",
                    "surface": "voice-live",
                    "voice_context": "User: synthetic recent context",
                }
                unattached = await call(reconnect, "prompt.submit", **request)
                assert unattached["error"]["message"] == "permission_denied", unattached
                assert not list_session_admissions(db, session_id=session_id, pending_only=False)

                receipt = (await call(first, "prompt.submit", **request))["result"]
                assert receipt["ref"] == {"profile_id": profile_id, "session_id": session_id}
                assert receipt["status"] == "queued" and receipt["outcome"] is None
                resumed = await call(reconnect, "session.resume", session_id=session_id)
                assert "result" in resumed, resumed
                assert (await call(reconnect, "prompt.submit", **request))["result"] == receipt
                receipt_params = {
                    "session_id": session_id,
                    "admission_id": receipt["admission_id"],
                }
                assert (await call(reconnect, "prompt.receipt", **receipt_params))[
                    "result"
                ] == receipt
                refused_read = await call(stranger, "prompt.receipt", **receipt_params)
                assert refused_read["error"]["message"] == "permission_denied", refused_read

                changed = await call(
                    reconnect,
                    "prompt.submit",
                    **{
                        **request,
                        "voice_context": "User: changed synthetic context",
                    },
                )
                assert changed["error"]["message"] == "admission_conflict", changed
                assert changed["error"]["data"]["field"] == "request_id"

                invalid = await call(
                    reconnect,
                    "prompt.submit",
                    **{
                        **request,
                        "submission_id": "invalid-hint",
                        "surface": "hud",
                    },
                )
                assert invalid["error"]["message"] == "invalid_params", invalid
                missing = get_image_cache_dir() / "missing-fixture.png"
                assert missing.is_relative_to(home) and not missing.exists()
                absent_attachment = await call(
                    reconnect,
                    "prompt.submit",
                    **{
                        **request,
                        "submission_id": "missing-file",
                        "attachments": [{"path": str(missing), "mime": "image/png"}],
                    },
                )
                assert absent_attachment["error"]["message"] == "invalid_params", absent_attachment

                (row,) = list_session_admissions(db, session_id=session_id, pending_only=False)
                assert row["admission_id"] == receipt["admission_id"]
                assert row["principal_id"] == first.actor.subject
                assert row["status"] == "queued" and row["request_id"] == request["submission_id"]
                assert row["payload"]["text"] == request["text"]
                assert row["payload"]["surface_v1"] == {
                    "surface": "voice-live",
                    "voice_context": request["voice_context"],
                }
                assert "attachments_v1" not in row["payload"]
                assert db.get_messages(session_id) == []
            finally:
                await first.close()
                await reconnect.close()
                await stranger.close()

        run_native_async(scenario())
