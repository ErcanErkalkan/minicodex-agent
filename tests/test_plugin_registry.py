import json

from minicodex_agent.plugin_registry import list_plugin_infos, render_plugins, render_tool_help


def test_plugin_registry_lists_builtins_and_local_manifest(tmp_path):
    plugin_dir = tmp_path / ".minicodex" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "demo.json").write_text(
        json.dumps({"name": "demo", "tools": ["demo_tool"]}), encoding="utf-8"
    )
    names = [plugin.name for plugin in list_plugin_infos(tmp_path)]
    assert "filesystem" in names
    assert "demo" in names
    rendered = render_plugins(tmp_path)
    assert "demo" in rendered
    assert "read_file" in render_tool_help("read_file")
    assert "Supported MiniCodex tools" in render_tool_help()


def test_plugin_registry_accepts_utf8_bom_manifest(tmp_path):
    plugin_dir = tmp_path / ".minicodex" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "bom-plugin.json").write_text(
        json.dumps({"name": "bom-plugin", "tools": ["write_file"]}),
        encoding="utf-8-sig",
    )

    plugins = {plugin.name: plugin for plugin in list_plugin_infos(tmp_path)}

    assert plugins["bom-plugin"].tools == ("write_file",)
