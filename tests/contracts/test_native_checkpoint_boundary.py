"""Pinned host evidence handoff: capabilities are not a durable-source receipt.

Only synthetic messages/profiles. Stub v2 providers are test recorders, never
registered by the shipped plugin and never claimed to implement durability.
"""

import copy
from types import SimpleNamespace

import pytest
import test_native_plugin
from agent.conversation_compression import (
    _adopt_grown_durable_parent,
    _direct_messages_for_pre_compress_memory,
    _pre_compress_memory_context,
)
from agent.conversation_compression_checkpoint import (
    CompressionCheckpointUnavailable,
    _refuse_checkpoint_required_on_codex_app_server,
)
from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider

from personal_agent.checkpoint_evidence import prepare_checkpoint_evidence
from personal_agent.memory_backend import MemoryError
from personal_agent.native_memory_provider import PersonalRecordsProvider

home = test_native_plugin.home


class Recorder(MemoryProvider):
    """Intentionally non-durable test recorder to expose what the host trusts."""

    pre_compress_checkpoint_api_version = 2

    def __init__(self, *, fail=False):
        self.calls = []
        self.syncs = []
        self.fail = fail
        self.session = ""

    @property
    def name(self):
        return "checkpoint-contract-recorder"

    def is_available(self):
        return True

    def get_tool_schemas(self):
        return []

    def initialize(self, session_id, **kwargs):
        self.session = session_id

    def on_session_switch(self, new_session_id, **kwargs):
        self.session = new_session_id

    def on_pre_compress(self, messages, **kwargs):
        self.calls.append((self.session, messages, kwargs))
        if self.fail:
            raise RuntimeError("synthetic durable checkpoint failure")
        return ""

    def sync_turn(self, user_content, assistant_content, **kwargs):
        self.syncs.append((user_content, assistant_content, kwargs))
        if self.fail:
            raise RuntimeError("synthetic sync failure")


@pytest.fixture
def checkpoint_host(home):
    manager = MemoryManager()
    recorder = Recorder()
    manager.add_provider(recorder)
    manager.initialize_all(
        session_id="session", hermes_home=str(home), platform="cli", agent_context="primary"
    )
    yield home, manager, recorder
    manager.shutdown_all()


def test_host_has_checkpoint_gate_but_does_not_require_source_ids_or_commit_receipt(
    checkpoint_host,
):
    home, manager, recorder = checkpoint_host
    message = {"role": "user", "content": "pending live input without a durable locator"}
    assert manager.supports_pre_compress_checkpoint()
    agent = SimpleNamespace(_memory_manager=manager)
    # The intentionally non-durable v2 recorder's normal return passes the host
    # gate. It is not evidence of a DB transaction, archive or source coverage.
    assert _pre_compress_memory_context(agent, [message], True) == ""
    assert recorder.calls == [("session", [message], {"require_checkpoint": True})]
    assert not (home / "plugin-data").exists()
    with pytest.raises(MemoryError, match="checkpoint_source_identity_unavailable"):
        prepare_checkpoint_evidence(recorder.calls[0][1])


def test_host_normalization_preserves_uid_and_merge_lineage_but_also_extra_sidecars(
    checkpoint_host,
):
    _, manager, recorder = checkpoint_host
    uid, absorbed = "1" * 32, "2" * 32
    messages = [
        {"role": "system", "content": "policy"},
        {
            "role": "user",
            "content": "direct prose",
            "message_uid": uid,
            "_absorbed_message_uids": [absorbed],
            "api_content": "injected old memory",
            "display_metadata": {"private": "display-only"},
        },
        {
            "role": "assistant",
            "content": "assistant prose",
            "message_uid": "3" * 32,
            "tool_calls": [{"id": "tool"}],
        },
        {"role": "assistant", "content": "", "tool_calls": [{"id": "wrapper"}]},
        {"role": "tool", "content": "tool payload", "tool_call_id": "tool"},
        {"role": "assistant", "content": "derived summary", "_compressed_summary": True},
    ]
    before = copy.deepcopy(messages)
    _pre_compress_memory_context(SimpleNamespace(_memory_manager=manager), messages, True)
    evidence = recorder.calls[0][1]
    assert [row["content"] for row in evidence] == ["direct prose", "assistant prose"]
    assert evidence[0]["message_uid"] == uid
    assert evidence[0]["_absorbed_message_uids"] == [absorbed]
    assert evidence[0]["api_content"] == "injected old memory"
    assert evidence[0]["display_metadata"] == {"private": "display-only"}
    assert "tool_calls" not in evidence[1]
    prepared = prepare_checkpoint_evidence(evidence)
    assert [candidate.content for candidate in prepared.messages] == [
        "direct prose",
        "assistant prose",
    ]
    assert prepared.source_identity_count == 3
    assert prepared.diagnostic()["source_verification"] == "not_performed"
    assert messages == before


