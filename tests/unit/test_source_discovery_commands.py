"""Read-only native recovery discovery, strict parsing and safe human commands."""

from contextlib import contextmanager

import pytest
from test_memory_commands import local as local
from test_memory_commands import private_store as private_store
from test_retained_sources import request

from personal_agent import conversation_memory as commands
from personal_agent import memory_storage
from personal_agent import observed_source_retention as retention
from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_presentation import render_memory_result


def test_default_and_filtered_parser():
    op, payload = commands.parse_command("source-discover")
    assert op == "source_discover"
    assert payload == dict(
        state="pending", consumer_id=None, limit=20, offset=0, expected_snapshot=None
    )
    op, payload = commands.parse_command(
        "source-discover --state all --consumer-id reviewed --limit 2 --offset 2 "
        "--expected-snapshot " + "a" * 64
    )
    assert payload == dict(
        state="all", consumer_id="reviewed", limit=2, offset=2, expected_snapshot="a" * 64
    )


@pytest.mark.parametrize(
    "suffix",
    [
        "--limit 0",
        "--limit 51",
        "--limit true",
        "--offset -1",
        "--offset 20",
        "--offset 1 --expected-snapshot " + "a" * 64,
        "--limit 1 --offset 1001 --expected-snapshot " + "a" * 64,
        "--state unknown",
        "--consumer-id BAD",
        "--expected-snapshot nope",
        "--path /tmp/foreign",
        "--session-id other",
        "--state pending extra",
        "--lim 2",
    ],
)
def test_invalid_discovery_arguments(suffix):
    with pytest.raises(MemoryError, match="invalid_request"):
        commands.parse_command("source-discover " + suffix)


def test_human_exact_identity_and_continuation_roundtrip():
    payload = dict(state="all", consumer_id="reviewed", limit=1, offset=0, expected_snapshot=None)
    query = dict(request_id="-original-key", expected_digest="b" * 64)
    envelope = dict(
        status="ok",
        replayed=False,
        data={
            **payload,
            "snapshot": "a" * 64,
            "next_offset": 1,
            "items": [{"query": query}],
        },
    )
    text = render_memory_result(envelope, operation="source_discover", payload=payload)
    status = next(line for line in text.splitlines() if line.startswith("/personal-memory "))
    assert commands.parse_command(status.removeprefix("/personal-memory ")) == (
        "source_status",
        query,
    )
    continuation = next(
        line.removeprefix("Next page: ")
        for line in text.splitlines()
        if line.startswith("Next page: ")
    )
    assert commands.parse_command(continuation.removeprefix("/personal-memory ")) == (
        "source_discover",
        {**payload, "offset": 1, "expected_snapshot": "a" * 64},
    )
    assert "historical" in text and "unobserved writer" in text
    assert "no authority or future write fence" in text


def test_discovery_only_opens_existing_canonical_reader(private_store, monkeypatch):
    home, path = private_store
    with memory_storage.open_memory_backend(home, "session") as backend:
        service = MemoryService(backend)
        accepted = request(
            key="accepted", content="synthetic accepted source", consumer_id="accepted"
        )
        service.execute("source_stage", accepted)
        service.execute("source_accept", accepted)
        service.execute("source_stage", request(key="-pending"))
    before = path.read_bytes()
    real_reader = memory_storage.open_existing_memory_reader

    @contextmanager
    def reader(*args):
        with real_reader(*args) as backend:

            def denied(action, arg1, arg2, database, trigger):
                import sqlite3

                if (
                    action == sqlite3.SQLITE_READ
                    and arg1 == "records"
                    and arg2 in {"content", "topic", "source", "session_ref"}
                ):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            backend._connection.set_authorizer(denied)
            yield backend

    monkeypatch.setattr(retention, "open_existing_memory_reader", reader)
    monkeypatch.setattr(retention, "open_memory_backend", lambda *a: pytest.fail("write opener"))
    monkeypatch.setattr(retention, "review", lambda *a, **k: pytest.fail("native source opener"))
    _, payload = commands.parse_command("source-discover")
    result = retention.run(home, "session", "source_discover", payload)
    assert result["data"]["items"][0]["query"]["request_id"] == "-pending"
    assert path.read_bytes() == before


def test_missing_store_is_not_created(private_store):
    home, path = private_store
    _, payload = commands.parse_command("source-discover")
    with pytest.raises(MemoryError, match="memory_store_missing"):
        retention.run(home, "session", "source_discover", payload)
    assert not path.exists()


def test_discovery_keeps_local_admission_gates(local, monkeypatch, tmp_path):
    _, call, config, binding, opened = local
    monkeypatch.setattr(retention, "run", lambda *a: pytest.fail("not admitted"))
    config["local_memory"] = False
    assert call("source-discover")["error"]["code"] == "local_memory_disabled"
    config["local_memory"] = True
    assert call("source-discover", platform="telegram")["error"]["code"] == "unsupported_origin"
    binding["key"] = ""
    assert call("source-discover")["error"]["code"] == "unsupported_origin"
    binding["key"] = "route"
    monkeypatch.setattr(commands, "current_profile_home", lambda: tmp_path / "other")
    assert call("source-discover")["error"]["code"] == "profile_context_changed"
    assert not opened
