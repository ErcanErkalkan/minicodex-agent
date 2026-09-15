from __future__ import annotations

import json

from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.plugin_registry import check_tool_access, list_enabled_tools
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_policy import read_effective_project_policy
from minicodex_agent.project_settings import update_project_config


def _agent(tmp_path):
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        show_diff=False,
        project_config_enabled=True,
        project_policy_enabled=True,
    )
    return MiniCodexAgent(config), AgentState(goal="test", project_profile=detect_project(tmp_path))


def test_execute_action_blocks_tool_not_exposed_by_enabled_builtin_plugin(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    update_project_config(tmp_path, {"enabled_plugins": ["filesystem"]})
    agent, state = _agent(tmp_path)

    allowed = agent.execute_action(state, "read_file", {"path": "hello.txt"})
    blocked = agent.execute_action(state, "run_tests", {})

    assert "hello" in allowed
    assert blocked.startswith("TOOL BLOCK:")
    assert "run_tests" in blocked


def test_check_tool_access_does_not_fallback_to_all_tools_for_unknown_enabled_plugin(tmp_path):
    update_project_config(tmp_path, {"enabled_plugins": ["does-not-exist"]})

    assert "run_command" not in list_enabled_tools(tmp_path)
    decision = check_tool_access(tmp_path, "run_command")

    assert not decision.allowed
    assert "enabled_plugins" in decision.render()


def test_control_actions_remain_available_when_plugins_are_restricted(tmp_path):
    update_project_config(tmp_path, {"enabled_plugins": ["filesystem"]})

    assert check_tool_access(tmp_path, "finish").allowed
    assert "finish" in list_enabled_tools(tmp_path)


def test_enabled_local_plugin_policy_is_merged_into_runtime_policy(tmp_path):
    plugin_dir = tmp_path / ".minicodex" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "docs-writer.json").write_text(
        json.dumps(
            {
                "name": "docs-writer",
                "tools": ["write_file"],
                "policies": {
                    "allowed_write_globs": ["docs/**"],
                    "blocked_write_globs": ["docs/secret.md"],
                    "blocked_command_regexes": ["forbidden-tool"],
                },
            }
        ),
        encoding="utf-8",
    )
    update_project_config(tmp_path, {"enabled_plugins": ["docs-writer"]})

    policy = read_effective_project_policy(tmp_path)
    assert "docs/**" in policy["plugin_allowed_write_globs"]
    assert "docs/secret.md" in policy["blocked_write_globs"]
    assert "forbidden-tool" in policy["blocked_command_regexes"]

    agent, state = _agent(tmp_path)
    outside = agent.execute_action(state, "write_file", {"path": "outside.md", "content": "x"})
    secret = agent.execute_action(state, "write_file", {"path": "docs/secret.md", "content": "x"})
    allowed = agent.execute_action(state, "write_file", {"path": "docs/readme.md", "content": "ok"})

    assert outside.startswith("POLICY BLOCK:")
    assert "enabled plugin allowed_write_globs" in outside
    assert secret.startswith("POLICY BLOCK:")
    assert "blocked_write_globs" in secret
    assert (
        "Dosya oluşturuldu" in allowed
        or "Dosya yazıldı" in allowed
        or "Wrote file" in allowed
        or "Created file" in allowed
    )
    assert (tmp_path / "docs" / "readme.md").read_text(encoding="utf-8") == "ok"
