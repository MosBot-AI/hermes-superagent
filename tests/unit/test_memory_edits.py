"""Managed editable draft lifecycle, writer fences and process crash recovery."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from personal_agent.local_memory import _APPLICATION_ID, _SCHEMA_V8, create_backend
from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_edits import FILENAME, TEMP, PrivateEdits
from personal_agent.memory_projection import PrivateProjection


def opened(directory, *, files=True, factory=sqlite3.Connection):
    conn = sqlite3.connect(directory / "records.sqlite3", isolation_level=None, factory=factory)
    backend = create_backend()
    backend.open(
        conn,
        namespace_id="test",
        session_ref="s",
        edits=PrivateEdits(directory) if files else None,
        projection=PrivateProjection(directory),
    )
    return backend, conn


@pytest.fixture
def store(tmp_path):
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700)
    backend, conn = opened(directory)
    yield MemoryService(backend), conn, directory
    backend.close()
    conn.close()


def seed(service, key="seed", **extra):
    return service.execute(
        "remember", {"content": "原正文\n第二行", "topic": "私人", "request_id": key, **extra}
    )["data"]["record_id"]


def draft(service, rid, key="draft", revision=1):
    return service.execute(
        "edit_create", {"record_id": rid, "expected_revision": revision, "request_id": key}
    )["data"]["draft_id"]


def change_file(
    directory, content="更新中文\n# Markdown 正文\n<script>不执行</script>", topic="工作"
):
    path = directory / FILENAME
    lines = path.read_text().split("\n", 4)
    lines[2] = "Topic: " + json.dumps(topic, ensure_ascii=False)
    lines[4] = content
    path.write_text("\n".join(lines))


def apply_request(service, did, key="apply"):
    preview = service.execute("edit_preview", {"draft_id": did})["data"]
    return {"draft_id": did, "expected_digest": preview["sha256"], "request_id": key}


def error(code, call):
    with pytest.raises(MemoryError) as caught:
        call()
    assert caught.value.code == code


def test_complete_edit_preserves_expiry_and_receipts_never_retain_body(store):
    s, c, d = store
    rid = seed(s, expires_at="2030-01-01T00:00:00Z")
    did = draft(s, rid)
    assert (d / FILENAME).stat().st_mode & 0o777 == 0o600
    change_file(d)
    before = c.total_changes
    preview = s.execute("edit_preview", {"draft_id": did})["data"]
    assert preview["before"]["content"] == "原正文\n第二行"
    assert preview["proposed"]["topic"] == "工作" and c.total_changes == before
    request = apply_request(s, did)
    result = s.execute("edit_apply", request)
    assert result["data"]["record"]["revision"] == 2
    current = s.execute("get", {"record_id": rid})["data"]
    assert current["content"] == preview["proposed"]["content"]
    assert current["expires_at"] == "2030-01-01T00:00:00Z"
    assert not (d / FILENAME).exists()
    assert "更新" not in str(c.execute("SELECT * FROM memory_edits").fetchall())
    assert (
        s.execute("search_terms", {"terms": ["更新中文"]})["data"]["items"][0]["record_id"] == rid
    )
    s.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"})
    assert s.execute("edit_apply", request) == {**result, "replayed": True}
    assert draft(s, rid) == did  # original create receipt only; no resurrection
    assert not (d / FILENAME).exists()
    assert s.execute("list", {})["data"]["items"] == []


def test_one_active_draft_discard_idempotence_and_fresh_create(store):
    s, _, d = store
    rid = seed(s)
    did = draft(s, rid)
    error("edit_active", lambda: draft(s, rid, key="another"))
    error("idempotency_conflict", lambda: draft(s, rid, revision=2))
    result = s.execute("edit_discard", {"draft_id": did})
    assert not (d / FILENAME).exists()
    assert s.execute("edit_discard", {"draft_id": did}) == {**result, "replayed": True}
    assert draft(s, rid, key="new") != did


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_target_mutations_clear_edited_body_and_crash_staging(store, operation):
    s, _, d = store
    rid = seed(s)
    did = draft(s, rid)
    # Once registered, even malformed edits belong to this managed lifecycle.
    (d / FILENAME).write_text("handwritten private material")
    (d / TEMP).write_text("partial private bytes")
    (d / TEMP).chmod(0o600)
    payload = {"record_id": rid, "expected_revision": 1, "request_id": operation}
    if operation == "correct":
        payload["content"] = "corrected"
    s.execute(operation, payload)
    assert not (d / FILENAME).exists() and not (d / TEMP).exists()
    error("edit_terminal", lambda: s.execute("edit_preview", {"draft_id": did}))
    assert draft(s, rid) == did and not (d / FILENAME).exists()


def test_unrelated_write_preserves_draft_and_bare_backend_cannot_bypass(store):
    s, _, d = store
    rid = seed(s)
    draft(s, rid)
    seed(s, key="unrelated")
    assert (d / FILENAME).exists()
    bare, conn = opened(d, files=False)
    try:
        error(
            "edit_storage_required",
            lambda: bare.execute(
                "forget", {"record_id": rid, "expected_revision": 1, "request_id": "bad"}
            ),
        )
        assert s.execute("get", {"record_id": rid})["data"]["revision"] == 1
    finally:
        bare.close()
        conn.close()


def test_changed_preview_cannot_apply_and_failed_cleanup_rolls_back(store, monkeypatch):
    s, c, d = store
    rid = seed(s)
    did = draft(s, rid)
    request = apply_request(s, did)
    change_file(d)
    error("edit_digest_conflict", lambda: s.execute("edit_apply", request))
    request = apply_request(s, did)
    before = c.execute("SELECT count(*) FROM events").fetchone()

    def failed(*args, **kwargs):
        raise OSError("private-path-must-not-leak")

    monkeypatch.setattr(os, "unlink", failed)
    error("edit_io_error", lambda: s.execute("edit_apply", request))
    assert c.execute("SELECT count(*) FROM events").fetchone() == before
    assert s.execute("get", {"record_id": rid})["data"]["revision"] == 1


@pytest.mark.parametrize("name", [FILENAME, TEMP])
def test_unregistered_files_are_never_adopted_or_deleted(store, name):
    s, c, d = store
    rid = seed(s)
    p = d / name
    p.write_text("unknown")
    p.chmod(0o600)
    error("edit_file_conflict", lambda: draft(s, rid))
    assert p.read_text() == "unknown" and not c.execute("SELECT * FROM memory_edits").fetchall()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "directory", "fifo"])
def test_unsafe_registered_file_blocks_forget_without_mutation(store, kind):
    s, _, d = store
    rid = seed(s)
    draft(s, rid)
    p = d / FILENAME
    p.unlink()
    if kind == "symlink":
        p.symlink_to(d / "other")
    elif kind == "hardlink":
        other = d / "other"
        other.write_text("outside")
        other.chmod(0o600)
        p.hardlink_to(other)
    elif kind == "directory":
        p.mkdir()
    elif kind == "fifo":
        os.mkfifo(p, 0o600)
    else:
        p.write_text("x" * (32769 if kind == "oversize" else 1))
        p.chmod(0o600 if kind == "oversize" else 0o644)
    code = "edit_size_limit" if kind == "oversize" else "unsafe_edit_file"
    error(
        code,
        lambda: s.execute(
            "forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"}
        ),
    )
    assert s.execute("get", {"record_id": rid})["data"]["revision"] == 1


@pytest.mark.parametrize(
    "bad", ["identity", "duplicate", "blank", "control", "content_limit", "topic_limit"]
)
def test_format_rejects_metadata_replacement_and_invalid_fields(store, bad):
    s, _, d = store
    did = draft(s, seed(s))
    path = d / FILENAME
    lines = path.read_text().split("\n", 4)
    if bad == "identity":
        lines[1] = lines[1].replace('"test"', '"other"')
    if bad == "duplicate":
        lines[1] = lines[1][:-1] + ', "namespace": "test"}'
    if bad == "blank":
        lines[3] = "extra header"
    if bad == "control":
        lines[4] = "bad\x00"
    if bad == "content_limit":
        lines[4] = "字" * 2049
    if bad == "topic_limit":
        lines[2] = "Topic: " + json.dumps("字" * 129)
    path.write_text("\n".join(lines))
    error("edit_format_invalid", lambda: s.execute("edit_preview", {"draft_id": did}))


def test_ready_missing_file_not_reconstructed_and_discard_still_available(store):
    s, _, d = store
    rid = seed(s)
    did = draft(s, rid)
    (d / FILENAME).unlink()
    assert draft(s, rid) == did and not (d / FILENAME).exists()
    error("edit_file_missing", lambda: s.execute("edit_preview", {"draft_id": did}))
    s.execute("edit_discard", {"draft_id": did})
    assert draft(s, rid, key="new") != did


def test_schema_v8_requires_writable_migration(tmp_path):
    path = tmp_path / "records.sqlite3"
    conn = sqlite3.connect(path, isolation_level=None)
    # v8 strict schema includes FTS shadow tables; create those through official helper.
    from personal_agent import memory_fts, memory_projection
    from personal_agent.local_memory import _SCHEMA_V6

    for sql in {**_SCHEMA_V6, **memory_projection.SCHEMA}.values():
        conn.execute(sql)
    memory_fts.create_index(conn)
    assert (
        dict(conn.execute("SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"))
        == _SCHEMA_V8
    )
    conn.execute("INSERT INTO namespace VALUES ('test')")
    conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
    conn.execute("PRAGMA user_version=8")
    b = create_backend()
    error(
        "readonly_schema_unavailable",
        lambda: b.open_readonly(conn, namespace_id="test", session_ref="s"),
    )
    conn.close()
    conn = sqlite3.connect(path, isolation_level=None)
    b.open(conn, namespace_id="test", session_ref="s")
    assert conn.execute("PRAGMA user_version").fetchone() == (9,)
    assert conn.execute("SELECT * FROM memory_edits").fetchall() == []
    b.close()
    conn.close()


CHILD = r"""
import os,sqlite3,sys
from pathlib import Path
from personal_agent.local_memory import create_backend
from personal_agent.memory_edits import PrivateEdits
from personal_agent.memory_backend import MemoryService
stage,directory,operation,identifier,sha=sys.argv[1:]
class Crash(sqlite3.Connection):
    armed=False
    commits=0
    def execute(self,sql,*args):
        if self.armed and sql=='COMMIT' and stage=='before_commit':
            if operation!='create' or self.commits==1: os._exit(73)
        value=super().execute(sql,*args)
        if self.armed and sql=='COMMIT':
            self.commits+=1
            if stage=='after_prepare' and self.commits==1: os._exit(73)
            if stage=='after_commit' and (operation!='create' or self.commits==2): os._exit(73)
        return value
