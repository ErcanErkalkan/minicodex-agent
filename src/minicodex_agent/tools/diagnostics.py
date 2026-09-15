"""Failure-analysis and recovery tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.failure_tools import analyze_failure_output
from minicodex_agent.recovery_tools import diagnose_patch_failure
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def handle_analyze_failure(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    output = str(args.get("output") or ctx.state.last_command_output)
    return analyze_failure_output(
        ctx.config.root,
        output=output,
        context_lines=int(args.get("context_lines", ctx.config.test_failure_context_lines)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_diagnose_patch_failure(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return diagnose_patch_failure(
        ctx.config.root,
        patch_text=str(args.get("patch", "")),
        error=str(args.get("error", "")),
        max_chars=ctx.config.max_observation_chars,
    )


register_tools(
    [
        ToolSpec(
            "analyze_failure",
            ACTION_SPECS["analyze_failure"],
            handle_analyze_failure,
            plugin="diagnostics",
        ),
        ToolSpec(
            "diagnose_patch_failure",
            ACTION_SPECS["diagnose_patch_failure"],
            handle_diagnose_patch_failure,
            plugin="diagnostics",
        ),
    ]
)
