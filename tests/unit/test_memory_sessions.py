"""Managed acquisition/admission/cleanup failures on synthetic local resources."""

import sqlite3

import pytest
from test_memory_commands import private_store as private_store

from personal_agent import memory_storage
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_conformance import run_managed_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
from personal_agent.memory_sdk_example import SyntheticMemoryFactory
from personal_agent.memory_sessions import ResourceScope, managed_backend
from personal_agent.memory_storage import SQLiteMemoryFactory

BINDING = LocalBinding("synthetic-example", "synthetic-session")


class Cancelled(BaseException):
    pass


@pytest.mark.parametrize("kind", ["bundled", "independent"])
def test_shared_managed_conformance(tmp_path, kind):
    factory = (
        SQLiteMemoryFactory(tmp_path / "records.sqlite3", tmp_path)
        if kind == "bundled"
        else SyntheticMemoryFactory(tmp_path)
    )
    assert len(run_managed_conformance(factory, BINDING, isolated_synthetic=True).passed) == 10


@pytest.mark.parametrize("primary", [None, RuntimeError("primary"), Cancelled("primary")])
@pytest.mark.parametrize("cleanup_error", [RuntimeError("private"), Cancelled("private")])
def test_registry_order_exhaustion_and_primary_identity(primary, cleanup_error):
    scope = ResourceScope()
    calls = []

    def cleanup(name):
        calls.append(name)
        raise cleanup_error

    for name in ("connection", "backend"):
        scope.register(lambda name=name: cleanup(name))
    if primary is None:
        with pytest.raises(MemoryError) as caught:
            scope.close()
        assert caught.value.code == "cleanup_failed" and not caught.value.retryable
        assert "private" not in str(caught.value)
    else:
        scope.close(primary=primary)
        with pytest.raises(MemoryError, match="cleanup_failed"):
            scope.close()
    scope.close()
    assert calls == ["backend", "connection"]
    with pytest.raises(MemoryError, match="invalid_resource_registration"):
        scope.register(lambda: None)


class FaultFactory:
    factory_version = 1

    def __init__(self, directory, stage, error, cleanup_error=None):
        self.factory = SyntheticMemoryFactory(directory)
        self.stage, self.error, self.cleanup_error = stage, error, cleanup_error
        self.calls = []

    def acquire(self, resources, binding, mode):
        def cleanup():
            self.calls.append("cleanup")
            if self.cleanup_error:
                raise self.cleanup_error

        resources.register(cleanup)
        if self.stage == "acquire":
            raise self.error
        backend = self.factory.acquire(resources, binding, mode)
        original_describe, original_execute = backend.describe, backend.execute

        def describe():
            if self.stage == "describe":
                raise self.error
            return original_describe()

        def execute(operation, payload):
            if self.stage == "export" and operation == "export":
                raise self.error
            result = original_execute(operation, payload)
            if self.stage == "namespace" and operation == "export":
                result["data"]["namespace_id"] = "wrong"
            if self.stage == "write" and operation == "remember":
                raise self.error
            return result

        backend.describe, backend.execute = describe, execute
        return backend


