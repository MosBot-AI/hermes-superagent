"""Real native memory discovery/admission using only temporary synthetic packages.

Entry-point enumeration is injected, not package installation. Directory imports,
config reads, availability probes and skill registration use the pinned host.
"""

import json
import sys
from importlib.metadata import EntryPoint

import pytest
from plugins import memory
from test_native_memory_provider import scoped


@pytest.fixture
def admission(tmp_path, monkeypatch):
    from hermes_cli.plugins import get_plugin_manager

    home = tmp_path / "profile"
    roots = [tmp_path / "bundled", home / "plugins", tmp_path / ".hermes/plugins"]
    for root in roots:
        root.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "1")
    monkeypatch.delenv("HERMES_PLUGIN_HOST_PROCESS", raising=False)
    monkeypatch.setattr(memory, "_MEMORY_PLUGINS_DIR", roots[0])
    monkeypatch.setattr(memory, "_iter_entry_points", lambda: [])
    monkeypatch.chdir(tmp_path)
    before = set(sys.modules)
    with scoped(home):
        (home / "config.yaml").write_text(json.dumps({"memory": {"provider": "selected"}}))
        try:
            yield home, roots
        finally:
            get_plugin_manager().unload()
            memory._REGISTERED_MEMORY_PROVIDER_SKILLS.pop(str(home.resolve()), None)
    for name in set(sys.modules) - before:
        if name.startswith(("_hermes_user_memory.", "plugins.memory.contract_", "contract_ep")):
            sys.modules.pop(name, None)


def provider(root, name, label, *, available=True, prefix=""):
    path = root / name
    path.mkdir()
    (path / "skill.md").write_text("# Synthetic skill\nTemporary fixture only.\n")
    (path / "plugin.yaml").write_text(f"name: {name}\ndescription: {label}\n")
    (path / "__init__.py").write_text(
        prefix
        + f"""from pathlib import Path
from agent.memory_provider import MemoryProvider
Path(__file__).with_name("imported").touch()
class Provider(MemoryProvider):
    name = {name!r}
    def is_available(self):
        Path(__file__).with_name("probed").touch()
        return {available!r}
    def initialize(self, session_id, **kwargs): pass
    def get_tool_schemas(self): return []
    def system_prompt_block(self): return {label!r}
def register(ctx):
    ctx.register_memory_provider(Provider())
    ctx.register_skill("synthetic", str(Path(__file__).with_name("skill.md")))
"""
    )
    return path