p=Path(directory); c=sqlite3.connect(p/'records.sqlite3',isolation_level=None,factory=Crash)
b=create_backend();b.open(c,namespace_id='test',session_ref='s',edits=PrivateEdits(p));s=MemoryService(b)
replace,write,unlink=os.replace,os.write,os.unlink
def replacing(*a,**k):
    v=replace(*a,**k)
    if stage=='after_replace':os._exit(73)
    return v
def writing(fd,data):
    if stage=='partial_temp':write(fd,data[:12]);os._exit(73)
    return write(fd,data)
def unlinking(*a,**k):
    v=unlink(*a,**k)
    if stage=='after_unlink':os._exit(73)
    return v
os.replace=replacing;os.write=writing;os.unlink=unlinking;c.armed=True
if operation=='create':
    s.execute('edit_create',{'record_id':identifier,'expected_revision':1,'request_id':'draft'})
elif operation=='apply':
    s.execute('edit_apply',{'draft_id':identifier,'expected_digest':sha,'request_id':'apply'})
elif operation=='discard':s.execute('edit_discard',{'draft_id':identifier})
else:s.execute('forget',{'record_id':identifier,'expected_revision':1,'request_id':'forget'})
raise RuntimeError('crash point not reached')
"""


def crash(stage, directory, operation, identifier, sha="unused"):
    result = subprocess.run(
        [sys.executable, "-c", CHILD, stage, str(directory), operation, identifier, sha],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 73, result.stderr


@pytest.mark.parametrize(
    "stage", ["after_prepare", "partial_temp", "after_replace", "before_commit", "after_commit"]
)
def test_create_process_crash_recovery_and_forget_fences(store, stage):
    s, c, d = store
    rid = seed(s)
    crash(stage, d, "create", rid)
    did = draft(s, rid)
    assert (
        s.execute("edit_preview", {"draft_id": did})["data"]["proposed"]["content"]
        == "原正文\n第二行"
    )
    s.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    assert not (d / FILENAME).exists() and not (d / TEMP).exists()
    assert draft(s, rid) == did and not (d / FILENAME).exists()
    assert c.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@pytest.mark.parametrize("stage", ["after_prepare", "partial_temp", "after_replace"])
def test_forget_directly_purges_crashed_create_without_needing_resume(store, stage):
    s, _, d = store
    rid = seed(s)
    crash(stage, d, "create", rid)
    s.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    assert not (d / FILENAME).exists() and not (d / TEMP).exists()
    draft(s, rid)
    assert not (d / FILENAME).exists()


@pytest.mark.parametrize("operation", ["apply", "discard", "forget"])
@pytest.mark.parametrize("stage", ["after_unlink", "before_commit", "after_commit"])
def test_mutation_process_crashes_have_truthful_db_and_no_payload_resurrection(
    store, operation, stage
):
    s, c, d = store
    rid = seed(s)
    did = draft(s, rid)
    change_file(d)
    request = apply_request(s, did)
    crash(stage, d, operation, rid if operation == "forget" else did, request["expected_digest"])
    current = s.execute("get", {"record_id": rid})["data"]
    assert not (d / FILENAME).exists()
    if stage != "after_commit":
        assert current["revision"] == 1
        error("edit_file_missing", lambda: s.execute("edit_preview", {"draft_id": did}))
        # Failed cleanup never authorizes silent reconstruction of user edits.
        s.execute("edit_discard", {"draft_id": did})
    elif operation == "apply":
        assert current["revision"] == 2
        assert s.execute("edit_apply", request)["replayed"]
    elif operation == "forget":
        assert current["status"] == "forgotten"
    else:
        assert current["revision"] == 1
        assert s.execute("edit_discard", {"draft_id": did})["replayed"]
    assert c.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_paused_create_after_durable_intent_cannot_publish_after_forget(store):
    s, _, d = store
    rid = seed(s)

    class Interleave(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and sql == "COMMIT":
                self.armed = False
                s.execute(
                    "forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"}
                )
            return result

    b, c = opened(d, factory=Interleave)
    c.armed = True
    try:
        error("edit_changed", lambda: draft(MemoryService(b), rid))
        assert not (d / FILENAME).exists()
    finally:
        b.close()
        c.close()


def test_renamed_crash_draft_preserves_hand_edits_when_create_resumes(store):
    s, _, d = store
    rid = seed(s)
    crash("after_replace", d, "create", rid)
    change_file(d, content="operator changed before recovery")
    did = draft(s, rid)
    assert (
        s.execute("edit_preview", {"draft_id": did})["data"]["proposed"]["content"]
        == "operator changed before recovery"
    )


def test_projection_invalidation_is_atomic_with_edit_application(store):
    s, _, d = store
    rid = seed(s)
    s.execute("projection_refresh", {})
    did = draft(s, rid)
    change_file(d)
    s.execute("edit_apply", apply_request(s, did))
    assert not (d / "records.md").exists()
    assert s.execute("projection_status", {})["data"]["dirty"]


def test_status_recovers_lost_identifier_and_missing_file_without_new_writes(store):
    s, c, d = store
    assert s.execute("edit_status", {})["data"]["active"] is None
    rid = seed(s)
    did = draft(s, rid)
    (d / FILENAME).unlink()
    before = c.total_changes
    status = s.execute("edit_status", {})["data"]
    assert status["active"]["draft_id"] == did and status["active"]["state"] == "ready"
    assert not status["file_present"] and c.total_changes == before
    s.execute("edit_discard", {"draft_id": did})
    assert s.execute("edit_status", {})["data"]["active"] is None
    replay = s.execute(
        "edit_create", {"record_id": rid, "expected_revision": 1, "request_id": "draft"}
    )
    assert replay["replayed"] and replay["data"]["state"] == "discarded"


def test_capacity_limits_new_drafts_not_cleanup_or_replay(store):
    from uuid import uuid4

    s, c, _ = store
    rid = seed(s)
    did = draft(s, rid)
    row = list(c.execute("SELECT * FROM memory_edits").fetchone())
    row[7], row[8] = "invalidated", None
    for n in range(999):
        row[0], row[3] = str(uuid4()), f"terminal-{n}"
        c.execute("INSERT INTO memory_edits VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
    s.execute("edit_discard", {"draft_id": did})
    error("edit_limit", lambda: draft(s, rid, key="new"))
    assert draft(s, rid) == did
    s.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})


@pytest.mark.parametrize("failure", ["replace", "write", "fsync"])
def test_publication_failure_preserves_recoverable_intent(store, monkeypatch, failure):
    s, c, d = store
    rid = seed(s)

    def broken(*args, **kwargs):
        raise OSError("secret-path")

    with monkeypatch.context() as m:
        m.setattr(os, failure, broken)
        error("edit_io_error", lambda: draft(s, rid))
    assert c.execute("SELECT state FROM memory_edits").fetchone() == ("preparing",)
    did = draft(s, rid)
    assert (
        s.execute("edit_preview", {"draft_id": did})["data"]["proposed"]["content"]
        == "原正文\n第二行"
    )
    assert (d / FILENAME).exists()


def test_sql_failure_after_cleanup_rolls_back_canonical_and_requires_discard(store):
    s, c, d = store
    rid = seed(s)
    did = draft(s, rid)
    change_file(d)
    request = apply_request(s, did)
    # A constrained receipt write fails after filesystem invalidation.
    c.execute(
        "CREATE TEMP TRIGGER fail_receipt BEFORE INSERT ON receipts "
        "BEGIN SELECT RAISE(ABORT,'fault'); END"
    )
    with pytest.raises(MemoryError):
        s.execute("edit_apply", request)
    assert s.execute("get", {"record_id": rid})["data"]["revision"] == 1
    assert not (d / FILENAME).exists()
    assert s.execute("edit_status", {})["data"]["active"]["state"] == "ready"
    s.execute("edit_discard", {"draft_id": did})


def test_actual_concurrent_forget_waits_for_create_publication_fence(store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    s, _, d = store
    rid = seed(s)
    entered, release, started = Event(), Event(), Event()
    original = PrivateEdits.publish_draft

    def paused(self, data):
        entered.set()
        assert release.wait(5)
        return original(self, data)

    monkeypatch.setattr(PrivateEdits, "publish_draft", paused)

    def creating():
        b, c = opened(d)
        try:
            return draft(MemoryService(b), rid)
        finally:
            b.close()
            c.close()

    def forgetting():
        started.set()
        b, c = opened(d)
        try:
            return b.execute(
                "forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"}
            )
        finally:
            b.close()
            c.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        create_future = pool.submit(creating)
        assert entered.wait(5)
        forget_future = pool.submit(forgetting)
        assert started.wait(5)
        assert not forget_future.done()
        release.set()
        did = create_future.result(timeout=10)
        forget_future.result(timeout=10)
    assert not (d / FILENAME).exists() and not (d / TEMP).exists()
    assert draft(s, rid) == did and not (d / FILENAME).exists()


def test_apply_requires_operator_and_readonly_never_opens_files(store):
    s, _, d = store
    rid = seed(s)
    did = draft(s, rid)
    backend = s.backend
    backend._source_kind = "activated_session_model"
    error("edit_scope_required", lambda: s.execute("edit_status", {}))
    backend._source_kind = "explicit_local_operator"
    c = sqlite3.connect(d / "records.sqlite3", isolation_level=None)
    b = create_backend()
    b.open_readonly(c, namespace_id="test", session_ref="s")
    try:
        error("edit_scope_required", lambda: b.execute("edit_preview", {"draft_id": did}))
    finally:
        b.close()
        c.close()


@pytest.mark.parametrize("operation", ["edit_discard", "forget"])
def test_safe_oversized_managed_paste_still_cleanable(store, operation):
    s, _, d = store
    rid = seed(s)
    did = draft(s, rid)
    (d / FILENAME).write_bytes(b"x" * 50000)
    error("edit_size_limit", lambda: s.execute("edit_preview", {"draft_id": did}))
    status = s.execute("edit_status", {})["data"]
    assert status["active"]["draft_id"] == did and status["file_present"]
    assert status["file_check_error"] is None
    payload = (
        {"draft_id": did}
        if operation == "edit_discard"
        else {"record_id": rid, "expected_revision": 1, "request_id": "forget"}
    )
    s.execute(operation, payload)
    assert not (d / FILENAME).exists()


def test_status_returns_recovery_id_even_when_file_is_unsafe(store):
    s, _, d = store
    did = draft(s, seed(s))
    (d / FILENAME).chmod(0o644)
    status = s.execute("edit_status", {})["data"]
    assert status["active"]["draft_id"] == did
    assert status["file_check_error"] == "unsafe_edit_file"
    assert status["file_present"] is None and status["staging_present"] is None
    assert (d / FILENAME).stat().st_mode & 0o777 == 0o644


def test_actual_apply_serializes_with_competing_correction(store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    s, _, d = store
    rid = seed(s)
    did = draft(s, rid)
    change_file(d, content="accepted editor text")
    request = apply_request(s, did)
    entered, release, started = Event(), Event(), Event()
    original = PrivateEdits.read_files

    def pause(self, registered):
        value = original(self, registered)
        entered.set()
        assert release.wait(5)
        return value

    monkeypatch.setattr(PrivateEdits, "read_files", pause)

    def applying():
        b, c = opened(d)
        try:
            return MemoryService(b).execute("edit_apply", request)
        finally:
            b.close()
            c.close()

    def correcting():
        started.set()
        b, c = opened(d)
        try:
            error(
                "revision_conflict",
                lambda: b.execute(
                    "correct",
                    {
                        "record_id": rid,
                        "expected_revision": 1,
                        "content": "stale competitor",
                        "request_id": "compete",
                    },
                ),
            )
        finally:
            b.close()
            c.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        edit = pool.submit(applying)
        assert entered.wait(5)
        competitor = pool.submit(correcting)
        assert started.wait(5)
        assert not competitor.done()
        release.set()
        assert edit.result(timeout=10)["data"]["record"]["revision"] == 2
        competitor.result(timeout=10)
    assert s.execute("get", {"record_id": rid})["data"]["content"] == "accepted editor text"
    assert not (d / FILENAME).exists()


def test_candidate_acceptance_preserves_unrelated_active_edit(store):
    from personal_agent.memory_candidate_store import digest

    s, _, d = store
    did = draft(s, seed(s))
    b = s.backend
    b._source_kind = "activated_session_model"
    proposed = s.execute(
        "candidate_propose",
        {
            "request_id": "candidate",
            "content": "new candidate",
            "quote": "candidate",
            "quote_start": 0,
            "source_digest": digest("source"),
            "source_turn": digest("turn"),
        },
    )
    b._source_kind = "explicit_local_operator"
    accepted = s.execute(
        "candidate_accept",
        {
            "candidate_id": proposed["data"]["candidate_id"],
            "expected_revision": 1,
            "expires_at": None,
        },
    )
    assert accepted["data"]["state"] == "accepted"
    assert s.execute("edit_status", {})["data"]["active"]["draft_id"] == did
    assert (d / FILENAME).exists()
