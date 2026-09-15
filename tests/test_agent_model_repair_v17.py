from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.agent import MiniCodexAgent
from minicodex_agent.config import AgentConfig


class RepairingModelClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def next_action_text(self, prompt: str, *, repair_error=None, invalid_output=None) -> str:
        self.calls.append(
            {"prompt": prompt, "repair_error": repair_error, "invalid_output": invalid_output}
        )
        if len(self.calls) == 1:
            return json.dumps(
                {
                    "thought": "bad",
                    "action": "read_file",
                    "args": {"path": "README.md", "extra": True},
                }
            )
        return json.dumps(
            {
                "thought": "repaired",
                "action": "finish",
                "args": {"summary": "fixed", "changed_files": [], "checks_run": []},
            }
        )


def test_agent_repairs_invalid_model_action(tmp_path: Path) -> None:
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        model_repair_attempts=1,
        log_enabled=False,
        show_diff=False,
    )
    agent = MiniCodexAgent(config)
    fake = RepairingModelClient()
    agent.model_client = fake  # type: ignore[assignment]

    decision = agent._request_valid_decision("{}", step=1)

    assert decision["action"] == "finish"
    assert len(fake.calls) == 2
    assert fake.calls[1]["repair_error"]
    assert "unsupported arg" in fake.calls[1]["repair_error"]


def test_agent_finishes_after_repair_attempts_exhausted(tmp_path: Path) -> None:
    class AlwaysBadModel:
        def next_action_text(self, prompt: str, *, repair_error=None, invalid_output=None) -> str:
            return "not json"

    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        model_repair_attempts=1,
        log_enabled=False,
        show_diff=False,
    )
    agent = MiniCodexAgent(config)
    agent.model_client = AlwaysBadModel()  # type: ignore[assignment]

    decision = agent._request_valid_decision("{}", step=1)

    assert decision["action"] == "finish"
    assert "repair denemeleri" in decision["args"]["summary"]
