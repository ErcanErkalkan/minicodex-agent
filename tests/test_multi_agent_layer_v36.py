from __future__ import annotations

import json

from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.multi_agent import (
    AgentMailbox,
    AgentResultMerger,
    RoleAgentResult,
    list_multi_agent_runs,
    plan_subagent_threads,
    read_multi_agent_run,
    run_multi_agent_work,
    run_subagent_threads,
)
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tools.context import ToolContext


def _ctx(tmp_path, *, dry_run=True):
    config = AgentConfig(
        root=tmp_path,
        model="stub-model",
        provider="stub",
        dry_run=dry_run,
        approval="auto",
        log_enabled=False,
        project_policy_enabled=False,
        multi_agent_thread_max_messages=6,
        multi_agent_result_max_chars=6000,
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


def _payload(output: str) -> dict:
    return json.loads(output.split("\n", 1)[1])


def test_plan_subagent_threads_has_thread_contract(tmp_path):
    out = plan_subagent_threads(tmp_path, "fix tests", max_agents=2, roles=["planner", "tester"])
    assert "Subagent thread plan" in out
    data = _payload(out)
    assert data["thread_model"].startswith("parent coordinator")
    assert {thread["role"] for thread in data["threads"]} == {"planner", "tester"}
    assert data["communication_contract"]["handoff"].startswith("completed role")


def test_run_multi_agent_work_records_threads_mailbox_and_merge(tmp_path):
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
    data = _payload(out)
    assert data["summary"]["threads"] == 2
    assert data["summary"]["mailbox_messages"] >= 3
    assert len(data["threads"]) == 2
    assert all(thread["thread_id"].startswith("thr_") for thread in data["threads"])
    assert data["merged_result"]["status"] == "merged"
    assert not (tmp_path / ".minicodex" / "multi_agent_runs").exists()


def test_run_subagent_threads_alias_uses_same_payload(tmp_path):
    ctx = _ctx(tmp_path)
    out = run_subagent_threads(
        ctx,
        goal="inspect project",
        max_agents=1,
        roles=["planner"],
        max_steps_each=1,
        model_call_budget_each=1,
        dry_run=True,
    )
    assert "DRY-RUN" in out
    data = _payload(out)
    assert data["thread_model"]["mailbox_enabled"] is True
    assert data["roles"][0]["role"] == "planner"


def test_saved_run_can_be_read_without_observations(tmp_path):
    ctx = _ctx(tmp_path, dry_run=False)
    out = run_multi_agent_work(
        ctx, goal="inspect", max_agents=1, roles=["planner"], max_steps_each=1, dry_run=False
    )
    data = _payload(out)
    run_id = data["run_id"]
    listed = list_multi_agent_runs(tmp_path)
    assert run_id in listed
    read = read_multi_agent_run(tmp_path, run_id, include_observations=False)
    assert "Saved multi-agent run" in read
    assert "merged_result" in read
    assert "observations" not in read


def test_result_merger_flags_unfinished_and_write_roles():
    mailbox = AgentMailbox()
    mailbox.post("planner", "all", "plan", kind="result")
    results = [
        RoleAgentResult("planner", "finished", 1, ("finish",), "ok", tuple(), thread_id="t1"),
        RoleAgentResult(
            "implementer",
            "max_steps_reached",
            2,
            ("apply_patch", "finish"),
            "needs more",
            tuple(),
            thread_id="t2",
        ),
    ]
    merged = AgentResultMerger.merge("goal", results, mailbox)
    assert merged["status"] == "needs_review"
    assert merged["failed_roles"] == ["implementer"]
    assert merged["write_roles"] == ["implementer"]