@pytest.mark.parametrize("stage", ["acquire", "describe", "export", "namespace", "body"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_failures_release_registered_resources(tmp_path, stage, cancelled):
    error = Cancelled("primary") if cancelled else RuntimeError("primary")
    factory = FaultFactory(tmp_path, stage, error, Cancelled("cleanup private"))
    with pytest.raises(BaseException) as caught:
        with LocalMemorySDK.session(factory, BINDING, mode="writable") as sdk:
            assert stage == "body"
            raise error
    if stage in {"acquire", "body"} or (cancelled and stage != "namespace"):
        assert caught.value is error
    else:
        assert isinstance(caught.value, MemoryError)
        assert caught.value.code == "unsupported_backend"
    assert factory.calls == ["cleanup"]
    if stage == "body":
        with pytest.raises(MemoryError, match="closed"):
            sdk.execute("list", {})
    with LocalMemorySDK.session(SyntheticMemoryFactory(tmp_path), BINDING, mode="writable"):
        pass


def test_unknown_committed_write_wins_over_cleanup_and_replays(tmp_path):
    factory = FaultFactory(tmp_path, "write", RuntimeError("lost ack"), RuntimeError("cleanup"))
    request = {"content": "synthetic", "request_id": "same"}
    with pytest.raises(MemoryError) as caught:
        with LocalMemorySDK.session(factory, BINDING, mode="writable") as sdk:
            sdk.execute("remember", request)
    assert caught.value.code == "outcome_unknown" and not caught.value.retryable
    with LocalMemorySDK.session(SyntheticMemoryFactory(tmp_path), BINDING, mode="writable") as sdk:
        assert sdk.execute("remember", request)["replayed"] is True
        assert len(sdk.execute("list", {})["data"]["items"]) == 1


def test_explicit_close_failure_is_once_and_invalidates(tmp_path):
    factory = FaultFactory(tmp_path, "none", None, Cancelled("cleanup private"))
    with LocalMemorySDK.session(factory, BINDING, mode="writable") as sdk:
        with pytest.raises(MemoryError, match="cleanup_failed"):
            sdk.close()
        sdk.close()
        with pytest.raises(MemoryError, match="closed"):
            sdk.execute("list", {})
    assert factory.calls == ["cleanup"]


@pytest.mark.parametrize(
    "operation",
    [
        "remember",
        "correct",
        "forget",
        "consumer_advance",
        "checkpoint_create",
        "source_stage",
        "source_accept",
        "source_discard",
    ],
)
def test_readonly_refuses_before_validation_or_backend_dispatch(tmp_path, operation):
    with LocalMemorySDK.session(SyntheticMemoryFactory(tmp_path), BINDING, mode="readonly") as sdk:
        sdk._service.backend.execute = lambda *args: pytest.fail("unexpected dispatch")
        with pytest.raises(MemoryError, match="read_only"):
            sdk.execute(operation, {})


@pytest.mark.parametrize(
    "field,value", [("factory_version", True), ("factory_version", 2), ("acquire", None)]
)
def test_factory_validation_before_acquire(field, value):
    class Factory:
        factory_version = 1

        def acquire(self, *args):
            pytest.fail("must not acquire")

    factory = Factory()
    setattr(factory, field, value)
    with pytest.raises(MemoryError, match="unsupported_factory"):
        with managed_backend(factory, BINDING, mode="writable"):
            pass


@pytest.mark.parametrize("binding,mode", [(None, "writable"), (BINDING, []), (BINDING, "other")])
def test_request_validation_before_acquire(binding, mode):
    with pytest.raises(MemoryError, match="invalid_request"):
        with managed_backend(object(), binding, mode=mode):
            pass


@pytest.mark.parametrize("reader", [False, True])
@pytest.mark.parametrize("stage", ["connect", "constructor", "pragma", "open", "close"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_real_openers_cleanup_and_reopen(private_store, monkeypatch, reader, stage, cancelled):
    home, _ = private_store
    with memory_storage.open_memory_backend(home, "synthetic"):
        pass
    calls = []
    error = Cancelled("private") if cancelled else RuntimeError("private")
    original_connect, original_create = (
        memory_storage.sqlite3.connect,
        memory_storage.create_backend,
    )

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, *args, **kwargs):
            if stage == "pragma":
                raise error
            return self.connection.execute(*args, **kwargs)

        def close(self):
            calls.append("connection")
            self.connection.close()

    def connect(*args, **kwargs):
        if stage == "connect":
            raise error
        return Connection(original_connect(*args, **kwargs))

    def create():
        if stage == "constructor":
            raise error
        backend = original_create()
        original_close = backend.close

        def fail_open(*args, **kwargs):
            raise error

        def close():
            calls.append("backend")
            original_close()
            if stage == "close":
                raise error

        if stage == "open":
            backend.open = backend.open_readonly = fail_open
        backend.close = close
        return backend

    opener = (
        memory_storage.open_existing_memory_reader if reader else memory_storage.open_memory_backend
    )
    with monkeypatch.context() as patch:
        patch.setattr(memory_storage.sqlite3, "connect", connect)
        patch.setattr(memory_storage, "create_backend", create)
        with pytest.raises(BaseException) as caught:
            with opener(home, "synthetic"):
                assert stage == "close"
        if stage == "close":
            assert isinstance(caught.value, MemoryError)
            assert caught.value.code == "cleanup_failed"
        else:
            assert caught.value is error
    assert calls == (
        []
        if stage == "connect"
        else ["connection"]
        if stage == "constructor"
        else ["backend", "connection"]
    )
    with opener(home, "synthetic") as backend:
        backend.execute("list", {})
    from personal_agent.memory_coordination import memory_lock

    with memory_lock(home, exclusive=True, timeout=0.03):
        pass


def test_already_open_constructor_does_not_own_connection(tmp_path):
    from personal_agent.local_memory import create_backend

    connection = sqlite3.connect(tmp_path / "original.sqlite3")
    backend = create_backend()
    backend.open(connection, namespace_id=BINDING.namespace_id, session_ref=BINDING.session_ref)
    sdk = LocalMemorySDK(backend, BINDING)
    sdk.close()
    assert connection.execute("SELECT 1").fetchone() == (1,)
    connection.close()


@pytest.mark.parametrize("reader", [False, True])
def test_body_identity_survives_backend_connection_and_lock_cleanup(
    private_store, monkeypatch, reader
):
    home, _ = private_store
    with memory_storage.open_memory_backend(home, "synthetic"):
        pass
    from personal_agent import memory_coordination

    original_connect = memory_storage.sqlite3.connect
    original_create = memory_storage.create_backend
    original_close = memory_coordination.os.close
    calls = []
    primary = MemoryError("outcome_unknown")

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def close(self):
            calls.append("connection")
            self.connection.close()
            raise Cancelled("connection cleanup private")

    def create():
        backend = original_create()
        close_backend = backend.close

        def close():
            calls.append("backend")
            close_backend()
            raise Cancelled("backend cleanup private")

        backend.close = close
        return backend

    def close_fd(fd):
        original_close(fd)
        calls.append("fd")
        raise Cancelled("lock cleanup private")

    with monkeypatch.context() as patch:
        patch.setattr(
            memory_storage.sqlite3,
            "connect",
            lambda *a, **kw: Connection(original_connect(*a, **kw)),
        )
        patch.setattr(memory_storage, "create_backend", create)
        opener = (
            memory_storage.open_existing_memory_reader
            if reader
            else memory_storage.open_memory_backend
        )
        with pytest.raises(MemoryError) as caught:
            with opener(home, "synthetic"):
                # Inject only after admission: raw header has already closed.
                patch.setattr(memory_coordination.os, "close", close_fd)
                raise primary
        assert caught.value is primary
    assert calls == ["backend", "connection", "fd"]
    with memory_coordination.memory_lock(home, exclusive=True, timeout=0.03):
        pass


def test_header_failure_preserves_primary_and_attempts_close(private_store, monkeypatch):
    home, _ = private_store
    with memory_storage.open_memory_backend(home, "synthetic"):
        pass
    original_close = memory_storage.os.close
    primary = Cancelled("header primary")
    calls = []

    def fail_read(*args):
        raise primary

    def close(fd):
        calls.append(fd)
        original_close(fd)
        raise RuntimeError("cleanup private")

    with monkeypatch.context() as patch:
        patch.setattr(memory_storage.os, "read", fail_read)
        patch.setattr(memory_storage.os, "close", close)
        with pytest.raises(Cancelled) as caught:
            with memory_storage.open_existing_memory_reader(home, "synthetic"):
                pytest.fail("must not admit")
        assert caught.value is primary
    assert len(calls) == 2  # Header descriptor and maintenance lock.
    with memory_storage.open_existing_memory_reader(home, "synthetic"):
        pass


@pytest.mark.parametrize("primary", [MemoryError("outcome_unknown"), Cancelled("body")])
def test_explicit_close_in_finally_preserves_primary(tmp_path, primary):
    factory = FaultFactory(tmp_path, "none", None, Cancelled("private cleanup"))
    with pytest.raises(BaseException) as caught:
        with LocalMemorySDK.session(factory, BINDING, mode="writable") as sdk:
            try:
                raise primary
            finally:
                sdk.close()
    assert caught.value is primary
    assert factory.calls == ["cleanup"]
    with pytest.raises(MemoryError, match="closed"):
        sdk.execute("list", {})


def test_reader_preserves_body_sqlite_failure(private_store, monkeypatch):
    home, _ = private_store
    with memory_storage.open_memory_backend(home, "synthetic"):
        pass
    original_create = memory_storage.create_backend
    primary = sqlite3.OperationalError("body")

    def create():
        backend = original_create()
        original_close = backend.close

        def close():
            original_close()
            raise RuntimeError("cleanup")

        backend.close = close
        return backend

    monkeypatch.setattr(memory_storage, "create_backend", create)
    with pytest.raises(sqlite3.OperationalError) as caught:
        with memory_storage.open_existing_memory_reader(home, "synthetic"):
            raise primary
    assert caught.value is primary


@pytest.mark.parametrize("explicit", [False, True])
def test_unrelated_handled_exception_cannot_hide_sdk_cleanup(tmp_path, explicit):
    factory = FaultFactory(tmp_path, "none", None, Cancelled("private cleanup"))
    try:
        raise ValueError("unrelated handled error")
    except ValueError:
        with pytest.raises(MemoryError, match="cleanup_failed") as caught:
            with LocalMemorySDK.session(factory, BINDING, mode="writable") as sdk:
                if explicit:
                    sdk.close()
                    sdk.close()
        assert not caught.value.retryable
    assert factory.calls == ["cleanup"]
    with pytest.raises(MemoryError, match="closed"):
        sdk.execute("list", {})


def test_explicit_close_with_handled_body_error_reports_at_successful_exit(tmp_path):
    factory = FaultFactory(tmp_path, "none", None, Cancelled("private cleanup"))
    with pytest.raises(MemoryError, match="cleanup_failed"):
        with LocalMemorySDK.session(factory, BINDING, mode="writable") as sdk:
            try:
                raise ValueError("handled inside body")
            except ValueError:
                sdk.close()
    assert factory.calls == ["cleanup"]


@pytest.mark.parametrize("boundary", ["lock", "header"])
def test_unrelated_handled_exception_cannot_hide_fd_cleanup(private_store, monkeypatch, boundary):
    from personal_agent.memory_coordination import memory_lock

    home, _ = private_store
    with memory_storage.open_memory_backend(home, "synthetic"):
        pass
    original_close = memory_storage.os.close
    calls = []

    def close(fd):
        original_close(fd)
        calls.append(fd)
        raise Cancelled("private cleanup")

    with monkeypatch.context() as patch:
        patch.setattr(memory_storage.os, "close", close)
        try:
            raise ValueError("unrelated handled error")
        except ValueError:
            with pytest.raises(MemoryError, match="cleanup_failed") as caught:
                if boundary == "lock":
                    with memory_lock(home):
                        pass
                else:
                    with memory_storage.open_existing_memory_reader(home, "synthetic"):
                        pytest.fail("header close failure must prevent admission")
            assert not caught.value.retryable
    assert len(calls) == (1 if boundary == "lock" else 2)
    with memory_lock(home, exclusive=True, timeout=0.03):
        pass


def test_deferred_cleanup_preserves_later_propagating_body_error(tmp_path):
    factory = FaultFactory(tmp_path, "none", None, Cancelled("private cleanup"))
    primary = MemoryError("outcome_unknown")
    with pytest.raises(MemoryError) as caught:
        with LocalMemorySDK.session(factory, BINDING, mode="writable") as sdk:
            try:
                raise ValueError("handled first")
            except ValueError:
                sdk.close()
            raise primary
    assert caught.value is primary
    assert factory.calls == ["cleanup"]
