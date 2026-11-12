"""Fresh-process, metadata-only origin preservation across canonical repack."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from acceptance.memory import retained

CHILD = r"""
import json,socket,sys
from pathlib import Path
from unittest.mock import patch
from personal_agent import memory_storage
from personal_agent.memory_backend import MemoryService

def deny(*a,**k):
    raise AssertionError('Native source and network unavailable')
socket.create_connection = socket.socket.connect = socket.socket.connect_ex = deny
home=Path(sys.argv[1])
with patch.object(memory_storage,'current_profile_home',lambda:home):
    with memory_storage.open_existing_memory_reader(home,'origin-restart') as backend:
        service=MemoryService(backend)
        results=[]
        for rid in json.loads(sys.argv[2]):
            result=service.execute('record_origin',{'record_id':rid})['data']
            result.pop('evaluated_at')
            results.append(result)
        print(json.dumps(results))
"""


def inspect_process(home, records):
    run = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(home), json.dumps(records)],
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
    return json.loads(run.stdout)


@pytest.mark.parametrize("interrupted", [False, True])
def test_origins_survive_normal_and_interrupted_repack(tmp_path, interrupted):
    home = tmp_path / "home"
    expected = retained._prepare(home)
    records = [
        s["decision"]["record"]["record_id"]
        for s in expected["statuses"]
        if s["decision"]["state"] == "accepted"
    ]
    first = inspect_process(home, records)
    assert {item["origin"]["kind"] for item in first} == {
        "retained_native_snapshot",
        "observed_native_snapshot",
    }
    assert all(item["origin"]["suppressed"] for item in first)
    watermark = retained._maintain(home, "preview")["watermark"]
    retained._maintain(home, "prepare", name="retained", expected_watermark=watermark)
    if interrupted:
        assert retained._process(home, "interrupt").returncode == 73
        assert retained._maintain(home, "recover", name="retained")["phase"] == "completed"
    else:
        assert retained._maintain(home, "commit", name="retained")["phase"] == "completed"
    assert inspect_process(home, records) == first
    retained._verify(home, expected)
    assert inspect_process(home, records) == first
