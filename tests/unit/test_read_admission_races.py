"""Real SQLite contention with explicitly synthetic authority/resource adapters."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from test_read_admission import (
    GRANT,
    KEY,
    REQUEST,
    SUMMARY,
    SyntheticHost,
    SyntheticSource,
    scope,
)

from personal_agent.enrollment import EnrollmentStore
from personal_agent.read_admission import ReadAdmissionError, ReadAdmissionService


def initialize(path):
    with sqlite3.connect(path) as connection:
        store = EnrollmentStore(connection)
        store.initialize()
        store.run(
            "create",
            {
                **KEY,
                "transport_id": "telegram",
                "transport_receiver_id": "bot",
                "principal_id": "actor",
                "scope": scope(),
            },
        )


@pytest.mark.parametrize("change", ["revoke", "set_policy"])
def test_admitted_summary_finishes_before_waiting_policy_mutation(tmp_path, change):
    path = tmp_path / "fenced-read.sqlite3"
    initialize(path)
    ready = Barrier(2)
    reading, mutating, mutated = Event(), Event(), Event()
    observed = []

    def reader():
        connection = sqlite3.connect(path)
        try:
            store = EnrollmentStore(connection)
            store.initialize()
            host, source = SyntheticHost(observed), SyntheticSource(observed)

            def hold_snapshot():
                reading.set()
                assert mutating.wait(5)
                assert not mutated.is_set()

            source.on_read = hold_snapshot
            service = ReadAdmissionService(
                store, host_authority=host, resource_source=source, enabled=True
            )
            ready.wait(timeout=5)
            result = service.read(KEY, REQUEST, live_handle=host.handle)
            assert not connection.in_transaction
            return result
        finally:
            connection.close()

    def writer():
        connection = sqlite3.connect(path)
        try:
            store = EnrollmentStore(connection)
            store.initialize()
            ready.wait(timeout=5)
            assert reading.wait(5)
            connection.set_trace_callback(
                lambda sql: mutating.set() if sql == "BEGIN IMMEDIATE" else None
            )
            request = {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1}
            if change == "set_policy":
                request["scope"] = scope()
            result = store.run(change, request)
            mutated.set()
            return result
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_result, mutation_result = pool.submit(reader), pool.submit(writer)
        assert read_result.result(timeout=10) == (SUMMARY,)
        assert mutation_result.result(timeout=10)["epoch"] == 1
    assert mutated.is_set()
    assert observed.index("read") < observed.index("snapshot_exit") < observed.index("host_exit")
    # A separate fresh attempt with the old confirmation cannot reuse its permit.
    with sqlite3.connect(path) as connection:
        store = EnrollmentStore(connection)
        store.initialize()
        events = []
        host, source = SyntheticHost(events), SyntheticSource(events)
        service = ReadAdmissionService(
            store, host_authority=host, resource_source=source, enabled=True
        )
        with pytest.raises(ReadAdmissionError, match="policy_denied"):
            service.read(KEY, REQUEST, live_handle=host.handle)
        assert "ownership" not in events and "read" not in events
        history = store.read_admission_history(KEY)["items"]
        assert len(history) == 1
        assert history[0]["epoch"] == 0
        assert history[0]["policy_revision"] == 1
        assert history[0]["outcome"] == "snapshot_prepared"


def test_confirmation_expires_while_waiting_for_sqlite_before_resource_access(tmp_path):
    path = tmp_path / "wait-expiry.sqlite3"
    initialize(path)
    ready, proceed, attempted = Event(), Event(), Event()
    events = []
    host, source = SyntheticHost(events), SyntheticSource(events)

    def reader():
        connection = sqlite3.connect(path)
        try:
            store = EnrollmentStore(connection)
            store.initialize()
            connection.set_trace_callback(
                lambda sql: attempted.set() if sql == "BEGIN IMMEDIATE" else None
            )
            service = ReadAdmissionService(
                store, host_authority=host, resource_source=source, enabled=True
            )
            ready.set()
            assert proceed.wait(5)
            with pytest.raises(ReadAdmissionError, match="authorization_denied"):
                service.read(KEY, REQUEST, live_handle=host.handle)
            assert not connection.in_transaction
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool, sqlite3.connect(path) as blocker:
        result = pool.submit(reader)
        assert ready.wait(5)
        blocker.execute("BEGIN IMMEDIATE")
        proceed.set()
        assert attempted.wait(5)
        assert events == ["host_enter", "clock"]
        host.now = GRANT.expires_at
        blocker.commit()
        result.result(timeout=10)
    assert "ownership" not in events and "read" not in events
    assert host.used and events[-1] == "host_exit"
