"""Fresh-process native dispatch with Chinese records and no live model provider.

Only synthetic private profiles are installed. Child processes receive an
allowlisted environment and their own socket guard, because pytest's in-process
autouse guard cannot protect a subprocess. This proves tool/store behavior, not
natural-language model selection or semantic recall.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import test_local_memory_commands as memory
from test_local_task_cli import PLUGIN_ID, PLUGIN_ROOT, install


def _child_main():
    import io
    import socket
    from contextlib import redirect_stdout

    def deny_network(*_args, **_kwargs):
        raise AssertionError("Restart contracts must not connect to the network")

    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network

    # Keep host loader output separate from the JSON contract result. No runtime
    # listener, provider, model agent or authentication flow is constructed.
    with redirect_stdout(io.StringIO()):
        import test_local_conversation_tasks as local
        import test_session_memory_tools as session
        from hermes_cli.plugins import get_plugin_manager

        def load(manager):
            manager.discover_and_load()
            plugin = manager._plugins[PLUGIN_ID]
            assert plugin.enabled and plugin.error is None
            assert "personal_memory_read" in plugin.tools_registered
            assert "personal_memory_write" in plugin.tools_registered

        local.load = load
        manager = get_plugin_manager()
        try:
            host = local.make_host(Path(os.environ["HERMES_HOME"]), manager)
            results = []
            for step in json.load(sys.stdin):
                if "activate" in step:
                    result = session.activate(host, step["activate"])
                else:
                    with session.turn(host):
                        result = session.call(host, step["tool"], write=step.get("write", False))
                results.append(result)
        finally:
            manager.unload()
    print(json.dumps(results, ensure_ascii=False))


def restart(home, steps):
    import hermes_cli

    # Do not inherit provider credentials, a real HOME, plugin discovery paths,
    # proxy configuration or process-session activation from the test runner.
    env = {
        "PATH": os.defpath,
        "HOME": str(home.parent / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(home.parent / "runtime"),
        "HERMES_BUNDLED_PLUGINS": str(home.parent / "bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": os.pathsep.join(
            (str(Path(hermes_cli.__file__).resolve().parents[1]), str(Path(__file__).parent))
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from test_memory_process_restart import _child_main; _child_main()",
        ],
        input=json.dumps(steps, ensure_ascii=False),
        cwd=PLUGIN_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout)


def tool(action, *, write=False, **arguments):
    return {"tool": {"action": action, **arguments}, "write": write}


def assert_disabled(results):
    assert results[0]["data"]["access"] == "disabled"
    assert results[1]["error"]["code"] == "session_tools_not_activated"


def test_chinese_correction_and_terminal_forget_survive_fresh_processes(tmp_path):
    home = tmp_path / "profile"
    install(home)
    memory.configure(home, memory_model_tools=True)
    (tmp_path / "bundled").mkdir()
    original_config = (home / "config.yaml").read_bytes()
    original = "饮食偏好：早餐喜欢豆浆，不喝咖啡。"
    corrected = "饮食偏好：早餐改喝燕麦奶，不喝豆浆。"
    remember = tool("remember", write=True, content=original, topic="早餐", request_id="zh-save")
    initial = restart(home, [{"activate": "enable-write"}, remember])
    assert initial[1]["status"] == "ok", initial
    saved_receipt = initial[1]["data"]
    rid = saved_receipt["record_id"]
    correction = tool(
        "correct",
        write=True,
        record_id=rid,
        expected_revision=1,
        content=corrected,
        topic="饮食",
        request_id="zh-edit",
    )
    prefix = [{"activate": "status"}, tool("list"), {"activate": "enable-read"}]
    edited = restart(
        home,
        [
            *prefix,
            tool("search", query="豆浆"),
            tool("search", query="早餐"),
            correction,
            {"activate": "enable-write"},
            correction,
            tool("search", query="咖啡"),
            tool("search", query="燕麦奶"),
            tool("show", record_id=rid),
        ],
    )
    assert_disabled(edited)
    assert edited[3]["data"]["items"][0]["content"] == original
    assert edited[4]["data"]["items"][0]["record_id"] == rid
    assert edited[5]["error"]["code"] == "session_write_not_activated"
    corrected_receipt = edited[7]["data"]
    assert corrected_receipt["revision"] == 2
    assert edited[8]["data"]["items"] == []
    row = edited[9]["data"]["items"][0]
    assert row == edited[10]["data"]
    assert (row["content"], row["topic"], row["source"]) == (
        corrected,
        "饮食",
        "activated_session_model",
    )
    forget = tool("forget", write=True, record_id=rid, expected_revision=2, request_id="zh-forget")
    forgotten = restart(
        home,
        [
            *prefix,
            tool("show", record_id=rid),
            {"activate": "enable-write"},
            tool("forget", write=True, record_id=rid, expected_revision=1, request_id="stale"),
            forget,
            tool("show", record_id=rid),
        ],
    )
    assert_disabled(forgotten)
    assert forgotten[3]["data"] == row
    assert forgotten[5]["error"]["code"] == "revision_conflict"
    forgotten_receipt = forgotten[6]["data"]
    assert forgotten_receipt["revision"] == 3
    assert forgotten_receipt["status"] == "forgotten"
    tombstone = forgotten[7]["data"]
    assert all(tombstone[k] is None for k in ("content", "topic", "source", "session_ref"))
    final = restart(
        home,
        [
            *prefix,
            tool("list"),
            tool("search", query="燕麦奶"),
            tool("search", query="饮食"),
            tool("show", record_id=rid),
            {"activate": "enable-write"},
            remember,
            correction,
            forget,
            tool(
                "correct",
                write=True,
                record_id=rid,
                expected_revision=3,
                content=original,
                request_id="no-resurrection",
            ),
            tool("list"),
        ],
    )
    assert_disabled(final)
    for result in final[3:6] + final[-1:]:
        assert result["data"]["items"] == []
    assert final[6]["data"] == tombstone
    for result, receipt in zip(
        final[8:11], (saved_receipt, corrected_receipt, forgotten_receipt), strict=True
    ):
        assert result["replayed"] and result["data"] == receipt
    assert final[11]["error"]["code"] == "record_forgotten"
    serialized = json.dumps(final, ensure_ascii=False)
    for text in (original, corrected, "早餐", "饮食"):
        assert text not in serialized
    assert (home / "config.yaml").read_bytes() == original_config
    assert not (home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3").exists()


def test_bounded_recall_after_restart_correction_and_forget(tmp_path):
    home = tmp_path / "profile"
    install(home)
    memory.configure(home, memory_model_tools=True)
    (tmp_path / "bundled").mkdir()
    original_config = (home / "config.yaml").read_bytes()
    query = tool("recall", queries=["早餐", "燕麦奶"], limit=2, max_chars=2000)
    saved = restart(
        home,
        [
            {"activate": "enable-write"},
            tool("remember", write=True, content="早餐豆浆", topic="饮食", request_id="r"),
            query,
        ],
    )
    rid = saved[1]["data"]["record_id"]
    assert saved[2]["data"]["items"][0]["record_id"] == rid
    current = restart(
        home,
        [
            query,
            {"activate": "enable-read"},
            query,
            {"activate": "enable-write"},
            tool(
                "correct",
                write=True,
                record_id=rid,
                expected_revision=1,
                content="早餐燕麦奶",
                request_id="c",
            ),
            query,
        ],
    )
    assert current[0]["error"]["code"] == "session_tools_not_activated"
    assert current[2]["data"] == saved[2]["data"]
    assert current[5]["data"]["items"][0]["content"] == "早餐燕麦奶"
    assert current[5]["data"]["items"][0]["revision"] == 2
    assert current[5]["data"]["items"][0]["matched_queries"] == [0, 1]
    assert current[5]["data"]["items_json_chars"] <= 2000
    forgotten = restart(
        home,
        [
            {"activate": "enable-write"},
            query,
            tool("forget", write=True, record_id=rid, expected_revision=2, request_id="f"),
            query,
        ],
    )
    assert forgotten[1]["data"] == current[5]["data"]
    assert forgotten[3]["data"]["items"] == []
    final = restart(home, [{"activate": "enable-read"}, query])
    assert final[1]["data"]["items"] == []
    assert final[1]["data"]["watermark"] == 3
    assert (home / "config.yaml").read_bytes() == original_config
