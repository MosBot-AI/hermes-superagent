"""Real SessionDB writes/search; source filters are not an authorization layer."""

import json
import sqlite3

import pytest


@pytest.fixture
def history(tmp_path, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_state import SessionDB

    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text("{}")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    token = set_hermes_home_override(home)
    db = SessionDB(db_path=home / "state.db")
    try:
        yield home, db
    finally:
        db.close()
        reset_hermes_home_override(token)


def search(db=None, **kwargs):
    from tools.session_search_tool import session_search

    return json.loads(session_search(db=db, **kwargs))


def add(db, sid, source="cli", content="synthetic telescope evidence", role="user"):
    db.create_session(sid, source=source, model="synthetic-model")
    return db.append_message(sid, role=role, content=content)


def test_real_fts_english_chinese_and_supported_short_cjk_fallback(history):
    _, db = history
    mid = add(db, "languages", content="synthetic telescope evidence 北京天文台研究 星图")
    # Observe real routing. Never replace FTS rows or enable a fake passing source.
    for query, route in [("telescope", "fts5"), ("北京天文台", "trigram"), ("星图", "like_scan")]:
        assert db._describe_search_path(query) == route
        rows = db.search_messages(query)
        assert any(row["id"] == mid and row["session_id"] == "languages" for row in rows)
        result = search(db, query=query)
        assert result["success"] and result["results"][0]["match_message_id"] == mid
        assert result["results"][0]["source"] == "cli"


def test_discovery_browse_source_filters_are_not_acl(history):
    _, db = history
    for source in ("cli", "cron", "kanban", "subagent", "tool"):
        add(db, source, source=source)
    discovered = search(db, query="telescope", limit=10)
    assert discovered["success"]
    assert [r["session_id"] for r in discovered["results"]] == ["cli", "cron"]
    browsed = search(db, limit=1000)
    assert browsed["mode"] == "browse"
    assert {r["session_id"] for r in browsed["results"]} == {"cli", "cron"}
    for source in ("kanban", "subagent", "tool"):
        direct = search(db, session_id=source)
        assert (
            direct["success"] and direct["messages"][0]["content"] == "synthetic telescope evidence"
        )


def test_read_scroll_discovery_bounds_and_attribution(history):
    _, db = history
    ids = [add(db, "long", content=f"telescope row {i} " + "x" * 6000) for i in range(55)]
    read = search(db, session_id="long")
    assert read["mode"] == "read" and read["message_count"] == 55 and read["truncated"]
    assert len(read["messages"]) == 30
    assert [m["id"] for m in read["messages"]] == ids[:20] + ids[-10:]
    assert all(m["content_truncated"] and len(m["content"]) == 2001 for m in read["messages"])
    scroll = search(db, session_id="long", around_message_id=ids[27], window=999)
    assert scroll["mode"] == "scroll" and scroll["window"] == 20
    assert len(scroll["messages"]) <= 41
    # Observed limitation: count is bounded, scroll content is NOT capped.
    assert all(len(m["content"]) > 6000 for m in scroll["messages"])
    assert [m["id"] for m in scroll["messages"] if m.get("anchor")] == [ids[27]]
    hit = search(db, query="telescope")["results"][0]
    assert (
        hit["session_id"] == "long" and hit["source"] == "cli" and hit["model"] == "synthetic-model"
    )
    assert hit["match_message_id"] in ids and hit["matched_role"] == "user"
    assert all(len(m["content"]) <= 4001 for m in hit["messages"])
    assert all(len(m["content"]) <= 1201 for m in hit["bookend_start"] + hit["bookend_end"])


def test_compaction_archives_are_discoverable_not_active_context(history):
    _, db = history
    old_id = add(db, "compact", content="telescope original durable evidence")
    assert search(db, query="telescope", current_session_id="compact")["results"] == []
    db.archive_and_compact(
        "compact", [{"role": "user", "content": "[CONTEXT SUMMARY]: synthetic summary"}]
    )
    assert all(row["id"] != old_id for row in db.get_messages("compact"))
    assert any(row["id"] == old_id for row in db.get_messages("compact", include_compacted=True))
    discovered = search(db, query="telescope", current_session_id="compact")
    assert discovered["results"][0]["match_message_id"] == old_id
    scroll = search(
        db, session_id="compact", around_message_id=old_id, current_session_id="compact"
    )
    assert scroll["success"] and any(m["id"] == old_id for m in scroll["messages"])
    read = search(db, session_id="compact")
    assert all(m["id"] != old_id for m in read["messages"])


def test_explicit_other_profile_reads_are_readonly_and_bare_id_does_not_fan_out(history):
    from hermes_cli.profiles import get_profile_dir
    from hermes_state import SessionDB
    from tools.session_search_tool import _resolve_profile_db

    _, db = history
    other = get_profile_dir("synthetic-other")
    other.mkdir(parents=True)
    (other / "config.yaml").write_text("{}")
    writer = SessionDB(db_path=other / "state.db")
    add(writer, "other-id", content="other profile synthetic evidence")
    writer.close()
    before = (other / "state.db").read_bytes()
    assert search(db, session_id="other-id")["success"] is False
    for args in (
        {"profile": "synthetic-other", "session_id": "other-id"},
        {"session_id": "synthetic-other/other-id"},
    ):
        result = search(db, **args)
        assert (
            result["success"]
            and result["messages"][0]["content"] == "other profile synthetic evidence"
        )
    readonly = _resolve_profile_db("synthetic-other")
    try:
        with pytest.raises(sqlite3.OperationalError, match="(?i)read.only|readonly"):
            readonly.append_message("other-id", "user", "must not write")
    finally:
        readonly.close()
    assert (other / "state.db").read_bytes() == before


def test_browse_and_discovery_limit_clamps(history):
    _, db = history
    for i in range(14):
        add(db, f"bounded-{i}")
    for kwargs in ({}, {"query": "telescope"}):
        assert len(search(db, limit=999, **kwargs)["results"]) == 10
        assert len(search(db, limit=-9, **kwargs)["results"]) == 1


def test_archived_session_is_not_deleted_or_an_access_boundary(history):
    _, db = history
    mid = add(db, "archived")
    db.set_session_archived("archived", True)
    assert db.get_session("archived")["archived"]
    assert search(db, session_id="archived")["messages"][0]["id"] == mid
    assert search(db, query="telescope")["results"][0]["match_message_id"] == mid


def test_tool_role_uses_supported_canonical_fallback(history):
    _, db = history
    mid = add(db, "tool-result", role="tool", content="synthetic toolneedle full-body evidence")
    assert search(db, query="toolneedle")["results"] == []
    result = search(db, query="toolneedle", role_filter="tool")
    assert result["results"][0]["match_message_id"] == mid
    assert result["results"][0]["matched_role"] == "tool"


def test_rewind_is_hidden_from_discovery_and_live_scroll_is_rejected(history):
    _, db = history
    mid = add(db, "rewind", content="rewindneedle synthetic evidence")
    denied = search(db, session_id="rewind", around_message_id=mid, current_session_id="rewind")
    assert denied["success"] is False and "active context" in denied["error"]
    db.rewind_to_message("rewind", mid)
    assert db.get_messages("rewind") == []
    assert search(db, query="rewindneedle")["results"] == []
    assert any(
        row["id"] == mid for row in db.search_messages("rewindneedle", include_inactive=True)
    )
    # Rewind is neither compaction nor erasure. An explicit historical scroll
    # without the live-lineage guard can still retrieve the retained row.
    assert search(db, session_id="rewind", around_message_id=mid)["messages"][0]["id"] == mid
