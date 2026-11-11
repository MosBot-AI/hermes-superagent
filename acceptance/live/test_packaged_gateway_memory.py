"""Manual-only installed memory lifecycle, synthetic data and no model turns.

Pending recovery uses an explicitly labeled installed-SDK fixture while stopped,
not a simulated Gateway crash or evidence of cross-store atomicity.
"""

# ruff: noqa: F811
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing, contextmanager

import pytest
from test_packaged_gateway_tasks import checked, installed  # noqa: F401


def enable_installed_memory(home):
    """Preserve the installer's YAML fields while enabling this test's opt-in."""
    from ruamel.yaml import YAML

    path = home / "config.yaml"
    yaml = YAML()
    config = yaml.load(path)
    config["plugins"]["entries"]["hermes-personal-agent"]["settings"]["local_memory"] = True
    yaml.dump(config, path)


@pytest.fixture
def installed_memory(installed):
    home, env, live = installed
    enable_installed_memory(home)
    return home, env, live


async def command(live, ws, sid, text, error=None):
    result = await live.ok(
        ws, "slash.exec", session_id=sid, command="personal-memory --json " + text
    )
    assert result["type"] == "exec", result
    payload = json.loads(result["output"])
    if error:
        assert payload["status"] == "error", payload
        assert payload["error"]["code"] == error, payload
    else:
        assert payload["status"] == "ok", payload
        return payload["data"]


class Gateway:
    """Every phase starts a new real process and stops it normally."""

    def __init__(self, installed):
        self.home, self.env, self.live = installed
        self.instances = set()
        self.pids = set()

    @contextmanager
    def start(self):
        with self.live.daemon(self.home, self.env, f"memory-{len(self.instances)}.log") as (
            proc,
            desc,
            _,
        ):
            assert proc.pid not in self.pids
            assert desc["instance_id"] not in self.instances
            self.pids.add(proc.pid)
            self.instances.add(desc["instance_id"])
            yield desc
            assert self.live.planned_stop(self.home, proc, desc) == 0
        assert self.live.control_absent(self.home)
        assert not self.live.port_open(self.live.api_port(desc))

    def create(self):
        async def run(desc):
            async with self.live.websocket(self.home, desc) as ws:
                result = await self.live.ok(
                    ws,
                    "session.create",
                    request_id="memory-session",
                    source="cli",
                    cwd=str(self.home),
                    toolsets=[],
                )
                sid = result["session_id"]
                await self.live.ok(ws, "session.resume", session_id=sid)
                return sid

        with self.start() as desc:
            return asyncio.run(run(desc))

    def phase(self, sid, callback):
        async def run(desc):
            async with self.live.websocket(self.home, desc) as ws:
                resumed = await self.live.ok(ws, "session.resume", session_id=sid)
                assert resumed["session_id"] == sid

                async def call(text, error=None):
                    return await command(self.live, ws, sid, text, error)

                return await callback(call)

        with self.start() as desc:
            return asyncio.run(run(desc))

    def seed(self, sid, rows=(), *, clear=False):
        # Public host API only; called after full stop, never SQL mutation.
        from hermes_state import SessionDB

        assert self.live.control_absent(self.home)
        with SessionDB(self.home / "state.db") as db:
            if clear:
                db.clear_messages(sid)
                assert db.get_messages(sid) == []
            for role, content in rows:
                db.append_message(sid, role, content)
            return db.get_messages(sid)


def query(preview):
    q = preview["query"]
    return f"{q['request_id']} --expected-digest {q['expected_digest']}"


async def preview(call, index, key, *, expiry=False):
    listing = await call("source-list")
    item = listing["items"][index]
    uid = item["message_uid"]
    shown = await call(f"source-show {uid} --expected-snapshot {listing['snapshot']}")
    args = (
        f"{uid} --expected-snapshot {listing['snapshot']} --consumer-id {key} "
        f"--expected-sequence 0 --request-id {key} --retention independent_snapshot "
        + ("--expires-at 2000-01-01T00:00:00Z" if expiry else "--keep")
        + " --topic synthetic-private-topic"
    )
    result = await call("source-preview " + args)
    payload = result["payload"]
    assert payload["content"] == shown["item"]["content"]
    assert payload["source"]["role"] == item["role"]
    assert payload["source"]["kind"] == "observed_native_snapshot"
    assert "receipt_id" not in payload["source"]
    assert (
        payload["source"]["fingerprint"] == hashlib.sha256(payload["content"].encode()).hexdigest()
    )
    assert result["canonical_admission"] is False
    return args, result


