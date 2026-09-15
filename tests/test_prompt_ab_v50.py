from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.config import AgentConfig
from minicodex_agent.prompt_ab import run_prompt_ab_comparison


def test_prompt_ab_runs_offline_with_stub_provider(tmp_path: Path) -> None:
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
    report = run_prompt_ab_comparison(
        tmp_path,
        config,
        ["smoke"],
        ["auto", "local-model"],
        run_id="demo",
        max_steps=1,
        model_call_budget=1,
        timeout=30,
    )
    assert report["ok"] is True
    assert report["winner"]["profile"] in {"auto", "local-model"}
    assert len(report["profiles"]) == 2
    assert (tmp_path / ".minicodex" / "evals" / "reports" / "ab-demo.json").exists()
