"""Long-horizon task, checkpoint, and resume tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.long_horizon import (
    create_checkpoint,
    create_long_task,
    list_long_tasks,
    read_long_task,
    resume_long_task,
    update_acceptance_criteria,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.common import as_string_list
from minicodex_agent.tools.context import ToolContext


def handle_create_long_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return create_long_task(
        ctx.config.root,
        goal=str(args.get("goal", ctx.state.goal)),
        title=str(args.get("title", "")),
        acceptance_criteria=as_string_list(args, "acceptance_criteria") or [],
        milestones=as_string_list(args, "milestones") or [],
        dry_run=ctx.config.dry_run,
    )


def handle_list_long_tasks(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_long_tasks(
        ctx.config.root,
        limit=int(args.get("limit", 20)),
        include_completed=bool(args.get("include_completed", True)),
    )


def handle_read_long_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_long_task(
        ctx.config.root,
        str(args["run_id"]),
        include_checkpoints=bool(args.get("include_checkpoints", True)),
        max_chars=int(args.get("max_chars", 40000)),
    )


def handle_resume_long_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return resume_long_task(
        ctx.config.root,
        str(args["run_id"]),
        max_chars=int(args.get("max_chars", ctx.config.long_horizon_resume_max_chars)),
    )


def handle_update_acceptance_criteria(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return update_acceptance_criteria(
        ctx.config.root,
        str(args["run_id"]),
        accepted=as_string_list(args, "accepted") or [],
        blocked=as_string_list(args, "blocked") or [],
        pending=as_string_list(args, "pending") or [],
        evidence=str(args.get("evidence", "")),
        dry_run=ctx.config.dry_run,
    )


def handle_create_checkpoint(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return create_checkpoint(
        ctx.config.root,
        str(args["run_id"]),
        label=str(args.get("label", "checkpoint")),
        summary=str(args.get("summary", "")),
        completed_milestones=as_string_list(args, "completed_milestones") or [],
        accepted_criteria=as_string_list(args, "accepted_criteria") or [],
        changed_files=as_string_list(args, "changed_files") or [],
        checks_run=as_string_list(args, "checks_run") or [],
        next_steps=as_string_list(args, "next_steps") or [],
        observations_summary=str(args.get("observations_summary", "")),
        status=str(args.get("status", "active")),
        dry_run=ctx.config.dry_run,
    )


register_tools(
    [
        ToolSpec(
            "create_long_task",
            ACTION_SPECS["create_long_task"],
            handle_create_long_task,
            plugin="long-horizon",
            requires_approval=True,
            risk_level="medium",
            description="Create a durable long-horizon task record with acceptance criteria and milestones.",
        ),
        ToolSpec(
            "list_long_tasks",
            ACTION_SPECS["list_long_tasks"],
            handle_list_long_tasks,
            plugin="long-horizon",
        ),
        ToolSpec(
            "read_long_task",
            ACTION_SPECS["read_long_task"],
            handle_read_long_task,
            plugin="long-horizon",
        ),
        ToolSpec(
            "resume_long_task",
            ACTION_SPECS["resume_long_task"],
            handle_resume_long_task,
            plugin="long-horizon",
        ),
        ToolSpec(
            "update_acceptance_criteria",
            ACTION_SPECS["update_acceptance_criteria"],
            handle_update_acceptance_criteria,
            plugin="long-horizon",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "create_checkpoint",
            ACTION_SPECS["create_checkpoint"],
            handle_create_checkpoint,
            plugin="long-horizon",
            requires_approval=True,
            risk_level="medium",
            description="Append a checkpoint for resume/continuation without rerunning the whole agent history.",
        ),
    ]
)