def oracle(home, *, records, events, decisions, forgotten=0, removed=()):
    canonical = home / "plugin-data/hermes-personal-agent/memory/records.sqlite3"
    for path in (home / "state.db", canonical):
        assert path.is_file()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    with closing(sqlite3.connect(canonical.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("SELECT count(*) FROM records").fetchone() == (records,)
        assert db.execute("SELECT count(*) FROM events").fetchone() == (events,)
        assert db.execute("SELECT count(*) FROM receipts").fetchone() == (events,)
        assert db.execute("SELECT count(*) FROM retained_source_decisions").fetchone() == (
            decisions,
        )
        assert db.execute(
            "SELECT count(*) FROM records WHERE status='forgotten' AND content IS NULL "
            "AND topic IS NULL AND session_ref IS NULL"
        ).fetchone() == (forgotten,)
        # Logical live database payload oracle, not a physical-media erasure claim.
        dump = "\n".join(db.iterdump())
        for content in removed:
            assert content not in dump


def test_retained_memory_survives_native_text_loss_and_suppresses_fresh_sources(installed_memory):
    gateway = Gateway(installed_memory)
    sid = gateway.create()
    rows = (
        ("user", "Synthetic original user memory 中文"),
        ("assistant", "Synthetic original assistant memory 中文"),
    )
    originals = gateway.seed(sid, rows)

    async def retain(call):
        accepted = []
        for index in range(2):
            args, p = await preview(call, index, f"accepted-{index}", expiry=index == 1)
            if index == 0:
                await call("source-status " + query(p), error="memory_store_missing")
                await call(
                    f"source-retain {args} --expected-digest " + "0" * 64,
                    error="source_preview_changed",
                )
                assert not (gateway.home / "plugin-data/hermes-personal-agent/memory").exists()
            raw = f"source-retain {args} --expected-digest {p['query']['expected_digest']}"
            decision = await call(raw)
            assert decision["state"] == "accepted"
            assert decision["source"] == p["payload"]["source"]
            assert await call(raw) == decision
            assert (await call(f"source-cursor --consumer-id accepted-{index}"))[
                "through_sequence"
            ] == 1
            accepted.append((p, decision))
        visible = (await call("list"))["items"]
        assert len(visible) == 1
        all_records = (await call("list --include-expired"))["items"]
        assert len(all_records) == 2
        assert sum(r["expired"] for r in all_records) == 1
        return accepted

    accepted = gateway.phase(sid, retain)
    oracle(gateway.home, records=2, events=2, decisions=2)
    gateway.seed(sid, clear=True)

    async def mutate(call):
        assert (await call("source-list"))["eligible_count"] == 0
        for index, (p, decision) in enumerate(accepted):
            status = await call("source-status " + query(p))
            assert status["decision"] == decision
            assert status["current"]["revision"] == 1
            rid = decision["record"]["record_id"]
            assert (await call("show " + rid))["content"] == rows[index][1]
            op = "correct" if index == 0 else "forget"
            extra = ' --text "Synthetic corrected memory"' if index == 0 else ""
            await call(f"{op} {rid} --expected-revision 1 --request-id mutation-{index}{extra}")

    gateway.phase(sid, mutate)
    fresh = gateway.seed(sid, rows)
    assert {r["message_uid"] for r in fresh}.isdisjoint(r["message_uid"] for r in originals)

    async def reconcile(call):
        for index, (p, decision) in enumerate(accepted):
            status = await call("source-status " + query(p))
            assert status["decision"] == decision  # historical acceptance, not restoration
            assert status["current"]["revision"] == 2
            record = await call("show " + decision["record"]["record_id"])
            assert record["revision"] == 2
            if index == 0:
                assert record["content"] == "Synthetic corrected memory"
            else:
                assert record["status"] == "forgotten"
                assert record["content"] is None and record["topic"] is None
            assert status["current"]["status"] == ("active" if index == 0 else "forgotten")
            encoded = json.dumps(status)
            assert rows[index][1] not in encoded and "synthetic-private-topic" not in encoded
            assert sid not in encoded
            assert (await call(f"source-cursor --consumer-id accepted-{index}"))[
                "through_sequence"
            ] == 1
            args, new = await preview(call, index, f"fresh-{index}")
            assert new["payload"]["source"]["identity"] != p["payload"]["source"]["identity"]
            await call(
                f"source-retain {args} --expected-digest {new['query']['expected_digest']}",
                error="source_suppressed",
            )

    gateway.phase(sid, reconcile)
    oracle(
        gateway.home, records=2, events=4, decisions=2, forgotten=1, removed=[r[1] for r in rows]
    )


# Isolated subprocess imports only the host and the officially installed package.
# The fixture stages through the production SDK, without patching any method.
STAGE_INSTALLED = r"""
import importlib, json, os, sys
from pathlib import Path
host, sid, saved, output, source = sys.argv[1:]
sys.path.insert(0, host)
from hermes_cli.plugins import get_plugin_manager
manager = get_plugin_manager()
manager.discover_and_load()
loaded = manager._plugins["hermes-personal-agent"]
assert loaded.enabled and loaded.error is None, loaded.error
plugin = Path(loaded.module.__file__).resolve().parent
home = Path(os.environ["HERMES_HOME"])
assert plugin.is_relative_to(home)
assert json.loads((plugin / "PROVENANCE.json").read_text())["source_commit"] == source
prefix = loaded.module.__name__ + ".personal_agent"
sdk_module = importlib.import_module(prefix + ".memory_sdk")
storage = importlib.import_module(prefix + ".memory_storage")
for module in (sdk_module, storage):
    assert Path(module.__file__).resolve().is_relative_to(plugin)
assert "personal_agent" not in sys.modules
payload = json.loads(Path(saved).read_text())["payload"]
with storage.open_memory_backend(home, sid) as backend:
    namespace = backend.execute("export", {"limit": 1})["namespace_id"]
    sdk = sdk_module.LocalMemorySDK(backend, sdk_module.LocalBinding(namespace, sid))
    result = sdk.execute("source_stage", payload)
Path(output).write_text(json.dumps(result))
"""


def test_installed_sdk_pending_fixture_recovers_by_gateway_discard(installed_memory, tmp_path):
    gateway = Gateway(installed_memory)
    sid = gateway.create()
    content = "Synthetic pending source lost before acceptance 中文"
    original = gateway.seed(sid, (("user", content),))

    async def review(call):
        return await preview(call, 0, "pending")

    _, saved = gateway.phase(sid, review)
    input_path, output_path = tmp_path / "preview.json", tmp_path / "staged.json"
    input_path.write_text(json.dumps(saved))
    checked(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            STAGE_INSTALLED,
            os.environ["HERMES_TEST_ROOT"],
            sid,
            str(input_path),
            str(output_path),
            os.environ["HERMES_SOURCE_COMMIT"],
        ],
        cwd=tmp_path,
        env=gateway.env,
    )
    staged = json.loads(output_path.read_text())
    assert staged["data"]["state"] == "pending"
    oracle(gateway.home, records=0, events=0, decisions=1, removed=[content])
    gateway.seed(sid, clear=True)

    async def discard(call):
        assert (await call("source-list"))["eligible_count"] == 0
        status = await call("source-status " + query(saved))
        assert status["decision"] == staged["data"]
        assert content not in json.dumps(status)
        assert (await call("source-cursor --consumer-id pending"))["through_sequence"] == 0
        await call(
            "source-discard pending --expected-digest " + "0" * 64, error="idempotency_conflict"
        )
        assert (await call("source-cursor --consumer-id pending"))["through_sequence"] == 0
        decision = await call("source-discard " + query(saved))
        assert decision["state"] == "discarded"
        assert await call("source-discard " + query(saved)) == decision
        assert (await call("source-cursor --consumer-id pending"))["through_sequence"] == 1
        assert (await call("list"))["items"] == []
        return decision

    discarded = gateway.phase(sid, discard)
    fresh = gateway.seed(sid, (("assistant", content),))
    assert fresh[0]["message_uid"] != original[0]["message_uid"]

    async def suppressed(call):
        assert (await call("source-status " + query(saved)))["decision"] == discarded
        assert (await call("source-cursor --consumer-id pending"))["through_sequence"] == 1
        args, p = await preview(call, 0, "pending-fresh")
        await call(
            f"source-retain {args} --expected-digest {p['query']['expected_digest']}",
            error="source_suppressed",
        )
        assert (await call("list"))["items"] == []

    gateway.phase(sid, suppressed)
    oracle(gateway.home, records=0, events=0, decisions=1, removed=[content])
