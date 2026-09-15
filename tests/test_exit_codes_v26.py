from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from minicodex_agent import cli
from minicodex_agent.agent import MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.exit_codes import ExitCode, RunResult, classify_action_outcome
from minicodex_agent.model_client import ModelCallError


class SequenceModelClient:
    def __init__(self, decisions: list[dict | str]) -> None:
        self.decisions = list(decisions)

    def next_action_text(self, prompt: str, *, repair_error=None, invalid_output=None) -> str:
        item = self.decisions.pop(0)
        if isinstance(item, str):
            return item
        return json.dumps(item)


def _config(root: Path, *, max_steps: int = 4) -> AgentConfig:
    return AgentConfig(
        root=root,
        model="stub",
        provider="stub",
        approval="auto",
        safety_profile="balanced",
        show_diff=False,
        log_enabled=False,
        auto_snapshot_before_edit=False,
        project_policy_enabled=False,
        max_steps=max_steps,
        model_repair_attempts=0,
    )


def test_classify_action_outcome_maps_stable_exit_codes() -> None:
    assert classify_action_outcome("run_tests", "Exit code: 1\n") == RunResult(
        ExitCode.TESTS_FAILED, "tests_failed", "run_tests exited with 1"
    )
    assert classify_action_outcome("run_command", "Exit code: 7\n") == RunResult(
        ExitCode.TOOL_EXECUTION_FAILED, "tool_execution_failed", "run_command exited with 7"
    )
    assert classify_action_outcome("run_command", "POLICY BLOCK: no") == RunResult(
        ExitCode.POLICY_BLOCKED, "policy_blocked", "POLICY BLOCK: no"
    )
    assert classify_action_outcome("read_file", "hello") is None


def test_agent_run_returns_success_exit_code(tmp_path: Path) -> None:
    agent = MiniCodexAgent(_config(tmp_path))
    agent.model_client = SequenceModelClient(
        [
            {"thought": "done", "action": "finish", "args": {"summary": "ok"}},
        ]
    )  # type: ignore[assignment]

    result = agent.run("finish")

    assert result.exit_code == ExitCode.SUCCESS
    assert result.status == "success"


def test_agent_run_returns_tests_failed_exit_code(tmp_path: Path) -> None:
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    agent = MiniCodexAgent(_config(tmp_path))
    agent.model_client = SequenceModelClient(
        [
            {
                "thought": "test",
                "action": "run_tests",
                "args": {"command": "python -m pytest -q", "timeout": 30},
            },
            {"thought": "done", "action": "finish", "args": {"summary": "done"}},
        ]
    )  # type: ignore[assignment]

    result = agent.run("run failing tests")

    assert result.exit_code == ExitCode.TESTS_FAILED
    assert result.status == "tests_failed"


def test_agent_run_returns_policy_blocked_exit_code(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        safety_profile="strict",
        show_diff=False,
        log_enabled=False,
        project_policy_enabled=False,
        auto_snapshot_before_edit=False,
        max_steps=3,
    )
    agent = MiniCodexAgent(config)
    agent.model_client = SequenceModelClient(
        [
            {"thought": "blocked", "action": "run_command", "args": {"command": "echo unsafe"}},
            {"thought": "done", "action": "finish", "args": {"summary": "done"}},
        ]
    )  # type: ignore[assignment]

    result = agent.run("run blocked command")

    assert result.exit_code == ExitCode.POLICY_BLOCKED
    assert result.status == "policy_blocked"


def test_agent_run_returns_tool_execution_failed_exit_code(tmp_path: Path) -> None:
    agent = MiniCodexAgent(_config(tmp_path))
    agent.model_client = SequenceModelClient(
        [
            {
                "thought": "run failing command",
                "action": "run_command",
                "args": {"command": 'python -c "import sys; sys.exit(7)"', "timeout": 30},
            },
            {"thought": "done", "action": "finish", "args": {"summary": "done"}},
        ]
    )  # type: ignore[assignment]

    result = agent.run("run failing command")

    assert result.exit_code == ExitCode.TOOL_EXECUTION_FAILED
    assert result.status == "tool_execution_failed"


def test_agent_run_returns_model_action_error_for_invalid_json(tmp_path: Path) -> None:
    agent = MiniCodexAgent(_config(tmp_path, max_steps=1))
    agent.model_client = SequenceModelClient(["not json"])  # type: ignore[assignment]

    result = agent.run("invalid model output")

    assert result.exit_code == ExitCode.MODEL_ACTION_ERROR
    assert result.status == "model_action_error"


def test_agent_run_returns_model_action_error_when_provider_fails(tmp_path: Path) -> None:
    class FailingModel:
        def next_action_text(self, prompt: str, *, repair_error=None, invalid_output=None) -> str:
            raise ModelCallError("rate limited")

    agent = MiniCodexAgent(_config(tmp_path, max_steps=1))
    agent.model_client = FailingModel()  # type: ignore[assignment]

    result = agent.run("provider failure")

    assert result.exit_code == ExitCode.MODEL_ACTION_ERROR
    assert result.status == "model_action_error"


def test_agent_run_returns_model_action_error_on_max_steps(tmp_path: Path) -> None:
    agent = MiniCodexAgent(_config(tmp_path, max_steps=1))
    agent.model_client = SequenceModelClient(
        [{"thought": "plan", "action": "update_plan", "args": {"steps": ["do work"]}}]
    )  # type: ignore[assignment]

    result = agent.run("never finishes")

    assert result.exit_code == ExitCode.MODEL_ACTION_ERROR
    assert result.status == "max_steps_exceeded"


def test_cli_exits_with_agent_result_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeAgent:
        def __init__(self, config: AgentConfig) -> None:
            self.config = config

        def run(self, goal: str) -> RunResult:
            assert goal == "goal"
            return RunResult(ExitCode.TESTS_FAILED, "tests_failed", "demo")

    monkeypatch.setattr(cli, "MiniCodexAgent", FakeAgent)
    monkeypatch.setattr(
        sys,
        "argv",
        ["minicodex", "goal", "--root", str(tmp_path), "--provider", "stub", "--no-log"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == int(ExitCode.TESTS_FAILED)
