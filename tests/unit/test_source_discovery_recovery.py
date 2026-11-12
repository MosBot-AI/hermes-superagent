"""Fresh-process discovery and repack preservation, without known request identities."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from test_retained_source_recovery import opened, request

from acceptance.memory import retained
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_storage import open_existing_memory_reader

CHILD = r"""
import json,socket,sys
from pathlib import Path
from unittest.mock import patch
from personal_agent import memory_storage
from personal_agent.memory_backend import MemoryService

def deny(*args,**kwargs):
    raise AssertionError('No network in synthetic recovery')
socket.create_connection = socket.socket.connect = socket.socket.connect_ex = deny
home=Path(sys.argv[1])
with patch.object(memory_storage,'current_profile_home',lambda:home):
    with memory_storage.open_existing_memory_reader(home,'fresh-recovery') as backend:
        page=MemoryService(backend).execute('source_discover',{'state':'all','limit':1})['data']
        items=list(page['items'])
        while page['next_offset'] is not None:
            page=MemoryService(backend).execute('source_discover',{
                'state':'all','limit':1,'offset':page['next_offset'],
                'expected_snapshot':page['snapshot']})['data']
            items.extend(page['items'])
        print(json.dumps({'items':items,'snapshot':page['snapshot']}))
"""


def discover_process(home):
    process = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(home)],
        env={
            "PATH": os.defpath,
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(process.stdout)


@pytest.mark.parametrize("interrupted", [False, True])
def test_fresh_process_discovery_before_after_repack_and_explicit_discard(tmp_path, interrupted):
    home = tmp_path / "home"
    expected = retained._prepare(home)
    first = discover_process(home)
    assert len(first["items"]) == 8
    assert {item["state"] for item in first["items"]} == {"pending", "accepted", "discarded"}
    assert {item["query"]["request_id"] for item in first["items"]} == {
        row[0] for row in expected["rows"]
    }
    watermark = retained._maintain(home, "preview")["watermark"]
    retained._maintain(home, "prepare", name="retained", expected_watermark=watermark)
    if interrupted:
        assert retained._process(home, "interrupt").returncode == 73
        assert retained._maintain(home, "recover", name="retained")["phase"] == "completed"
    else:
        assert retained._maintain(home, "commit", name="retained")["phase"] == "completed"
    assert discover_process(home) == first
    with retained._opened(home) as (sdk, _):
        for item in first["items"]:
            status = sdk.execute("source_status", item["query"])["data"]
            assert status["decision"]["state"] == item["state"]
            if item["state"] == "pending":
                assert sdk.execute("source_discard", item["query"])["data"]["state"] == "discarded"
                original = next(
                    p
                    for p in retained._requests()
                    if p["request_id"] == item["query"]["request_id"]
                )
                fresh = {
                    **original,
                    "request_id": "reentry-" + original["request_id"],
                    "consumer_id": "another-" + original["consumer_id"],
                    "expected_sequence": 0,
                    "source": {**original["source"], "identity": "f" * 64},
                }
                with pytest.raises(MemoryError, match="source_suppressed"):
                    sdk.execute("source_stage", fresh)
    after = discover_process(home)
    assert all(item["state"] != "pending" for item in after["items"])


@pytest.mark.parametrize("version", [11, 12])
def test_readonly_older_schema_refusal_never_migrates(tmp_path, version):
    path = tmp_path / "synthetic.sqlite"
    with opened(path) as (sdk, _, connection):
        sdk.execute("source_stage", request())
        if version == 12:
            retained._legacy_layout(connection)
        else:
            connection.execute("DROP TABLE retained_source_decisions")
            connection.execute("PRAGMA user_version=11")
    before = path.read_bytes()
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        with opened(path, readonly=True):
            pytest.fail("old schema was admitted")
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (version,)


def test_missing_store_reader_does_not_create(tmp_path):
    with patch("personal_agent.memory_storage.current_profile_home", lambda: tmp_path):
        with pytest.raises(MemoryError, match="memory_store_missing"):
            with open_existing_memory_reader(tmp_path, "session"):
                pytest.fail("missing storage admitted")
    assert not list(tmp_path.iterdir())
