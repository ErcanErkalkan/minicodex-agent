"""Tool handlers for MiniCodex local observability telemetry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.failure_taxonomy import build_failure_taxonomy_dashboard
from minicodex_agent.model_pricing import list_model_prices
from minicodex_agent.telemetry import (
    compare_telemetry_runs,
    export_telemetry_bundle,
    list_telemetry_runs,
    read_telemetry_run,
    render_optimization_dashboard,
    summarize_telemetry,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.utils import to_pretty_json, truncate


def handle_list_telemetry_runs(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    limit = int(args.get("limit", 20) or 20)
    return "Telemetry runs:\n" + to_pretty_json(list_telemetry_runs(ctx.config.root, limit=limit))


def handle_read_telemetry_run(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    run_id = str(args.get("run_id", ""))
    include_spans = bool(args.get("include_spans", True))
    max_chars = int(args.get("max_chars", 24000) or 24000)
    return read_telemetry_run(
        ctx.config.root, run_id, include_spans=include_spans, max_chars=max_chars
    )


def handle_telemetry_summary(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    limit = int(args.get("limit", 20) or 20)
    max_chars = int(args.get("max_chars", 24000) or 24000)
    return summarize_telemetry(ctx.config.root, limit=limit, max_chars=max_chars)


def handle_compare_telemetry_runs(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return compare_telemetry_runs(
        ctx.config.root,
        str(args.get("baseline_run_id", "")),
        str(args.get("candidate_run_id", "")),
        max_chars=int(args.get("max_chars", 24000) or 24000),
    )


def handle_export_telemetry_bundle(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return export_telemetry_bundle(
        ctx.config.root,
        run_id=str(args.get("run_id", "")),
        max_chars=int(args.get("max_chars", 24000) or 24000),
        dry_run=bool(args.get("dry_run", ctx.config.dry_run)),
    )


def handle_list_model_prices(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    max_chars = int(args.get("max_chars", 24000) or 24000)
    return truncate(to_pretty_json({"prices": list_model_prices()}), max_chars)


def handle_optimization_dashboard(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_optimization_dashboard(
        ctx.config.root,
        limit=int(args.get("limit", 20) or 20),
        max_chars=int(args.get("max_chars", 24000) or 24000),
    )


def handle_failure_dashboard(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    max_chars = int(args.get("max_chars", 24000) or 24000)
    data = build_failure_taxonomy_dashboard(ctx.config.root, limit=int(args.get("limit", 20) or 20))
    return truncate(to_pretty_json(data), max_chars)


register_tools(
    [
        ToolSpec(
            "list_telemetry_runs",
            ACTION_SPECS["list_telemetry_runs"],
            handle_list_telemetry_runs,
            "observability",
            description="List saved local telemetry traces.",
        ),
        ToolSpec(
            "read_telemetry_run",
            ACTION_SPECS["read_telemetry_run"],
            handle_read_telemetry_run,
            "observability",
            description="Read a saved telemetry trace.",
        ),
        ToolSpec(
            "telemetry_summary",
            ACTION_SPECS["telemetry_summary"],
            handle_telemetry_summary,
            "observability",
            description="Summarize recent telemetry traces.",
        ),
        ToolSpec(
            "compare_telemetry_runs",
            ACTION_SPECS["compare_telemetry_runs"],
            handle_compare_telemetry_runs,
            "observability",
            description="Compare two telemetry traces.",
        ),
        ToolSpec(
            "export_telemetry_bundle",
            ACTION_SPECS["export_telemetry_bundle"],
            handle_export_telemetry_bundle,
            "observability",
            description="Export a compact telemetry review bundle.",
        ),
        ToolSpec(
            "list_model_prices",
            ACTION_SPECS["list_model_prices"],
            handle_list_model_prices,
            "observability",
            description="List local provider/model price defaults.",
        ),
        ToolSpec(
            "optimization_dashboard",
            ACTION_SPECS["optimization_dashboard"],
            handle_optimization_dashboard,
            "observability",
            description="Show eval/telemetry optimization dashboard.",
        ),
        ToolSpec(
            "failure_dashboard",
            ACTION_SPECS["failure_dashboard"],
            handle_failure_dashboard,
            "observability",
            description="Show failure taxonomy dashboard.",
        ),
    ]
)
