"""Strict local retention selection, explicit consent, recovery and text views."""

import hashlib
import json
import shlex
from uuid import uuid4

import pytest
from test_memory_commands import local as local
from test_native_source_resolution import row
from test_native_source_workbench import BINDING, Reader, inspect

from personal_agent import conversation_memory as commands
from personal_agent import native_source_workbench as review
from personal_agent import observed_source_retention as retention
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_presentation import render_memory_result

UID = row()["message_uid"]
SNAPSHOT = "a" * 64


def args(**changes):
    return {
        "message_uid": UID,
        "expected_snapshot": SNAPSHOT,
        "consumer_id": "reviewed",
        "expected_sequence": 0,
        "request_id": "keep-one",
        "retention": "independent_snapshot",
        "expires_at": None,
        "topic": "topic",
        **changes,
    }


def command(operation="source-preview", payload=None):
    p = args() if payload is None else payload
    tokens = [operation, p["message_uid"]]
    for key in (
        "expected_snapshot",
        "consumer_id",
        "expected_sequence",
        "request_id",
        "retention",
        "topic",
    ):
        tokens.append("--" + key.replace("_", "-") + "=" + str(p[key]))
    tokens.extend(["--keep"] if p["expires_at"] is None else ["--expires-at", p["expires_at"]])
    if operation == "source-retain":
        tokens.extend(["--expected-digest", p["expected_digest"]])
    return shlex.join(tokens)


def capture(db, snapshot, binding=BINDING):
    return review.inspect_sources(
        db,
        session_id="session",
        binding=binding,
        operation="source_show",
        payload={"message_uid": UID, "expected_snapshot": snapshot},
        capture=True,
    )


