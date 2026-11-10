"""Native delegation routing/stop boundaries, not live scheduler authority.

Child execution and async submission are inert. Native dispatch, reattachment,
stop propagation and parallel joins remain real; no model or transport is used.
"""

import json
import threading
import time
from types import SimpleNamespace

import pytest


def batch_for(children=1):
    from tools.delegate_tool_dispatch import _Batch

    parent = SimpleNamespace(_active_children=[], _interrupt_requested=False, tools=[])
    kids = [SimpleNamespace(_interrupt_requested=False) for _ in range(children)]
    parent._active_children.extend(kids)
    tasks = [{"goal": f"synthetic-{i}"} for i in range(children)]
    return _Batch(
        task_list=tasks,
        children=[(i, tasks[i], c) for i, c in enumerate(kids)],
        parent_agent=parent,
        creds={"model": None},
        context=None,
        top_role="leaf",
        max_children=children,
        live_deleg_id=None,
        live_writers=[],
        live_paths=[],
        origin_wake_sid="",
        origin_ui_session_id="",
        origin_owner_transport=None,
        origin_owner_session_record=None,
        origin_session_history_delivery=False,
        overall_start=time.monotonic(),
    )


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("finite", None),
        ("oneshot", None),
        ("unsupported", None),
        ("history", "synthetic-session"),
        ("probe-error", ""),
    ],
)
def test_async_delivery_resolution_boundaries(monkeypatch, mode, expected):
    from gateway import session_context, session_finite
    from tools.delegate_tool_dispatch import _resolve_async_wake_sid

    monkeypatch.setattr(session_finite, "finite_turn_required", lambda: mode == "finite")
    monkeypatch.setattr(session_context, "get_session_env", lambda *_: "")

    def supported():
        if mode == "probe-error":
            raise RuntimeError("synthetic capability probe failure")
        return False

    monkeypatch.setattr(session_context, "async_delivery_supported", supported)
    assert (
        _resolve_async_wake_sid(
            "synthetic-session", mode == "history", oneshot_session=mode == "oneshot"
        )
        == expected
    )
    # In particular an exception returns the detached push-route sentinel, not None.


def test_session_tool_pin_joins_background_request(monkeypatch):
    from tools import delegate_tool
    from tools import delegate_tool_dispatch as dispatch

    batch = batch_for()
    batch.parent_agent.tools = [
        {
            "function": {
                "name": "delegate_task",
                "description": delegate_tool._ONESHOT_DESCRIPTION_DELIVERY,
            }
        }
    ]
    effects = []
    monkeypatch.setattr(dispatch, "begin_delegation_run", lambda *a, **k: None)
    monkeypatch.setattr(
        dispatch, "_execute_and_aggregate", lambda b: effects.append(b) or {"results": []}
    )
    monkeypatch.setattr(dispatch, "_dispatch_background", lambda b: pytest.fail("must join"))
    assert delegate_tool.session_joins_delegation(batch.parent_agent)
    assert json.loads(dispatch._run_batch(batch, True)) == {"results": []}
    assert effects == [batch]
    batch.parent_agent._oneshot_session = True
    assert not delegate_tool.session_joins_delegation(batch.parent_agent)


@pytest.mark.parametrize("rejection", [None, "capacity", "session refused"])
def test_background_fallback_is_execution_not_authorization(monkeypatch, rejection):
    from tools import delegate_tool
    from tools import delegate_tool_dispatch as dispatch

    batch = batch_for()
    child = batch.children[0][2]
    admissions, effects = [], []
    monkeypatch.setattr(
        dispatch, "_resolve_async_wake_sid", lambda *a, **k: None if rejection is None else ""
    )
    monkeypatch.setattr(dispatch, "_resolve_async_session_key", lambda *a: ("synthetic", ""))
    monkeypatch.setattr(dispatch, "_units_of", lambda b: [b])
    monkeypatch.setattr(delegate_tool, "_get_max_async_children", lambda: 1)

    def reject(unit, *args):
        assert child not in batch.parent_agent._active_children
        admissions.append(unit)
        batch.parent_agent._interrupt_requested = True
        return {"status": "rejected", "error": rejection}

    def execute(b):
        assert child in b.parent_agent._active_children
        # Reattachment replays the stop, but fallback still invokes execution.
        assert child._interrupt_requested is (rejection is not None)
        effects.append("inert-child-endpoint")
        return {"results": []}

    monkeypatch.setattr(dispatch, "_dispatch_unit", reject)
    monkeypatch.setattr(dispatch, "_execute_and_aggregate", execute)
    result = json.loads(dispatch._dispatch_background(batch))
    assert len(admissions) == (0 if rejection is None else 1)
    assert effects == ["inert-child-endpoint"]
    assert "SYNCHRONOUSLY" in result["note"]


def test_detached_callback_stops_child_but_does_not_undo_effect(monkeypatch):
    from tools import async_delegation
    from tools import delegate_tool_dispatch as dispatch

    batch = batch_for(2)
    captured, effects = {}, []
    monkeypatch.setattr(
        async_delegation,
        "dispatch_async_delegation_batch",
        lambda **kw: captured.update(kw) or {"status": "dispatched"},
    )

    def execute(unit, *, honor_parent_interrupt):
        assert honor_parent_interrupt is False
        effects.append("already-admitted")
        return {"results": []}

    monkeypatch.setattr(dispatch, "_execute_and_aggregate", execute)
    dispatch._dispatch_unit(batch, "synthetic-id", None, {})
    captured["runner"]()
    captured["interrupt_fn"]()
    assert all(c._interrupt_requested for _, _, c in batch.children)
    assert effects == ["already-admitted"]


@pytest.mark.parametrize("honor_parent", [True, False])
def test_parent_join_interrupt_is_not_child_effect_revocation(monkeypatch, honor_parent):
    from tools import delegate_tool_config
    from tools import delegate_tool_dispatch as dispatch

    batch = batch_for(2)
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()
    finished = [threading.Event(), threading.Event()]
    effects, results, failures, workers = [], [], [], []
    monkeypatch.setattr(delegate_tool_config, "_get_prefix_stagger_seconds", lambda: 0)
    monkeypatch.setattr(dispatch, "_report_child_done", lambda *a: None)

    def run(i, task, child):
        workers.append(threading.current_thread())
        entered[i].set()
        try:
            assert release.wait(5), "test failed to release inert child"
            effects.append(i)
            return {"task_index": i, "status": "completed"}
        finally:
            finished[i].set()

    batch.run_child = run

    def join():
        try:
            dispatch._run_children_parallel(batch, results, honor_parent_interrupt=honor_parent)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=join)
    thread.start()
    try:
        assert all(e.wait(3) for e in entered)
        batch.parent_agent._interrupt_requested = True
        if honor_parent:
            thread.join(2)
            assert not thread.is_alive()
            assert [r["status"] for r in results] == ["interrupted", "interrupted"]
            assert effects == []
        else:
            thread.join(0.1)
            assert thread.is_alive()
    finally:
        release.set()
        assert all(e.wait(3) for e in finished)
        thread.join(3)
        for worker in workers:
            worker.join(3)
            assert not worker.is_alive()
    assert not thread.is_alive() and failures == []
    assert sorted(effects) == [0, 1]
    if not honor_parent:
        assert [r["status"] for r in results] == ["completed", "completed"]
