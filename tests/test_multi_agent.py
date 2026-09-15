from __future__ import annotations

from minicodex_agent.multi_agent import list_agent_batches, make_multi_agent_plan, run_task_batch


def test_make_multi_agent_plan(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    out = make_multi_agent_plan(tmp_path, "fix tests", max_agents=3)
    assert "Multi-agent work plan" in out
    assert "planner" in out
    assert "code-researcher" in out


def test_run_task_batch_dry_run_does_not_save(tmp_path):
    out = run_task_batch(tmp_path, ["a", "b"], dry_run=True)
    assert "DRY-RUN" in out
    assert "task-1" in out
    assert "No agent batch" in list_agent_batches(tmp_path)


def test_run_task_batch_saves(tmp_path):
    out = run_task_batch(tmp_path, ["a"], dry_run=False)
    assert "Task batch saved" in out
    listed = list_agent_batches(tmp_path)
    assert "task-1" in listed