def test_host_drops_withheld_prompt_metadata_before_provider_handoff(checkpoint_host):
    from agent.message_metadata import PRE_LLM_BLOCK_WITHHELD_PROMPT

    _, manager, recorder = checkpoint_host
    messages = [
        {
            "role": "user",
            "content": PRE_LLM_BLOCK_WITHHELD_PROMPT,
            "message_uid": "1" * 32,
            "display_metadata": {"withheld_prompt": "blocked private prompt", "kind": "kept"},
        }
    ]
    _pre_compress_memory_context(SimpleNamespace(_memory_manager=manager), messages, True)
    assert recorder.calls[0][1][0]["display_metadata"] == {"kind": "kept"}
    assert messages[0]["display_metadata"]["withheld_prompt"] == "blocked private prompt"


def test_actual_native_store_preserves_stable_uids_across_reopen(home, tmp_path):
    from hermes_state import SessionDB

    path = tmp_path / "native-state.db"
    with SessionDB(path) as db:
        db.create_session("session", source="cli")
        db.append_message("session", "user", "same words")
        db.append_message("session", "assistant", "same words")
        first = db.get_messages_as_conversation("session")
        first_revision = db.conversation_revision("session")
    with SessionDB(path, read_only=True) as db:
        restored, _ = db.get_resume_conversations("session")
        assert [m["message_uid"] for m in restored] == [m["message_uid"] for m in first]
        assert restored[0]["message_uid"] != restored[1]["message_uid"]
        assert db.conversation_revision("session") == first_revision
        evidence = _direct_messages_for_pre_compress_memory(restored)
        prepared = prepare_checkpoint_evidence(evidence)
        assert prepared.source_identity_count == 2
        # The callback candidate itself still has no validated revision receipt.
        assert prepared.diagnostic()["source_verification"] == "not_performed"


def test_native_resume_merge_retains_absorbed_identities_not_one_to_one_rows(home, tmp_path):
    from hermes_state import SessionDB

    with SessionDB(tmp_path / "native-state.db") as db:
        db.create_session("session", source="cli")
        db.append_message("session", "user", "first source")
        db.append_message("session", "user", "second source")
        rows = db.get_messages_as_conversation("session")
        restored, _ = db.get_resume_conversations("session")
        assert len(rows) == 2 and len(restored) == 1
        merged = restored[0]
        assert merged["content"] == "first source\n\nsecond source"
        assert merged["message_uid"] == rows[0]["message_uid"]
        assert merged["_absorbed_message_uids"] == [rows[1]["message_uid"]]
        prepared = prepare_checkpoint_evidence(_direct_messages_for_pre_compress_memory(restored))
        assert len(prepared.messages) == 1 and prepared.source_identity_count == 2


def test_ordinary_pending_tail_is_not_preflushed_by_parent_adoption(home, tmp_path):
    from hermes_state import SessionDB

    class RejectUnlocatedEvidence(Recorder):
        def on_pre_compress(self, messages, **kwargs):
            super().on_pre_compress(messages, **kwargs)
            prepare_checkpoint_evidence(messages)
            return ""

    with SessionDB(tmp_path / "native-state.db") as db:
        db.create_session("session", source="cli")
        db.append_message("session", "assistant", "durable prefix")
        durable = db.get_messages_as_conversation("session")
        messages = durable + [{"role": "user", "content": "unpersisted live input"}]
        before = copy.deepcopy(messages)
        flushes = []
        manager = MemoryManager()
        recorder = RejectUnlocatedEvidence()
        manager.add_provider(recorder)
        manager.initialize_all(
            session_id="session", hermes_home=str(home), platform="cli", agent_context="primary"
        )
        agent = SimpleNamespace(
            _memory_manager=manager,
            _persist_user_message_idx=1,
            _flush_messages_to_session_db=lambda *args, **kwargs: flushes.append(args) or True,
        )
        lease = SimpleNamespace(
            db=db, sid="session", watermark=db.get_active_message_watermark("session")
        )
        try:
            # Parent adoption only flushes when durable history has outgrown live
            # history. The ordinary case still reaches the gate with pending input.
            assert _adopt_grown_durable_parent(agent, lease, messages) is None
            assert not flushes
            with pytest.raises(CompressionCheckpointUnavailable):
                _pre_compress_memory_context(agent, messages, True)
            assert recorder.calls[0][1] == messages
            assert messages == before
            assert db.get_messages_as_conversation("session") == durable
        finally:
            manager.shutdown_all()


def test_native_merge_can_keep_valid_uid_without_identifying_pending_constituent(home, tmp_path):
    from agent.message_metadata import record_absorbed_message
    from hermes_state import SessionDB

    with SessionDB(tmp_path / "native-state.db") as db:
        db.create_session("session", source="cli")
        db.append_message("session", "user", "stored input")
        stored = db.get_messages_as_conversation("session")[0]
        merged = copy.deepcopy(stored)
        pending = {"role": "user", "content": "unpersisted additional input"}
        record_absorbed_message(merged, pending)
        merged["content"] += "\n\n" + pending["content"]
        prepared = prepare_checkpoint_evidence([merged])
        candidate = prepared.messages[0]
        assert candidate.message_uid == stored["message_uid"]
        assert candidate.absorbed_message_uids == ()
        assert candidate.content != stored["content"]
        assert len(db.get_messages_as_conversation("session")) == 1
        # Shape preparation accepts this candidate but explicitly cannot verify
        # its source. A resolver must reject this content mismatch, not bless UID.
        assert prepared.diagnostic()["source_verification"] == "not_performed"
        assert prepared.diagnostic()["durable_checkpoint"] is False