def test_capture_uses_native_uuid_occurrence_identity_not_fake_receipt():
    db = Reader([row()])
    native_uuid = str(uuid4())
    db.get_meta = lambda key: native_uuid if key == "store_instance_id" else None
    snapshot = inspect(db)["snapshot"]
    data = capture(db, snapshot)["data"]
    source = data["retained_source"]
    assert source == {
        "kind": "observed_native_snapshot",
        "role": "user",
        "fingerprint": hashlib.sha256(row()["content"].encode()).hexdigest(),
        "identity": hashlib.sha256(
            json.dumps(
                ["native_original_v1", native_uuid, "session", UID],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "observation_id": review._hash(
            ["personal.native-retention-observation.v1", snapshot, native_uuid]
        ),
    }
    assert data["source_receipt"] is False and "receipt_id" not in source
    moved_binding = ("/moved-profile", 3, 4)
    moved_snapshot = inspect(db, binding=moved_binding)["snapshot"]
    moved = capture(db, moved_snapshot, moved_binding)["data"]["retained_source"]
    assert moved["identity"] == source["identity"]
    assert moved["observation_id"] != source["observation_id"]


@pytest.mark.parametrize(
    "identity", [None, "", "not-uuid", "A" * 36, str(uuid4()).upper(), "0" * 32, 42, True]
)
def test_invalid_identity_refuses_capture_but_keeps_review_available(identity):
    db = Reader([row()])
    db.get_meta = lambda key: identity
    with pytest.raises(MemoryError, match="source_store_identity_unavailable"):
        capture(db, inspect(db)["snapshot"])


def test_identity_read_is_inside_observation_and_generation_checked():
    db = Reader([row()])
    db.get_meta = lambda key: str(uuid4())
    snapshot = inspect(db)["snapshot"]
    db.valid = False
    with pytest.raises(MemoryError, match="source_generation_changed"):
        capture(db, snapshot)


@pytest.mark.parametrize(
    "field,value",
    [
        ("message_uid", "bad"),
        ("expected_snapshot", None),
        ("consumer_id", "BAD"),
        ("expected_sequence", True),
        ("expected_sequence", -1),
        ("request_id", "bad/key"),
        ("retention", "current_source"),
        ("expires_at", "later"),
        ("topic", "x" * 129),
    ],
)
def test_strict_preview_validation(field, value):
    with pytest.raises(MemoryError, match="invalid_request"):
        retention.validate("source_preview", args(**{field: value}))


@pytest.mark.parametrize("field", list(args()))
def test_preview_requires_every_explicit_argument(field):
    payload = args()
    del payload[field]
    with pytest.raises(MemoryError, match="invalid_request"):
        retention.validate("source_preview", payload)


@pytest.mark.parametrize(
    "raw",
    [
        command().replace("--keep", ""),
        command().replace("--retention=independent_snapshot", ""),
        command().replace("--request-id=keep-one", ""),
        command().replace("source-preview", "source-retain"),
        command() + " --path /tmp/foreign",
        command() + " --session-id another",
        "source-status key",
        "source-discard key",
        "source-cursor",
        "source-cursor --consumer-id BAD",
        "source-status key --expected-digest not-digest",
    ],
)
def test_parser_refuses_implicit_retention_unbound_mutation_and_source_override(raw):
    with pytest.raises(MemoryError, match="invalid_request"):
        commands.parse_command(raw)


@pytest.fixture
def bridge(local, monkeypatch):
    instance, call, _, _, opened = local
    db = Reader([row()])
    db.get_meta = lambda key: "12345678-1234-4123-8123-123456789abc"
    snapshot = inspect(db)["snapshot"]
    monkeypatch.setattr(
        retention, "review", lambda home, session, op, p, **kw: capture(db, p["expected_snapshot"])
    )
    monkeypatch.setattr(retention, "open_memory_backend", commands.open_memory_backend)
    return instance, call, opened, db, args(expected_snapshot=snapshot)


def test_preview_is_pure_retention_matches_digest_and_replay_is_historical(bridge):
    _, call, opened, _, payload = bridge
    preview = call(command(payload=payload))
    assert preview["status"] == "ok", preview
    assert not opened
    assert preview["data"]["canonical_admission"] is False
    query = preview["data"]["query"]
    retained_args = {**payload, "expected_digest": query["expected_digest"]}
    retained = call(command("source-retain", retained_args))
    assert retained["status"] == "ok", retained
    assert retained["data"]["source"]["kind"] == "observed_native_snapshot"
    rid = retained["data"]["record"]["record_id"]
    assert call(f"show {rid}")["data"]["content"] == row()["content"]
    assert call(f"forget {rid} --expected-revision 1")["status"] == "ok"
    replay = call(command("source-retain", retained_args))
    assert replay["replayed"] and replay["data"] == retained["data"]
    assert call(f"show {rid}")["data"]["content"] is None


def test_wrong_digest_or_changed_native_uuid_refuses_before_admission(bridge):
    _, call, opened, db, payload = bridge
    preview = call(command(payload=payload))["data"]
    changed = {**payload, "expected_digest": "0" * 64}
    assert call(command("source-retain", changed))["error"]["code"] == "source_preview_changed"
    changed["expected_digest"] = preview["query"]["expected_digest"]
    db.get_meta = lambda key: str(uuid4())
    assert call(command("source-retain", changed))["error"]["code"] == "source_preview_changed"
    assert not opened


def test_complete_safe_preview_has_roundtrip_retain_command(bridge):
    _, call, _, _, payload = bridge
    payload["topic"] = "-中文 ' topic"
    payload["request_id"] = "-request"
    preview = call(command(payload=payload))
    assert preview["status"] == "ok"
    text = render_memory_result(preview, operation="source_preview", payload=payload)
    assert "nothing staged" in text and row()["content"] in text
    assert "observed_native_snapshot" in text and "receipt_id" not in text
    retain = next(
        line.split(": ", 1)[1]
        for line in text.splitlines()
        if line.startswith("Explicitly retain this independent snapshot:")
    )
    op, parsed = commands.parse_command(retain.removeprefix("/personal-memory "))
    assert op == "source_retain"
    assert parsed == {**payload, "expected_digest": preview["data"]["query"]["expected_digest"]}


def test_overlong_or_control_content_is_not_summarized_or_truncated(bridge):
    _, call, opened, db, payload = bridge
    for content in ("x" * 2049, "private\x1btext"):
        db.rows[0]["content"] = content
        payload["expected_snapshot"] = inspect(db)["snapshot"]
        result = call(command(payload=payload))
        assert result["error"]["code"] == "invalid_request"
    assert not opened


def test_retention_operations_keep_native_local_configuration_gates(local, monkeypatch):
    _, call, config, _, opened = local
    monkeypatch.setattr(retention, "review", lambda *a, **k: pytest.fail("not admitted"))
    config["local_memory"] = False
    assert call(command())["error"]["code"] == "local_memory_disabled"
    config["local_memory"] = True
    assert call(command(), platform="telegram")["error"]["code"] == "unsupported_origin"
    assert not opened


def test_recovery_command_handles_valid_leading_hyphen_key():
    payload = args(request_id="-request", expected_digest="a" * 64)
    result = {
        "status": "error",
        "error": {"code": "storage_error", "retryable": False},
        "request_id": "-request",
    }
    text = render_memory_result(result, operation="source_retain", payload=payload)
    line = next(line for line in text.splitlines() if line.startswith("/personal-memory "))
    op, parsed = commands.parse_command(line.removeprefix("/personal-memory "))
    assert op == "source_status"
    assert parsed == {"request_id": "-request", "expected_digest": "a" * 64}
