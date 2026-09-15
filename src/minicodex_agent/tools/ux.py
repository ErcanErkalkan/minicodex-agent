"""Developer-experience tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.dev_experience import (
    create_review_bundle,
    export_ide_bridge,
    list_review_bundles,
    read_review_bundle,
    record_review_decision,
    render_run_summary,
    render_tui_panel,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def handle_render_tui_panel(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_tui_panel(
        ctx.config.root,
        goal=str(args.get("goal", ctx.state.goal)),
        max_diff_chars=int(args.get("max_diff_chars", ctx.config.max_observation_chars)),
    )


def handle_create_review_bundle(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    if not ctx.config.dry_run and not ctx.confirm("Change review bundle yazılacak."):
        return "Kullanıcı create_review_bundle işlemini reddetti."
    return create_review_bundle(
        ctx.config.root,
        title=str(args.get("title", "")),
        goal=str(args.get("goal", ctx.state.goal)),
        max_diff_chars=int(args.get("max_diff_chars", ctx.config.max_observation_chars)),
        dry_run=ctx.config.dry_run,
    )


def handle_list_review_bundles(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_review_bundles(ctx.config.root, limit=int(args.get("limit", 20)))


def handle_read_review_bundle(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_review_bundle(
        ctx.config.root,
        bundle_id=str(args.get("bundle_id", "")),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_record_review_decision(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return record_review_decision(
        ctx.config.root,
        bundle_id=str(args["bundle_id"]),
        decision=str(args["decision"]),
        note=str(args.get("note", "")),
        dry_run=ctx.config.dry_run,
    )


def handle_run_summary(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_run_summary(
        ctx.config.root,
        run_id=str(args.get("run_id", "")),
        limit=int(args.get("limit", 30)),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_export_ide_bridge(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    if not ctx.config.dry_run and not ctx.confirm("IDE bridge descriptor yazılacak."):
        return "Kullanıcı export_ide_bridge işlemini reddetti."
    return export_ide_bridge(
        ctx.config.root,
        output_path=str(args.get("output_path", ".minicodex/ide/bridge.json")),
        dry_run=ctx.config.dry_run,
    )


register_tools(
    [
        ToolSpec(
            "render_tui_panel",
            ACTION_SPECS["render_tui_panel"],
            handle_render_tui_panel,
            plugin="developer-ux",
        ),
        ToolSpec(
            "create_review_bundle",
            ACTION_SPECS["create_review_bundle"],
            handle_create_review_bundle,
            plugin="developer-ux",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "list_review_bundles",
            ACTION_SPECS["list_review_bundles"],
            handle_list_review_bundles,
            plugin="developer-ux",
        ),
        ToolSpec(
            "read_review_bundle",
            ACTION_SPECS["read_review_bundle"],
            handle_read_review_bundle,
            plugin="developer-ux",
        ),
        ToolSpec(
            "record_review_decision",
            ACTION_SPECS["record_review_decision"],
            handle_record_review_decision,
            plugin="developer-ux",
        ),
        ToolSpec(
            "run_summary", ACTION_SPECS["run_summary"], handle_run_summary, plugin="developer-ux"
        ),
        ToolSpec(
            "export_ide_bridge",
            ACTION_SPECS["export_ide_bridge"],
            handle_export_ide_bridge,
            plugin="developer-ux",
            requires_approval=True,
            risk_level="medium",
        ),
    ]
)
