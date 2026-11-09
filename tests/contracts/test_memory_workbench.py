"""Readable native memory commands with an explicit structured compatibility path."""

import asyncio
import json
from dataclasses import replace

import pytest
import test_local_memory_commands as memory

native = memory.native
host = memory.host


def raw_command(host, text):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-memory " + text})
    )
    assert result["type"] == "exec"
    return result["output"]


def retained(host, callback, text):
    from gateway.platforms.base import MessageEvent

    event = MessageEvent(text="/personal-memory " + text, source=host.source)
    entry = host.runner.session_store.lookup_by_session_key(host.live.route)
    return asyncio.run(host.runner._hm_run_plugin_handler(callback, event, host.source, entry))


def assert_text(value):
    assert isinstance(value, str) and value.strip()
    with pytest.raises(json.JSONDecodeError):
        json.loads(value)


def test_default_native_help_is_text_and_json_is_explicit_without_storage(host):
    text = raw_command(host, "help")
    assert_text(text)
    assert "search-terms" in text and "--json" in text
    structured = json.loads(raw_command(host, "--json help"))
    assert structured["schema_version"] == "personal.local-memory.v1"
    assert structured["status"] == "ok" and "search-terms" in structured["data"]["help"]
    assert not memory.database(host.home).exists()


def test_default_native_record_views_and_receipts_keep_chinese_readable(host):
    request = 'remember "北京 Hermes 项目需要评审" --topic 工作 --request-id workbench-save'
    receipt = raw_command(host, request)
    assert_text(receipt)
    assert "workbench-save" in receipt and "北京 Hermes 项目需要评审" not in receipt
    replay = json.loads(raw_command(host, "--json " + request))
    assert replay["replayed"] is True
    rid = replay["data"]["record_id"]
    assert rid in receipt
    replay_text = raw_command(host, request)
    assert "not current state" in replay_text.lower() and "workbench-save" in replay_text
    for query in (
        "list",
        f"show {rid}",
        'search "Hermes"',
        "search-terms 北京 Hermes",
        "recall 北京 Hermes",
    ):
        text = raw_command(host, query)
        assert_text(text)
        assert rid in text and "北京 Hermes 项目需要评审" in text
        assert "工作" in text
        data = json.loads(raw_command(host, "--json " + query))
        assert data["status"] == "ok" and data["replayed"] is False
    forgotten = raw_command(
        host, f"forget {rid} --expected-revision 1 --request-id workbench-forget"
    )
    assert_text(forgotten)
    assert rid in forgotten and "workbench-forget" in forgotten
    assert "北京 Hermes 项目需要评审" not in raw_command(host, f"show {rid}")
    assert "北京 Hermes 项目需要评审" not in raw_command(host, "list")


def test_default_native_expired_record_is_labelled_and_not_normally_listed(host):
    saved = memory.command(
        host, 'remember "已过期的中文计划" --expires-at 2000-01-01T00:00:00Z --request-id wb-expiry'
    )
    rid = saved["data"]["record_id"]
    assert "已过期的中文计划" not in raw_command(host, "list")
    for query in ("list --include-expired", f"show {rid}"):
        text = raw_command(host, query)
        assert_text(text)
        assert "已过期的中文计划" in text and "expired" in text.lower()
        assert "2000-01-01" in text


@pytest.mark.parametrize("prefix", ["", "--json "])
def test_parse_failure_format_does_not_reflect_private_arguments_or_create_store(host, prefix):
    raw = raw_command(host, prefix + "remember --unknown DO_NOT_REFLECT_SECRET")
    assert "DO_NOT_REFLECT_SECRET" not in raw
    if prefix:
        memory.assert_error(json.loads(raw), "invalid_request")
    else:
        assert_text(raw)
        assert "invalid_request" in raw
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize("prefix", ["", "--json "])
def test_unbound_callback_failure_uses_requested_format_without_storage(host, prefix):
    result = memory.handler(host)(prefix + "list")
    if prefix:
        memory.assert_error(json.loads(result), "unsupported_origin")
    else:
        assert_text(result)
        assert "unsupported_origin" in result
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize("prefix", ["", "--json "])
def test_retained_config_and_unload_failure_uses_requested_format(host, prefix):
    callback = memory.handler(host)
    memory.configure(host.home, local_memory=False)
    disabled = retained(host, callback, prefix + "list")
    if prefix:
        memory.assert_error(json.loads(disabled), "local_memory_disabled")
    else:
        assert_text(disabled)
        assert "local_memory_disabled" in disabled
    host.manager.unload()
    unloaded = retained(host, callback, prefix + "list")
    if prefix:
        memory.assert_error(json.loads(unloaded), "local_memory_unloaded")
    else:
        assert_text(unloaded)
        assert "local_memory_unloaded" in unloaded
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize("prefix", ["", "--json "])
def test_unsafe_storage_failure_uses_requested_format_and_preserves_file(host, prefix):
    path = memory.database(host.home)
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text("not a database; private sentinel")
    path.chmod(0o644)
    before = path.read_bytes()
    result = raw_command(host, prefix + "list")
    if prefix:
        memory.assert_error(json.loads(result), "unsafe_storage_file")
    else:
        assert_text(result)
        assert "unsafe_storage_file" in result
    assert "private sentinel" not in result
    assert path.read_bytes() == before


@pytest.mark.parametrize("prefix", ["", "--json "])
def test_real_host_admission_still_rejects_before_command_presentation(host, prefix):
    from hermes_state_runtime import RuntimeStoreError

    host.connection.actor = replace(host.connection.actor, subject="someone-else")
    with pytest.raises(RuntimeStoreError) as caught:
        raw_command(host, prefix + 'remember "must not save" --request-id rejected')
    assert caught.value.reason == "permission_denied"
    assert not memory.database(host.home).exists()
