"""Managed bundled lifetimes through real native dispatch, synthetic/offline only."""

import importlib
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_local_memory_commands as memory
import test_memory_process_restart as process
import test_observed_source_retention as sources
import test_session_memory_recall as recall
import test_session_memory_tools as model
from test_local_task_cli import PLUGIN_ID, install

native = model.native
host = model.host


def module(host, name):
    prefix = host.manager._plugins[PLUGIN_ID].module.__name__ + ".personal_agent."
    return importlib.import_module(prefix + name)


class ObservedConnection(sqlite3.Connection):
    """Observe cleanup on its native dispatch thread without relaxing affinity."""

    close_calls = 0

    def close(self):
        self.close_calls += 1
        super().close()
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            self.execute("SELECT 1")


@pytest.fixture
def acquisitions(host, monkeypatch):
    storage = module(host, "memory_storage")
    local = module(host, "local_memory")
    sdk = module(host, "memory_sdk")
    acquired = []
    connect = sqlite3.connect

    def observed_connect(*args, **kwargs):
        return connect(*args, **kwargs, factory=ObservedConnection)

    monkeypatch.setattr(
        storage, "sqlite3", SimpleNamespace(connect=observed_connect, Error=sqlite3.Error)
    )
    original = storage.SQLiteMemoryFactory.acquire
    execute = local.LocalMemoryBackend.execute

    def no_sdk(*args, **kwargs):
        pytest.fail("Production readers must not invoke SDK export admission")

    def no_export(self, operation, payload):
        assert operation != "export", "Production route must not probe export"
        return execute(self, operation, payload)

    def track(self, resources, binding, mode):
        backend = original(self, resources, binding, mode)
        acquired.append((mode, binding.source_kind, backend, backend._connection))
        if mode == "readonly":
            assert backend._connection.execute("PRAGMA query_only").fetchone() == (1,)
        return backend

    monkeypatch.setattr(storage.SQLiteMemoryFactory, "acquire", track)
    monkeypatch.setattr(sdk.LocalMemorySDK, "__init__", no_sdk)
    monkeypatch.setattr(local.LocalMemoryBackend, "execute", no_export)
    yield acquired
    for _, _, backend, connection in acquired:
        assert backend._connection is None
        assert connection.close_calls == 1


def test_native_command_model_recall_and_source_use_managed_bundle(host, acquisitions):
    saved = recall.save(host)
    assert acquisitions[-1][:2] == ("writable", "explicit_local_operator")
    model.activate(host)
    with model.turn(host):
        result = model.call(
            host,
            {"action": "remember", "content": "synthetic coffee", "request_id": "model-managed"},
            write=True,
        )
        assert result["status"] == "ok", result
        assert acquisitions[-1][:2] == ("writable", "activated_session_model")
        assert model.call(host, {"action": "list"})["status"] == "ok"
    recall.enable(host)
    before = memory.database(host.home).read_bytes()
    with model.turn(host):
        assert saved["record_id"] in recall.collect(host)
    assert acquisitions[-1][0] == "readonly"
    assert memory.database(host.home).read_bytes() == before
    sources.seed(host)
    args, preview = sources.selection(host)
    assert sources.retain(host, args, preview)["state"] == "accepted"
    assert acquisitions[-1][:2] == ("writable", "explicit_local_operator")
    assert memory.command(host, "source-status " + sources.query(preview))["status"] == "ok"
    assert acquisitions[-1][0] == "readonly"


def test_native_gates_precede_factory_acquisition(host, acquisitions):
    with model.turn(host):
        assert model.call(host)["error"]["code"] == "session_tools_not_activated"
    model.activate(host)
    with model.turn(host, platform="telegram"):
        assert model.call(host)["status"] == "error"
    with model.turn(host):
        for action in ("source_discover", "source_retain", "maintenance_prepare"):
            assert model.call(host, {"action": action}, write=True)["status"] == "error"
    from hermes_state_runtime import RuntimeStoreError

    host.connection.actor = replace(host.connection.actor, capabilities=frozenset({"session:read"}))
    with pytest.raises(RuntimeStoreError):
        memory.command(host, "list")
    assert acquisitions == []
    assert not memory.database(host.home).exists()


def test_native_maintenance_fence_precedes_both_factory_modes(host, acquisitions):
    recall.save(host)
    recall.enable(host)
    prepared = memory.command(host, "maintenance-prepare managed-fence --expected-watermark 1")
    assert prepared["status"] == "ok", prepared
    count = len(acquisitions)
    memory.assert_error(memory.command(host, "list"), "memory_maintenance_pending")
    with model.turn(host):
        assert recall.collect(host) == ""
        memory.assert_error(model.call(host), "memory_maintenance_pending")
    assert len(acquisitions) == count
    assert memory.command(host, "maintenance-commit managed-fence")["status"] == "ok"
    assert memory.command(host, "list")["status"] == "ok"


