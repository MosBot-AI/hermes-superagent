"""Real YAML regression for isolated packaged-memory configuration, no Gateway."""

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def enable_installed_memory():
    source = (ROOT / "acceptance/live/test_packaged_gateway_memory.py").read_text()
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "enable_installed_memory"
    )
    namespace = {}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "<memory-config>", "exec"), namespace
    )
    return namespace["enable_installed_memory"]


@pytest.mark.parametrize("installer_yaml", [False, True])
def test_memory_opt_in_preserves_installer_configuration(
    tmp_path, installer_yaml, enable_installed_memory
):
    """Executable YAML regression; no installation, listener, or model required."""
    from ruamel.yaml import YAML

    original = {
        "gateway": {"multiplex_profiles": False},
        "model": {"default": "synthetic-model-label"},
        "auxiliary": {"title_generation": {"enabled": False}},
        "platform_toolsets": {"cli": []},
        "plugins": {
            "isolation": "in_process",
            "entries": {
                "hermes-personal-agent": {
                    "settings": {
                        "mode": "local_tasks",
                        "local_conversation": True,
                        "local_model_tools": True,
                    }
                }
            },
            "enabled": ["hermes-personal-agent"],
            "disabled": [],
        },
    }
    text = json.dumps(original)
    if installer_yaml:
        # The official installer appends unquoted YAML keys/values inside an
        # initially JSON-style flow mapping. This is valid YAML but not JSON.
        text = text.replace(
            '"enabled": ["hermes-personal-agent"]', "enabled: [hermes-personal-agent]"
        )
        text = text.replace('"disabled": []', "disabled: []")
        text = "# Preserve this operator comment.\n" + text
        with pytest.raises(json.JSONDecodeError):
            json.loads(text)
    path = tmp_path / "config.yaml"
    path.write_text(text)
    enable_installed_memory(tmp_path)
    expected = json.loads(json.dumps(original))
    expected["plugins"]["entries"]["hermes-personal-agent"]["settings"]["local_memory"] = True
    assert YAML().load(path) == expected
    if installer_yaml:
        assert "# Preserve this operator comment." in path.read_text()
    # Reapplying the opt-in must preserve every unrelated setting as well.
    enable_installed_memory(tmp_path)
    assert YAML().load(path) == expected
