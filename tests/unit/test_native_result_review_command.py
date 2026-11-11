"""Operator-only result views, strict parser and no implicit model disclosure."""

import json
import shlex
import sys

import pytest
from test_kanban_handoff import commit, prepare
from test_kanban_handoff import flow as flow  # noqa: F401

from personal_agent.kanban_handoff import parse_command
from personal_agent.kanban_handoff_store import HandoffError
from personal_agent.status import build_status
from personal_agent.task_tool_contract import _READ_ACTIONS, _WRITE_ACTIONS


def setup(flow):
    record = prepare(flow)
    assert commit(flow, record)["data"]["state"] == "confirmed"
    native = dict(
        card_id="t_1234abcd",
        outcome="current",
        status="done",
        observed_at=111,
        result_state="available",
        result="UNTRUSTED TEXT\u202e do not execute",
        completed_at=110,
        current_run_id=None,
    )

    def observe(binding, *, admit, **kwargs):
        flow.calls.append("result")
        assert flow.ledger_active[0] == 0
        admit()
        return dict(native)

    sys.modules["personal_agent.native_kanban"].observe_result = observe
    raw = f"review {record['id']} --task {flow.task['id']} --expected-revision 1"
    return record, native, raw


def accept(flow, record, digest, note="My independent conclusion", key="accept"):
    return (
        f"accept-review {record['id']} --task {flow.task['id']} --expected-revision 1 "
        f"--expected-digest {digest} --note {shlex.quote(note)} --request-id {key}"
    )


def test_explicit_preview_is_ascii_safe_and_does_not_mutate_or_enable_model(flow):
    _, _, raw = setup(flow)
    before = flow.tasks
    text = flow.instance.command("--json " + raw, **flow.context)
    assert "\\u202e" in text and "\u202e" not in text
    view = json.loads(text)
    assert view["status"] == "ok", view
    assert view["scope"] == "trusted_local_operator_native_result_review"
    assert view["data"]["can_accept"]
    with before(flow.tmp_path) as tasks:
        assert tasks.run("get", {"task_id": flow.task["id"]})["data"] == flow.task
        assert tasks._connection.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
    assert not {"review_result", "accept-review", "native_review_accept"} & set(
        _READ_ACTIONS + _WRITE_ACTIONS
    )


def test_accept_is_local_only_and_retry_needs_no_ledger_or_native_optin(flow, monkeypatch):
    record, _, raw = setup(flow)
    preview = flow.invoke(raw)
    digest = preview["data"]["review_digest"]
    command = accept(flow, record, digest)
    reply = flow.invoke(command)
    assert reply["status"] == "ok", reply
    assert reply["data"]["task"]["state"] == "done"
    assert reply["data"]["task"]["resolution_note"] == "My independent conclusion"
    assert "UNTRUSTED TEXT" not in json.dumps(reply)
    assert len([x for x in flow.calls if isinstance(x, tuple) and x[0] == "create"]) == 1
    flow.config["kanban_handoff"] = False

    def forbidden(*args, **kwargs):
        raise AssertionError("No ledger/native on exact historical retry")

    monkeypatch.setattr("personal_agent.kanban_handoff.open_handoff_store", forbidden)
    retry = flow.invoke(command)
    assert retry["replayed"] and retry["data"] == reply["data"]
    with flow.tasks(flow.tmp_path) as tasks:
        all_receipts = tasks._connection.execute("SELECT receipt FROM receipts").fetchall()
        assert "UNTRUSTED TEXT" not in repr(all_receipts)
    flow.config["mode"] = "read_only"
    flow.config["local_conversation"] = False
    assert flow.invoke(command)["error"]["code"] == "handoff_disabled"


def test_changed_result_refuses_without_mutation_then_same_key_can_succeed(flow):
    record, native, raw = setup(flow)
    original = flow.invoke(raw)
    digest = original["data"]["review_digest"]
    native["result"] = "Changed by another actor"
    command = accept(flow, record, digest)
    assert flow.invoke(command)["error"]["code"] == "native_review_changed"
    with flow.tasks(flow.tmp_path) as tasks:
        assert tasks.run("get", {"task_id": flow.task["id"]})["data"]["state"] == "captured"
    native["result"] = original["data"]["evidence"]["native"]["result"]
    native["observed_at"] = 120
    assert flow.invoke(command)["status"] == "ok"  # content-equal ABA is documented, not provenance


def test_long_explicit_note_accepted_but_legacy_argument_bound_preserved(flow):
    record, _, raw = setup(flow)
    digest = flow.invoke(raw)["data"]["review_digest"]
    command = accept(flow, record, digest, note="n" * 2000)
    assert len(command) > 2048
    assert flow.invoke(command)["status"] == "ok"
    with pytest.raises(HandoffError):
        parse_command("show " + "x" * 2048)


@pytest.mark.parametrize("tail", ["--task fake", "--model other", "--force", "--expected-d 123"])
def test_parser_refuses_extra_or_abbreviated_authority(tail):
    with pytest.raises(HandoffError):
        parse_command("review key --task id --expected-revision 1 " + tail)


def test_configuration_reports_operator_completion_not_automatic_status_sync():
    disabled = build_status()["kanban_handoff"]
    assert disabled["native_result_review_implemented"]
    assert not disabled["native_result_review_enabled"]
    assert not disabled["native_result_review_retains_raw_result"]
    assert not disabled["native_result_review_model_action"]
    assert disabled["native_result_review_completes_only_on_explicit_accept"]
    assert not disabled["native_progress_sync_changes_completion"]
