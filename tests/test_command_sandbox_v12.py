from __future__ import annotations

from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.project_inspector import detect_project


def _state(tmp_path):
    return AgentState(goal="test", project_profile=detect_project(tmp_path))


def test_auto_approval_does_not_silently_run_network_install(tmp_path):
    agent = MiniCodexAgent(
        AgentConfig(
            root=tmp_path,
            model="stub",
            provider="stub",
            approval="auto",
            safety_profile="balanced",
            allow_network_commands=True,
            show_diff=False,
        )
    )

    result = agent.execute_action(
        _state(tmp_path), "run_command", {"command": "pip install requests"}
    )

    assert result.startswith("MANUAL APPROVAL REQUIRED:")
    assert "network/install" in result


def test_network_install_is_blocked_without_separate_permission(tmp_path):
    agent = MiniCodexAgent(
        AgentConfig(
            root=tmp_path,
            model="stub",
            provider="stub",
            approval="auto",
            safety_profile="balanced",
            allow_network_commands=False,
            show_diff=False,
        )
    )

    result = agent.execute_action(
        _state(tmp_path), "run_command", {"command": "pip install requests"}
    )

    assert result.startswith("COMMAND BLOCK:")
    assert "requires --allow-network-commands" in result