def test_native_source_revision_changes_on_rewrite_and_compaction(home, tmp_path):
    from hermes_state import SessionDB

    with SessionDB(tmp_path / "native-state.db") as db:
        db.create_session("session", source="cli")
        row_id = db.append_message("session", "user", "original input")
        before = db.get_messages_as_conversation("session")
        revision = db.conversation_revision("session")
        prepared = prepare_checkpoint_evidence(before)
        assert db.set_user_message_content("session", row_id, "rewritten input") == 1
        rewritten = db.get_messages_as_conversation("session")
        rewritten_revision = db.conversation_revision("session")
        assert rewritten[0]["message_uid"] == before[0]["message_uid"]
        assert rewritten_revision != revision
        assert prepared.messages[0].content != rewritten[0]["content"]
        assert (
            db.archive_and_compact(
                "session",
                [{"role": "assistant", "content": "summary", "_compressed_summary": True}],
            )
            == 1
        )
        assert db.conversation_revision("session") != rewritten_revision
        assert prepared.diagnostic()["source_verification"] == "not_performed"


def test_required_provider_error_blocks_compression_and_best_effort_swallow_is_not_success(
    checkpoint_host,
):
    _, manager, recorder = checkpoint_host
    recorder.fail = True
    agent = SimpleNamespace(_memory_manager=manager)
    messages = [{"role": "user", "content": "unchanged", "message_uid": "1" * 32}]
    before = copy.deepcopy(messages)
    with pytest.raises(CompressionCheckpointUnavailable):
        _pre_compress_memory_context(agent, messages, True)
    assert messages == before
    assert _pre_compress_memory_context(agent, messages, False) == ""
    assert messages == before


def test_async_turn_sync_failure_is_not_a_checkpoint_receipt(checkpoint_host):
    _, manager, recorder = checkpoint_host
    recorder.fail = True
    messages = [{"role": "user", "content": "direct input"}]
    manager.sync_all(
        "direct input",
        "assistant output",
        session_id="session",
        messages=messages,
        turn_author={"id": "display-id", "name": "Unverified label", "is_bot": False},
    )
    manager.shutdown_all()
    assert recorder.syncs[0][2]["session_id"] == "session"
    assert recorder.syncs[0][2]["messages"] == messages
    assert manager.shutdown_drain_state["status"] == "drained"
    # Drained reports host queue completion, even though the write callback raised.
    assert not recorder.calls


@pytest.mark.parametrize("context", ["primary", "cron", "subagent", "flush"])
def test_host_checkpoint_hook_still_runs_for_nonprimary_contexts(home, context):
    manager = MemoryManager()
    recorder = Recorder()
    manager.add_provider(recorder)
    manager.initialize_all(
        session_id="session", hermes_home=str(home), platform="cli", agent_context=context
    )
    try:
        manager.on_pre_compress([], evidence_messages=[], require_checkpoint=True)
        assert recorder.calls == [("session", [], {"require_checkpoint": True})]
    finally:
        manager.shutdown_all()


def test_checkpoint_callback_does_not_bind_argument_messages_to_current_session(checkpoint_host):
    _, manager, recorder = checkpoint_host
    messages = [{"role": "user", "content": "old session evidence", "message_uid": "1" * 32}]
    manager.on_session_switch("new-session", reset=True)
    _pre_compress_memory_context(SimpleNamespace(_memory_manager=manager), messages, True)
    assert recorder.calls == [("new-session", messages, {"require_checkpoint": True})]
    # A future adapter must resolve UIDs against bound durable session/lineage;
    # manager-local session state alone is not source attribution.


def test_product_provider_still_refuses_v2_and_new_checkpoint_flags(home):
    from test_native_memory_provider import configuration

    from personal_agent.memory_lifecycle import recall_settings

    manager = MemoryManager()
    provider = PersonalRecordsProvider()
    manager.add_provider(provider)
    try:
        assert not manager.supports_pre_compress_checkpoint()
        with pytest.raises(CompressionCheckpointUnavailable):
            _pre_compress_memory_context(SimpleNamespace(_memory_manager=manager), [], True)
        config = configuration()
        config["memory"]["personal_records"]["checkpoint_enabled"] = True
        with pytest.raises(MemoryError, match="native_recall_configuration_invalid"):
            recall_settings(config)
    finally:
        manager.shutdown_all()


def test_native_app_server_required_checkpoint_boundary_remains_unsupported():
    with pytest.raises(RuntimeError, match="without a truthful pre-compaction"):
        _refuse_checkpoint_required_on_codex_app_server(True, "codex_app_server")