@pytest.mark.parametrize("failure", ["constructor", "open", "close"])
@pytest.mark.parametrize("readonly", [False, True])
def test_failed_native_lifetime_releases_connection_and_lock(host, monkeypatch, failure, readonly):
    storage = module(host, "memory_storage")
    local = module(host, "local_memory")
    errors = module(host, "memory_backend")
    coordination = module(host, "memory_coordination")
    recall.save(host)
    recall.enable(host)
    connections, closes = [], []
    connect = sqlite3.connect
    create = storage.create_backend
    original_close = local.LocalMemoryBackend.close

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs, factory=ObservedConnection)
        connections.append(connection)
        return connection

    def broken_constructor():
        raise errors.MemoryError("local_memory_unavailable")

    def broken_open(self, connection, **kwargs):
        connection.execute("BEGIN")
        raise errors.MemoryError("local_memory_unavailable")

    def tracked_close(self):
        closes.append(self)
        original_close(self)
        if failure == "close":
            raise RuntimeError("synthetic private close detail")

    with monkeypatch.context() as patch:
        patch.setattr(
            storage, "sqlite3", SimpleNamespace(connect=tracked_connect, Error=sqlite3.Error)
        )
        patch.setattr(local.LocalMemoryBackend, "close", tracked_close)
        if failure == "constructor":
            patch.setattr(storage, "create_backend", broken_constructor)
        elif failure == "open":
            patch.setattr(
                local.LocalMemoryBackend, "open_readonly" if readonly else "open", broken_open
            )
        if readonly:
            with model.turn(host):
                assert recall.collect(host) == ""
        else:
            result = memory.command(host, "list")
            memory.assert_error(
                result, "cleanup_failed" if failure == "close" else "local_memory_unavailable"
            )
            assert "synthetic private" not in str(result)
        assert len(connections) == 1
        assert len(closes) == (0 if failure == "constructor" else 1)
        assert connections[0].close_calls == 1
        # An exclusive lock cannot succeed if either shared opener leaked its fd.
        with coordination.memory_lock(host.home, exclusive=True, timeout=0):
            pass
    assert storage.create_backend is create
    assert memory.command(host, "list")["status"] == "ok"
    with model.turn(host):
        assert "oat milk" in recall.collect(host)


def test_readonly_missing_and_old_schema_do_not_create_or_migrate(host, acquisitions):
    recall.enable(host)
    with model.turn(host):
        assert recall.collect(host) == ""
    assert acquisitions == []
    assert not (host.home / "plugin-data").exists()
    recall.save(host)
    path = memory.database(host.home)
    with sqlite3.connect(path) as connection:
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        connection.execute(f"PRAGMA user_version={current - 1}")
    before = path.read_bytes()
    with model.turn(host):
        assert recall.collect(host) == ""
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == current - 1


def test_fresh_native_process_reopen_replays_exact_receipt_after_forget(tmp_path):
    home = tmp_path / "profile"
    install(home)
    memory.configure(home, memory_model_tools=True)
    (tmp_path / "bundled").mkdir()
    request = 'remember "synthetic managed coffee" --request-id managed-restart'
    first = process.restart(home, [{"command": request}])[0]
    assert first["status"] == "ok"
    rid = first["data"]["record_id"]
    second = process.restart(
        home,
        [
            {"command": request},
            {"activate": "enable-read"},
            process.tool("recall", queries=["coffee"]),
            {"command": f"forget {rid} --expected-revision 1 --request-id managed-forget"},
        ],
    )
    assert second[0]["replayed"] and second[0]["data"] == first["data"]
    assert second[2]["data"]["items"][0]["record_id"] == rid
    assert second[3]["status"] == "ok"
    third = process.restart(
        home,
        [
            {"command": request},
            {"activate": "status"},
            {"command": "list"},
            {"command": f"show {rid}"},
        ],
    )
    assert third[0]["replayed"] and third[0]["data"] == first["data"]
    assert third[1]["data"]["access"] == "disabled"
    assert third[2]["data"]["items"] == []
    assert third[3]["data"]["status"] == "forgotten"


def test_native_committed_write_close_failure_reconciles_in_fresh_process(host, monkeypatch):
    local = module(host, "local_memory")
    original_close = local.LocalMemoryBackend.close
    closes = []

    def failed_close(self):
        closes.append(self)
        original_close(self)
        raise RuntimeError("synthetic private cleanup detail")

    request = 'remember "synthetic durable cleanup" --request-id close-reconcile'
    with monkeypatch.context() as patch:
        patch.setattr(local.LocalMemoryBackend, "close", failed_close)
        result = memory.command(host, request)
    memory.assert_error(result, "cleanup_failed")
    assert result["error"]["retryable"] is False
    assert "synthetic private" not in str(result)
    assert len(closes) == 1
    # Cleanup failure is not rollback: reconcile the same durable key after an
    # actual process restart instead of generating a second mutation identity.
    results = process.restart(host.home, [{"command": request}, {"command": "list"}])
    assert results[0]["status"] == "ok" and results[0]["replayed"] is True
    assert len(results[1]["data"]["items"]) == 1
    assert results[1]["data"]["items"][0]["record_id"] == results[0]["data"]["record_id"]
