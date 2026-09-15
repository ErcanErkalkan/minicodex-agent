"""Final readiness / quality-gate tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.quality_gate import (
    _render_prefixed_json,
    build_test_matrix_plan,
    clean_generated_artifacts,
    final_readiness_report,
    release_package_manifest,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.utils import to_pretty_json


def handle_final_readiness_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return final_readiness_report(
        ctx.config.root,
        include_cli_smoke=bool(args.get("include_cli_smoke", True)),
        include_test_matrix=bool(args.get("include_test_matrix", True)),
        include_security_audit=bool(args.get("include_security_audit", True)),
        include_verification_tools=bool(args.get("include_verification_tools", True)),
        run_test_matrix=bool(args.get("run_test_matrix", True)),
        test_matrix_max_files=int(args.get("test_matrix_max_files", 3)),
        test_matrix_timeout=int(args.get("test_matrix_timeout", 20)),
        test_matrix_group=str(args.get("test_matrix_group", "fast")),
        run_verification_tools=bool(args.get("run_verification_tools", False)),
        timeout=int(args.get("timeout", 45)),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_test_matrix_plan(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    plan = build_test_matrix_plan(
        ctx.config.root,
        per_file_timeout=int(args.get("per_file_timeout", 60)),
        group=str(args.get("group", "all")),
    )
    return _render_prefixed_json(
        "TEST_MATRIX_PLAN_JSON", plan, int(args.get("max_chars", ctx.config.max_observation_chars))
    )


def handle_release_package_manifest(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return release_package_manifest(
        ctx.config.root,
        from_zip=str(args.get("from_zip", "") or "") or None,
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_clean_generated_artifacts(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return to_pretty_json(
        clean_generated_artifacts(
            ctx.config.root,
            dry_run=bool(args.get("dry_run", False)),
            include_build_outputs=bool(args.get("include_build_outputs", True)),
        )
    )


register_tools(
    [
        ToolSpec(
            "final_readiness_report",
            ACTION_SPECS["final_readiness_report"],
            handle_final_readiness_report,
            plugin="quality-gates",
        ),
        ToolSpec(
            "test_matrix_plan",
            ACTION_SPECS["test_matrix_plan"],
            handle_test_matrix_plan,
            plugin="quality-gates",
        ),
        ToolSpec(
            "release_package_manifest",
            ACTION_SPECS["release_package_manifest"],
            handle_release_package_manifest,
            plugin="quality-gates",
        ),
        ToolSpec(
            "clean_generated_artifacts",
            ACTION_SPECS["clean_generated_artifacts"],
            handle_clean_generated_artifacts,
            plugin="quality-gates",
            risk_level="medium",
        ),
    ]
)
