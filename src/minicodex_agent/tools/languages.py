"""Language/framework and semantic code intelligence tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.language_adapters import analyze_language_stack, suggest_verification_commands
from minicodex_agent.semantic_index import (
    build_semantic_index,
    find_symbol_references,
    inspect_routes,
    semantic_capability_report,
)
from minicodex_agent.test_ci import render_json
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.common import as_string_list
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.utils import truncate


def _bool_arg(args: Mapping[str, Any], name: str, default: bool = False) -> bool:
    value = args.get(name, default)
    return value if isinstance(value, bool) else default


def handle_detect_language_stack(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    report = analyze_language_stack(ctx.config.root, max_files=int(args.get("max_files", 1200)))
    return render_json(
        {"summary": "Language/framework stack detected.", "report": report.to_dict()}
    )


def handle_inspect_frameworks(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    report = analyze_language_stack(ctx.config.root, max_files=int(args.get("max_files", 1200)))
    frameworks = [framework for framework in report.to_dict()["frameworks"]]
    return render_json(
        {
            "summary": f"Detected {len(frameworks)} framework/tooling signal(s).",
            "frameworks": frameworks,
        }
    )


def handle_suggest_verification_commands(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    purposes = as_string_list(args, "purposes") or ["test", "typecheck", "lint", "build"]
    result = suggest_verification_commands(
        ctx.config.root,
        changed_files=as_string_list(args, "changed_files"),
        purposes=purposes,
        max_commands=int(args.get("max_commands", 8)),
    )
    return render_json(result)


def handle_language_adapter_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    report = analyze_language_stack(ctx.config.root, max_files=int(args.get("max_files", 1200)))
    max_chars = int(args.get("max_chars", ctx.config.max_observation_chars))
    return truncate(report.summary(), max_chars)


def handle_semantic_capability_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    max_chars = int(args.get("max_chars", ctx.config.max_observation_chars))
    return truncate(render_json(semantic_capability_report().to_dict()), max_chars)


def handle_build_semantic_index(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    max_chars = int(args.get("max_chars", ctx.config.max_observation_chars))
    index = build_semantic_index(
        ctx.config.root,
        max_files=int(args.get("max_files", 1600)),
        max_symbols=int(args.get("max_symbols", 1000)),
        max_references_per_symbol=int(args.get("max_references_per_symbol", 8)),
        include_routes=_bool_arg(args, "include_routes", True),
    )
    return truncate(
        render_json({"summary": "Semantic index built.", "index": index.to_dict()}), max_chars
    )


def handle_find_symbol_references(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    max_chars = int(args.get("max_chars", ctx.config.max_observation_chars))
    result = find_symbol_references(
        ctx.config.root,
        str(args.get("symbol", "")),
        language=str(args.get("language", "")),
        path=str(args.get("path", "")),
        max_matches=int(args.get("max_matches", 80)),
    )
    return truncate(render_json(result), max_chars)


def handle_inspect_routes(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    max_chars = int(args.get("max_chars", ctx.config.max_observation_chars))
    result = inspect_routes(
        ctx.config.root,
        framework=str(args.get("framework", "")),
        max_routes=int(args.get("max_routes", 120)),
    )
    return truncate(render_json(result), max_chars)


register_tools(
    [
        ToolSpec(
            "detect_language_stack",
            ACTION_SPECS["detect_language_stack"],
            handle_detect_language_stack,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "inspect_frameworks",
            ACTION_SPECS["inspect_frameworks"],
            handle_inspect_frameworks,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "suggest_verification_commands",
            ACTION_SPECS["suggest_verification_commands"],
            handle_suggest_verification_commands,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "language_adapter_report",
            ACTION_SPECS["language_adapter_report"],
            handle_language_adapter_report,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "semantic_capability_report",
            ACTION_SPECS["semantic_capability_report"],
            handle_semantic_capability_report,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "build_semantic_index",
            ACTION_SPECS["build_semantic_index"],
            handle_build_semantic_index,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "find_symbol_references",
            ACTION_SPECS["find_symbol_references"],
            handle_find_symbol_references,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "inspect_routes",
            ACTION_SPECS["inspect_routes"],
            handle_inspect_routes,
            plugin="code-intelligence",
            risk_level="low",
        ),
    ]
)
