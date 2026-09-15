"""Multi-agent and subagent thread tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.multi_agent import (
    list_multi_agent_runs,
    plan_subagent_threads,
    read_multi_agent_run,
    run_multi_agent_work,
    run_subagent_threads,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def _roles(args: Mapping[str, Any]) -> list[str]:
    roles_raw = args.get("roles", [])
    return [str(role) for role in roles_raw] if isinstance(roles_raw, list) else []


def handle_plan_subagent_threads(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return plan_subagent_threads(
        ctx.config.root,
        goal=str(args.get("goal", ctx.state.goal)),
        max_agents=min(int(args.get("max_agents", 4)), ctx.config.max_agent_batch_size),
        roles=_roles(args),
        max_steps_each=int(args.get("max_steps_each", 3)),
        model_call_budget_each=int(args.get("model_call_budget_each", 4)),
    )


def handle_run_multi_agent_work(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return run_multi_agent_work(
        ctx,
        goal=str(args.get("goal", ctx.state.goal)),
        max_agents=min(int(args.get("max_agents", 4)), ctx.config.max_agent_batch_size),
        execution_mode=str(args.get("execution_mode", "sequential")),
        max_steps_each=int(args.get("max_steps_each", 3)),
        model_call_budget_each=int(args.get("model_call_budget_each", 4)),
        roles=_roles(args),
        dry_run=bool(args.get("dry_run", ctx.config.dry_run)),
    )


def handle_run_subagent_threads(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return run_subagent_threads(
        ctx,
        goal=str(args.get("goal", ctx.state.goal)),
        max_agents=min(int(args.get("max_agents", 4)), ctx.config.max_agent_batch_size),
        execution_mode=str(args.get("execution_mode", "sequential")),
        max_steps_each=int(args.get("max_steps_each", 3)),
        model_call_budget_each=int(args.get("model_call_budget_each", 4)),
        roles=_roles(args),
        dry_run=bool(args.get("dry_run", ctx.config.dry_run)),
    )


def handle_list_multi_agent_runs(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_multi_agent_runs(ctx.config.root, limit=int(args.get("limit", 10)))


def handle_read_multi_agent_run(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_multi_agent_run(
        ctx.config.root,
        str(args.get("run_id", "")),
        include_observations=bool(args.get("include_observations", False)),
        max_chars=int(args.get("max_chars", 40000)),
    )


register_tools(
    [
        ToolSpec(
            "plan_subagent_threads",
            ACTION_SPECS["plan_subagent_threads"],
            handle_plan_subagent_threads,
            plugin="multi-agent",
            description="Plan Codex-style parent/child subagent threads with role-scoped budgets and mailbox handoffs.",
        ),
        ToolSpec(
            "run_multi_agent_work",
            ACTION_SPECS["run_multi_agent_work"],
            handle_run_multi_agent_work,
            plugin="multi-agent",
            requires_approval=True,
            risk_level="high",
            description="Run bounded local role workers with separate threads, mailbox context, tool allowlists, and budgets.",
        ),
        ToolSpec(
            "run_subagent_threads",
            ACTION_SPECS["run_subagent_threads"],
            handle_run_subagent_threads,
            plugin="multi-agent",
            requires_approval=True,
            risk_level="high",
            description="Run Codex-style subagent threads; alias for the enhanced multi-agent coordinator.",
        ),
        ToolSpec(
            "list_multi_agent_runs",
            ACTION_SPECS["list_multi_agent_runs"],
            handle_list_multi_agent_runs,
            plugin="multi-agent",
            description="List previous bounded real multi-agent/subagent run summaries.",
        ),
        ToolSpec(
            "read_multi_agent_run",
            ACTION_SPECS["read_multi_agent_run"],
            handle_read_multi_agent_run,
            plugin="multi-agent",
            description="Read a saved multi-agent run transcript by run_id, optionally including observations.",
        ),
    ]
)
