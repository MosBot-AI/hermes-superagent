"""Preparation rejects loss and ambiguity; it does not verify source authority."""

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest
from test_memory_progress import error

from personal_agent.checkpoint_evidence import prepare_checkpoint_evidence


def message(n=1, **kwargs):
    return {"role": "user", "content": "早餐燕麦奶", "message_uid": f"{n:032x}", **kwargs}


def test_candidate_preserves_only_direct_text_role_and_logical_lineage():
    source = message(
        _absorbed_message_uids=[f"{2:032x}"],
        api_content="private injected recall",
        _row_id=7,
        display_metadata={"private": "display data"},
        reasoning="private reasoning",
        author_id="claimed owner",
        session_id="claimed session",
        grant="claimed approval",
    )
    prepared = prepare_checkpoint_evidence([source])
    record = prepared.messages[0]
    assert record.content == "早餐燕麦奶"
    assert record.content_sha256 == hashlib.sha256(record.content.encode()).hexdigest()
    assert record.message_uid == f"{1:032x}"
    assert record.absorbed_message_uids == (f"{2:032x}",)
    assert set(vars(record)) == {
        "message_uid",
        "absorbed_message_uids",
        "role",
        "content",
        "content_sha256",
    }
    source["content"] = "changed"
    source["_absorbed_message_uids"].clear()
    assert record.content == "早餐燕麦奶" and len(record.absorbed_message_uids) == 1
    with pytest.raises(FrozenInstanceError):
        record.content = "changed"


def test_metadata_diagnostic_never_claims_verified_durability_or_exposes_input():
    prepared = prepare_checkpoint_evidence([message()])
    diagnostic = prepared.diagnostic()
    assert diagnostic["source_verification"] == "not_performed"
    assert diagnostic["durable_checkpoint"] is diagnostic["automatic_ingestion"] is False
    assert diagnostic["message_count"] == diagnostic["source_identity_count"] == 1
    encoded = json.dumps(diagnostic, ensure_ascii=False)
    assert "早餐" not in encoded
    assert prepared.messages[0].message_uid not in encoded
    assert prepared.messages[0].content_sha256 not in encoded


def test_equal_text_distinct_uids_are_distinct_occurrences_and_edits_change_digest():
    prepared = prepare_checkpoint_evidence([message(1), message(2)])
    assert len(prepared.messages) == 2
    assert prepared.messages[0].content_sha256 == prepared.messages[1].content_sha256
    edited = prepare_checkpoint_evidence([message(1, content="早餐豆浆")])
    assert edited.messages[0].message_uid == prepared.messages[0].message_uid
    assert edited.messages[0].content_sha256 != prepared.messages[0].content_sha256


@pytest.mark.parametrize("value", [None, [], {}, "text"])
def test_missing_evidence_is_not_empty_success(value):
    error("checkpoint_evidence_unavailable", lambda: prepare_checkpoint_evidence(value))


@pytest.mark.parametrize(
    "value", [None, "", True, "claimed-id", "A" * 32, "a" * 31, "a" * 33, "a" * 32 + "\n"]
)
def test_source_uid_is_required_but_syntax_is_not_durability(value):
    error(
        "checkpoint_source_identity_unavailable",
        lambda: prepare_checkpoint_evidence([message(message_uid=value)]),
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"role": "tool"},
        {"role": "system"},
        {"role": "assistant", "tool_calls": [{"id": "t"}]},
        {"_compressed_summary": True},
    ],
)
def test_unsupported_sources_are_rejected_instead_of_silently_dropped(kwargs):
    error(
        "checkpoint_source_kind_unsupported",
        lambda: prepare_checkpoint_evidence([message(**kwargs)]),
    )


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "  ",
        [{"type": "image_url", "image_url": {"url": "data:image/png;base64,synthetic"}}],
        "bad\ud800",
    ],
)
def test_nontext_empty_and_invalid_unicode_are_explicitly_unsupported(content):
    error(
        "checkpoint_content_unsupported",
        lambda: prepare_checkpoint_evidence([message(content=content)]),
    )


def test_repeated_and_overlapping_merge_identities_are_ambiguous():
    for candidates in (
        [message(), message()],
        [message(_absorbed_message_uids=[f"{1:032x}"])],
        [message(_absorbed_message_uids=[f"{2:032x}", f"{2:032x}"])],
        [message(_absorbed_message_uids=[f"{2:032x}"]), message(2)],
        [
            message(1, _absorbed_message_uids=[f"{3:032x}"]),
            message(2, _absorbed_message_uids=[f"{3:032x}"]),
        ],
    ):
        error(
            "checkpoint_source_identity_ambiguous",
            lambda candidates=candidates: prepare_checkpoint_evidence(candidates),
        )


@pytest.mark.parametrize("lineage", [None, "uid", ("a" * 32,), ["not-native"]])
def test_lineage_shape_is_not_coerced(lineage):
    expected = (
        "checkpoint_source_identity_unavailable"
        if type(lineage) is list
        else "checkpoint_source_lineage_invalid"
    )
    error(expected, lambda: prepare_checkpoint_evidence([message(_absorbed_message_uids=lineage)]))


def test_budgets_refuse_entire_input_without_truncation():
    for candidates in (
        [message(n) for n in range(257)],
        [message(content="x" * 16385)],
        [message(n, content="x" * 16384) for n in range(5)],
        [message(1, _absorbed_message_uids=[f"{n:032x}" for n in range(2, 1025)]), message(1025)],
    ):
        error(
            "checkpoint_evidence_limit",
            lambda candidates=candidates: prepare_checkpoint_evidence(candidates),
        )
    prepared = prepare_checkpoint_evidence([message(n, content="x" * 16384) for n in range(4)])
    assert prepared.total_content_chars == 65536
