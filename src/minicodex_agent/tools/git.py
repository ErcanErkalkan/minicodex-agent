"""Git and change-review tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.change_review import record_change_approval, review_change_set
from minicodex_agent.git_tools import git_status
from minicodex_agent.pr_tools import prepare_pr_summary
from minicodex_agent.shell_tools import git_diff
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def handle_git_status(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return git_status(ctx.config.root, ctx.config.max_observation_chars)


def handle_git_diff(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return git_diff(
        ctx.config.root, ctx.config.max_observation_chars, profile=ctx.config.safety_profile
    )


def handle_review_change_set(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return review_change_set(
        ctx.config.root,
        max_diff_chars=int(args.get("max_diff_chars", ctx.config.max_observation_chars)),
    )


def handle_record_change_approval(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return record_change_approval(
        ctx.config.root,
        decision=str(args["decision"]),
        note=str(args.get("note", "")),
        dry_run=ctx.config.dry_run,
    )


def handle_prepare_pr_summary(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return prepare_pr_summary(
        ctx.config.root, goal=ctx.state.goal, max_chars=ctx.config.max_observation_chars
    )


register_tools(
    [
        ToolSpec("git_status", ACTION_SPECS["git_status"], handle_git_status, plugin="git"),
        ToolSpec("git_diff", ACTION_SPECS["git_diff"], handle_git_diff, plugin="git"),
        ToolSpec(
            "review_change_set",
            ACTION_SPECS["review_change_set"],
            handle_review_change_set,
            plugin="git",
        ),
        ToolSpec(
            "record_change_approval",
            ACTION_SPECS["record_change_approval"],
            handle_record_change_approval,
            plugin="git",
        ),
        ToolSpec(
            "prepare_pr_summary",
            ACTION_SPECS["prepare_pr_summary"],
            handle_prepare_pr_summary,
            plugin="git",
        ),
    ]
)
