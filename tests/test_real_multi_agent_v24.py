from __future__ import annotations

import json

from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.multi_agent import list_multi_agent_runs, run_multi_agent_work
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tools.context import ToolContext


def _ctx(tmp_path, *, provider="stub", dry_run=True):
    config = AgentConfig(
        root=tmp_path,
        model="stub-model",
        provider=provider,
        dry_run=dry_run,
        approval="auto",
        log_enabled=False,
        project_policy_enabled=False,
    )
    agent = MiniCodexAgent(config)
    state = AgentState(goal="inspect project", project_profile=detect_project(tmp_path))
    return ToolContext(
        config=config,
        state=state,
        logger=agent.logger,
        confirm_fn=lambda question, auto_approve, force_manual=False: True,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=agent._ensure_auto_snapshot_before_edit,
        mark_auto_snapshot_handled_fn=agent._mark_auto_snapshot_handled,
    )


def test_run_multi_agent_work_uses_independent_role_workers(tmp_path):
    ctx = _ctx(tmp_path)
    out = run_multi_agent_work(
        ctx,
        goal="inspect project",
        max_agents=2,
        roles=["planner", "code-researcher"],
        max_steps_each=1,
        model_call_budget_each=1,
        dry_run=True,
    )
    assert "DRY-RUN: multi-agent run not saved" in out
    data = json.loads(out.split("\n", 1)[1])
    assert data["summary"]["workers"] == 2
    assert {role["role"] for role in data["roles"]} == {"planner", "code-researcher"}
    assert all(role["model_call_budget"] == 1 for role in data["roles"])
    assert not (tmp_path / ".minicodex" / "multi_agent_runs").exists()


def test_run_multi_agent_parallel_downgrades_when_write_role_selected(tmp_path):
    ctx = _ctx(tmp_path)
    out = run_multi_agent_work(
        ctx,
        goal="edit docs",
        max_agents=1,
        roles=["implementer"],
        execution_mode="parallel",
        max_steps_each=1,
        dry_run=True,
    )
    data = json.loads(out.split("\n", 1)[1])
    assert data["requested_execution_mode"] == "parallel"
    assert data["actual_execution_mode"] == "sequential"
    assert "downgraded" in data["note"]


def test_agent_dispatches_run_multi_agent_work(tmp_path):
    agent = MiniCodexAgent(
        AgentConfig(
            root=tmp_path,
            model="stub-model",
            provider="stub",
            dry_run=True,
            approval="auto",
            log_enabled=False,
            project_policy_enabled=False,
        )
    )
    state = AgentState(goal="inspect", project_profile=detect_project(tmp_path))
    out = agent.execute_action(
        state,
        "run_multi_agent_work",
        {"roles": ["planner"], "max_agents": 1, "max_steps_each": 1, "dry_run": True},
    )
    assert "DRY-RUN: multi-agent run not saved" in out


def test_list_multi_agent_runs(tmp_path):
    ctx = _ctx(tmp_path)
    run_multi_agent_work(
        ctx, goal="inspect", max_agents=1, roles=["planner"], max_steps_each=1, dry_run=False
    )
    out = list_multi_agent_runs(tmp_path)
    assert "Recent real multi-agent runs" in out
    assert "planner" not in out or "summary" in out