def entry(monkeypatch, tmp_path, name="contract_ep"):
    # A module (not a package) exercises the actual entry-point load route.
    path = tmp_path / "contract_ep.py"
    path.write_text(
        "from agent.memory_provider import MemoryProvider\n"
        "class Provider(MemoryProvider):\n"
        f"    name = {name!r}\n"
        "    def is_available(self): return True\n"
        "    def initialize(self, session_id, **kwargs): pass\n"
        "    def get_tool_schemas(self): return []\n"
        '    def system_prompt_block(self): return "entry"\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    ep = EntryPoint(name=name, value="contract_ep:Provider", group=memory.ENTRY_POINTS_GROUP)
    monkeypatch.setattr(memory, "_iter_entry_points", lambda: [ep])


def test_metadata_listing_never_imports_but_availability_discovery_does(admission):
    _, roots = admission
    path = provider(roots[1], "contract_probe", "Synthetic unavailable", available=False)
    assert memory.list_memory_provider_names() == ["contract_probe"]
    assert not (path / "imported").exists()
    assert not (path / "probed").exists()
    assert memory.discover_memory_providers() == [
        ("contract_probe", "Synthetic unavailable", False)
    ]
    assert (path / "imported").exists() and (path / "probed").exists()


@pytest.mark.parametrize("source", [0, 1, 2, 3])
def test_directory_precedence_then_entry_point(admission, tmp_path, monkeypatch, source):
    _, roots = admission
    entry(monkeypatch, tmp_path, "contract_collision")
    paths = [
        provider(root, "contract_collision", str(i)) for i, root in enumerate(roots) if i >= source
    ]
    assert memory.list_memory_provider_names() == ["contract_collision"]
    loaded = memory.load_memory_provider("contract_collision", register_skills=False)
    assert loaded.system_prompt_block() == (str(source) if source < 3 else "entry")
    for path in paths[1:]:
        assert not (path / "imported").exists()
    if source < 3:
        assert "contract_ep" not in sys.modules


def test_inspecting_inactive_provider_never_selects_it_or_registers_its_skill(admission):
    from hermes_cli.plugins import get_plugin_manager

    home, roots = admission
    provider(roots[1], "contract_inactive", "inactive")
    before = (home / "config.yaml").read_bytes()
    assert memory.load_memory_provider("contract_inactive") is not None
    assert get_plugin_manager().find_plugin_skill("contract_inactive:synthetic") is None
    assert memory._get_active_memory_provider() == "selected"
    assert (home / "config.yaml").read_bytes() == before
    assert memory.discover_memory_providers() == [("contract_inactive", "inactive", True)]
    assert get_plugin_manager().find_plugin_skill("contract_inactive:synthetic") is None
    # Explicit skill admission is separate from selecting/changing memory.provider.
    assert memory.load_memory_provider("contract_inactive", register_skills=True) is not None
    assert get_plugin_manager().find_plugin_skill("contract_inactive:synthetic") is not None
    assert (home / "config.yaml").read_bytes() == before


@pytest.mark.parametrize(
    "failure",
    [
        "import contract_missing_dependency_7349\n",
        "raise RuntimeError('synthetic import failure')\n",
    ],
)
def test_load_failure_does_not_install_dependencies_or_mutate_selection(
    admission, monkeypatch, failure
):
    import subprocess

    home, roots = admission
    path = provider(roots[1], "contract_broken", "broken", prefix=failure)
    (path / "requirements.txt").write_text("contract_missing_dependency_7349==0.0.0\n")
    before = (home / "config.yaml").read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("Runtime provider loading must not spawn an installer")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert memory.load_memory_provider("contract_broken") is None
    assert memory.discover_memory_providers() == [("contract_broken", "broken", False)]
    assert (home / "config.yaml").read_bytes() == before


def test_disabled_directory_refused_before_import(admission):
    home, roots = admission
    path = provider(roots[1], "contract_disabled", "disabled")
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "memory": {"provider": "contract_disabled"},
                "plugins": {"disabled": ["contract_disabled"]},
            }
        )
    )
    assert memory.load_memory_provider("contract_disabled") is None
    assert "turned off" in memory.parked_provider_notice("contract_disabled")
    assert not (path / "imported").exists()


@pytest.mark.parametrize("isolation,loads", [("in_process", True), ("host", False)])
def test_module_entrypoint_disable_is_not_directory_parking_and_host_mode_refuses(
    admission, tmp_path, monkeypatch, isolation, loads
):
    home, _ = admission
    entry(monkeypatch, tmp_path)
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "memory": {"provider": "contract_ep"},
                "plugins": {"disabled": ["contract_ep"], "isolation": isolation},
            }
        )
    )
    loaded = memory.load_memory_provider("contract_ep")
    assert (loaded is not None) is loads
    assert ("contract_ep" in sys.modules) is loads
    # Bare-module entry points have no provider directory and no parking notice.
    assert memory.parked_provider_notice("contract_ep") is None


def test_directory_provider_host_mode_runs_in_separate_process(admission):
    import os

    from hermes_cli.plugin_host import is_hosted_object
    from hermes_cli.plugin_isolation import transient_plugin_host

    home, roots = admission
    path = provider(roots[1], "contract_isolated", "isolated")
    source = path / "__init__.py"
    source.write_text(
        source.read_text().replace(
            "def system_prompt_block(self): return 'isolated'",
            "def system_prompt_block(self):\n        import os\n        return str(os.getpid())",
        )
    )
    (home / "config.yaml").write_text(
        json.dumps({"memory": {"provider": "contract_isolated"}, "plugins": {"isolation": "host"}})
    )
    with transient_plugin_host():
        loaded = memory.load_memory_provider("contract_isolated", register_skills=False)
        assert loaded is not None and is_hosted_object(loaded)
        assert loaded.is_available()
        assert int(loaded.system_prompt_block()) != os.getpid()
        assert memory._module_name(path, "contract_isolated") not in sys.modules
        loaded.shutdown()
    # Process separation is not a filesystem/network sandbox or security audit.
