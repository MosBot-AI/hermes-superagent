"""Pinned builtin stores and real prompt assembly, with synthetic homes only."""

import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def memory_home(tmp_path, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    token = set_hermes_home_override(home)
    try:
        yield home
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize(
    "target,filename,default", [("memory", "MEMORY.md", 2200), ("user", "USER.md", 1375)]
)
@pytest.mark.parametrize("configured", [False, True])
def test_builtin_caps_boundary_and_overflow_preserve_disk(
    memory_home, target, filename, default, configured
):
    from tools.memory_tool import load_on_disk_store

    limit = 80 if configured else default
    config = {"memory": {"memory_char_limit": 80, "user_char_limit": 80}} if configured else {}
    (memory_home / "config.yaml").write_text(json.dumps(config))
    store = load_on_disk_store()
    assert getattr(store, f"{target}_char_limit") == limit
    content = "茶" * limit  # The cap counts characters, not UTF-8 bytes.
    assert store.add(target, content)["success"]
    path = memory_home / "memories" / filename
    before = path.read_bytes()
    assert content in path.read_text()
    assert not store.add(target, "extra")["success"]
    assert path.read_bytes() == before
    assert not store.replace(target, content, content + "茶")["success"]
    assert path.read_bytes() == before
    reopened = load_on_disk_store()
    assert getattr(reopened, f"{target}_entries") == [content]


@pytest.mark.parametrize("via_compression", [False, True])
def test_actual_prompt_invalidation_reloads_external_store(
    memory_home, monkeypatch, via_compression
):
    from agent.system_prompt import build_system_prompt, invalidate_system_prompt
    from tools.memory_tool import load_on_disk_store

    writer = load_on_disk_store()
    assert writer.add("memory", "Synthetic memory before change")["success"]
    assert writer.add("user", "Synthetic user before change")["success"]
    reader = load_on_disk_store()
    # Minimal inert agent state: assembly and invalidation are the actual host
    # functions; no constructor/model client, replacement renderer, or mock store.
    agent = SimpleNamespace(
        load_soul_identity=False,
        skip_context_files=True,
        valid_tool_names=[],
        _task_completion_guidance=False,
        _tool_use_enforcement=False,
        _environment_probe=False,
        _kanban_worker_guidance="",
        _memory_store=reader,
        _memory_enabled=True,
        _user_profile_enabled=True,
        _memory_manager=None,
        model="",
        provider="",
        platform="",
        pass_session_id=False,
        session_id="synthetic",
        _emit_status=lambda *_a, **_k: None,
        _cached_system_prompt=None,
        _cached_system_prompt_static=None,
    )
    original = build_system_prompt(agent)
    assert "Synthetic memory before change" in original
    assert "Synthetic user before change" in original
    agent._cached_system_prompt = original
    agent._cached_system_prompt_static = "synthetic cached prefix"
    for target in ("memory", "user"):
        assert writer.replace(
            target, f"Synthetic {target} before change", f"Synthetic {target} after change"
        )["success"]
    frozen = build_system_prompt(agent)
    assert "Synthetic memory before change" in frozen
    assert "Synthetic memory after change" not in frozen
    if via_compression:
        refreshed = compress_with_synthetic_summary(agent, monkeypatch)
        assert agent._cached_system_prompt == refreshed
    else:
        invalidate_system_prompt(agent)
        assert agent._cached_system_prompt is None and agent._cached_system_prompt_static is None
        refreshed = build_system_prompt(agent)
    for target in ("memory", "user"):
        assert f"Synthetic {target} after change" in refreshed
        assert f"Synthetic {target} before change" not in refreshed


def compress_with_synthetic_summary(agent, monkeypatch):
    """Real compression orchestration and prompt boundary, synthetic summary only.

    No model, durable session, lease contention, or tool discovery is exercised.
    The compression callsite, candidate admission, prompt invalidation/rebuild,
    and builtin stores remain real; replacing that callsite with a no-op fails
    the caller's refreshed-content assertions.
    """
    from types import MethodType

    from agent import conversation_compression as compression
    from agent.system_prompt import build_system_prompt, invalidate_system_prompt

    agent._invalidate_system_prompt = MethodType(invalidate_system_prompt, agent)
    agent._build_system_prompt = MethodType(build_system_prompt, agent)
    agent.context_compressor = SimpleNamespace(
        compression_count=1, _last_compression_made_progress=True
    )
    agent._session_db = None
    agent._todo_store = SimpleNamespace(format_for_injection=lambda: "")
    agent.tools = []
    agent.log_prefix = ""
    messages = [{"role": "user", "content": "Synthetic conversation before compression. " * 30}]
    summary = [{"role": "user", "content": "[CONTEXT SUMMARY]: Synthetic summary"}]
    # Skip only external/model-facing preparation and telemetry. Keep the actual
    # compress_context -> _rebuild_system_prompt_at_boundary path untouched.
    for name in (
        "_refresh_main_credential",
        "lazy_compression_feasibility_check",
        "_refresh_agent_tool_definitions",
        "_emit_compression_attempt_telemetry",
        "_record_committed_attempt_effect",
    ):
        monkeypatch.setattr(compression, name, lambda *_a, **_k: None)
    monkeypatch.setattr(
        compression, "_announce_compression_start", lambda *_a, **_k: SimpleNamespace()
    )
    lease = SimpleNamespace(finish_lock_setup=lambda: None, release=lambda: None)
    monkeypatch.setattr(compression, "_acquire_compression_lease", lambda *_a, **_k: (lease, None))
    monkeypatch.setattr(compression, "_adopt_if_parent_rotated", lambda *_a, **_k: None)
    monkeypatch.setattr(
        compression,
        "_run_summary_phase",
        lambda *_a, **_k: compression._SummaryPhase(
            messages=messages,
            compressed=summary,
            messages_before_compression=list(messages),
            approx_tokens=500,
            pre_msg_count=1,
        ),
    )
    compressed, prompt = compression.compress_context(
        agent, messages, "", force=True, approx_tokens=500
    )
    assert compressed is summary
    assert agent.context_compressor.awaiting_real_usage_after_compression is True
    return prompt
