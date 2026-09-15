from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.config import AgentConfig
from minicodex_agent.eval_runner import run_eval_task


def test_eval_report_contains_telemetry_link(tmp_path: Path) -> None:
    task_dir = tmp_path / ".minicodex" / "evals" / "tasks"
    task_dir.mkdir(parents=True)
    (task_dir / "smoke.json").write_text(
        json.dumps(
            {
                "id": "smoke",
                "title": "Smoke",
                "goal": "Finish",
                "files": {"README.md": "# Demo\n"},
                "expected": {},
                "verification_commands": [],
            }
        ),
        encoding="utf-8",
    )
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        log_enabled=False,
        show_diff=False,
        max_steps=1,
    )
    report = run_eval_task(
        tmp_path, config, "smoke", run_id="eval-link", max_steps=1, model_call_budget=1
    )
    agent = report["agent"]
    assert agent["telemetry_run_id"] == "eval-link-smoke"
    assert agent["telemetry_available"] is True
    assert (tmp_path / agent["telemetry_trace_path"]).exists()
    assert "latency_summary" in agent
    assert "failure_taxonomy_summary" in agent
