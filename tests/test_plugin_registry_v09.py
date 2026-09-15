from __future__ import annotations

import json

from minicodex_agent.plugin_registry import (
    inspect_plugin,
    list_enabled_tools,
    render_enabled_tools,
    validate_plugin_manifests,
)
from minicodex_agent.project_settings import update_project_config


def test_validate_local_plugin_manifest(tmp_path):
    plugin_dir = tmp_path / ".minicodex" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "local.json").write_text(
        json.dumps({"name": "local", "tools": ["read_file"], "prompts": ["Be careful"]}),
        encoding="utf-8",
    )
    report = validate_plugin_manifests(tmp_path)
    assert '"valid": true' in report
    assert "local.json" in report
    assert "local" in inspect_plugin(tmp_path, "local")


def test_validate_plugin_rejects_unknown_tool(tmp_path):
    plugin_dir = tmp_path / ".minicodex" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "bad.json").write_text(
        json.dumps({"name": "bad", "tools": ["not_a_tool"]}), encoding="utf-8"
    )
    report = validate_plugin_manifests(tmp_path)
    assert "unknown tool" in report


def test_enabled_tools_respects_project_config(tmp_path):
    update_project_config(tmp_path, {"enabled_plugins": ["filesystem"]})
    tools = list_enabled_tools(tmp_path)
    assert "read_file" in tools
    assert "run_tests" not in tools
    rendered = render_enabled_tools(tmp_path)
    assert "read_file" in rendered
