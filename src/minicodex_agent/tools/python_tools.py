"""Python analysis and refactor tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.ast_patch_tools import (
    ast_patch_capability_report,
    cleanup_dead_code,
    detect_dead_code,
    format_and_verify,
    organize_imports,
    plan_semantic_edit,
    rename_symbol_semantic,
)
from minicodex_agent.ast_tools import find_python_symbol, inspect_python_ast
from minicodex_agent.code_search import build_dependency_graph, search_code
from minicodex_agent.refactor_tools import rename_python_symbol
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.common import as_string_list, ensure_write_allowed
from minicodex_agent.tools.context import ToolContext


def handle_search_code(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return search_code(
        ctx.config.root,
        query=str(args["query"]),
        start_path=str(args.get("path", ".")),
        max_matches=int(args.get("max_matches", 20)),
        context_lines=int(args.get("context_lines", 2)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_build_dependency_graph(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return build_dependency_graph(
        ctx.config.root,
        start_path=str(args.get("path", ".")),
        max_files=int(args.get("max_files", 300)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_inspect_python_ast(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return inspect_python_ast(
        ctx.config.root,
        user_path=str(args["path"]),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_find_python_symbol(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return find_python_symbol(
        ctx.config.root,
        symbol_name=str(args["symbol"]),
        start_path=str(args.get("path", ".")),
        max_matches=int(args.get("max_matches", 50)),
    )


def handle_rename_python_symbol(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    path = str(args.get("path", "."))
    preview_only = bool(args.get("preview_only", False))
    if not preview_only and not ctx.confirm(
        f"Python sembolü yeniden adlandırılacak: {args['old_name']} -> {args['new_name']}"
    ):
        return "Kullanıcı rename_python_symbol işlemini reddetti."
    snapshot_note = ""
    if not preview_only:
        snapshot_ok, snapshot_note = ctx.ensure_auto_snapshot_before_edit(
            "rename_python_symbol", path
        )
        if not snapshot_ok:
            return snapshot_note
    result = rename_python_symbol(
        ctx.config.root,
        old_name=str(args["old_name"]),
        new_name=str(args["new_name"]),
        start_path=path,
        max_files=int(args.get("max_files", 200)),
        preview_only=preview_only,
        dry_run=ctx.config.dry_run,
        max_chars=ctx.config.max_observation_chars,
    )
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


def handle_ast_patch_capability_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return ast_patch_capability_report(
        ctx.config.root, max_chars=int(args.get("max_chars", ctx.config.max_observation_chars))
    )


def handle_plan_semantic_edit(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return plan_semantic_edit(
        ctx.config.root,
        operation=str(args["operation"]),
        path=str(args.get("path", ".")),
        language=str(args.get("language", "")),
        symbol=str(args.get("symbol", "")),
        new_name=str(args.get("new_name", "")),
        max_files=int(args.get("max_files", 400)),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def _confirm_semantic_write(ctx: ToolContext, *, action: str, path: str, detail: str) -> str:
    policy_note = ensure_write_allowed(ctx, path)
    if policy_note and policy_note.startswith("POLICY BLOCK"):
        return policy_note
    if not ctx.confirm(f"AST-aware refactor uygulanacak: {detail}{policy_note or ''}"):
        return f"Kullanıcı {action} işlemini reddetti."
    snapshot_ok, snapshot_note = ctx.ensure_auto_snapshot_before_edit(action, path)
    if not snapshot_ok:
        return snapshot_note
    return snapshot_note


def handle_rename_symbol_semantic(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    path = str(args.get("path", "."))
    preview_only = bool(args.get("preview_only", True))
    snapshot_note = ""
    if not preview_only:
        snapshot_note = _confirm_semantic_write(
            ctx,
            action="rename_symbol_semantic",
            path=path,
            detail=f"{args['old_name']} -> {args['new_name']} ({args.get('language', 'auto')})",
        )
        if snapshot_note.startswith("POLICY BLOCK") or "reddetti" in snapshot_note:
            return snapshot_note
    result = rename_symbol_semantic(
        ctx.config.root,
        old_name=str(args["old_name"]),
        new_name=str(args["new_name"]),
        language=str(args.get("language", "")),
        path=path,
        max_files=int(args.get("max_files", 400)),
        preview_only=preview_only,
        dry_run=ctx.config.dry_run,
        max_chars=ctx.config.max_observation_chars,
    )
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


def handle_organize_imports(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    path = str(args.get("path", "."))
    preview_only = bool(args.get("preview_only", True))
    snapshot_note = ""
    if not preview_only:
        snapshot_note = _confirm_semantic_write(
            ctx, action="organize_imports", path=path, detail=f"organize imports under {path}"
        )
        if snapshot_note.startswith("POLICY BLOCK") or "reddetti" in snapshot_note:
            return snapshot_note
    result = organize_imports(
        ctx.config.root,
        path=path,
        language=str(args.get("language", "")),
        max_files=int(args.get("max_files", 400)),
        preview_only=preview_only,
        dry_run=ctx.config.dry_run,
        max_chars=ctx.config.max_observation_chars,
    )
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


def handle_detect_dead_code(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return detect_dead_code(
        ctx.config.root,
        language=str(args.get("language", "python")),
        path=str(args.get("path", ".")),
        include_public=bool(args.get("include_public", False)),
        max_files=int(args.get("max_files", 600)),
        max_candidates=int(args.get("max_candidates", 80)),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_cleanup_dead_code(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    path = str(args.get("path", "."))
    preview_only = bool(args.get("preview_only", True))
    snapshot_note = ""
    if not preview_only:
        snapshot_note = _confirm_semantic_write(
            ctx, action="cleanup_dead_code", path=path, detail=f"cleanup dead code under {path}"
        )
        if snapshot_note.startswith("POLICY BLOCK") or "reddetti" in snapshot_note:
            return snapshot_note
    result = cleanup_dead_code(
        ctx.config.root,
        names=tuple(as_string_list(args, "names")),
        path=path,
        include_public=bool(args.get("include_public", False)),
        max_files=int(args.get("max_files", 600)),
        preview_only=preview_only,
        dry_run=ctx.config.dry_run,
        max_chars=ctx.config.max_observation_chars,
    )
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


def handle_format_and_verify(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    path = str(args["path"])
    run_formatter = bool(args.get("run_formatter", False))
    snapshot_note = ""
    if run_formatter and not ctx.config.dry_run:
        snapshot_note = _confirm_semantic_write(
            ctx, action="format_and_verify", path=path, detail=f"formatter for {path}"
        )
        if snapshot_note.startswith("POLICY BLOCK") or "reddetti" in snapshot_note:
            return snapshot_note
    result = format_and_verify(
        ctx.config.root,
        path=path,
        formatter=str(args.get("formatter", "auto")),
        run_formatter=run_formatter,
        verify_syntax=bool(args.get("verify_syntax", True)),
        timeout=int(args.get("timeout", 60)),
        dry_run=ctx.config.dry_run,
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


register_tools(
    [
        ToolSpec(
            "search_code", ACTION_SPECS["search_code"], handle_search_code, plugin="diagnostics"
        ),
        ToolSpec(
            "build_dependency_graph",
            ACTION_SPECS["build_dependency_graph"],
            handle_build_dependency_graph,
            plugin="diagnostics",
        ),
        ToolSpec(
            "inspect_python_ast",
            ACTION_SPECS["inspect_python_ast"],
            handle_inspect_python_ast,
            plugin="diagnostics",
        ),
        ToolSpec(
            "find_python_symbol",
            ACTION_SPECS["find_python_symbol"],
            handle_find_python_symbol,
            plugin="diagnostics",
        ),
        ToolSpec(
            "rename_python_symbol",
            ACTION_SPECS["rename_python_symbol"],
            handle_rename_python_symbol,
            plugin="diagnostics",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "ast_patch_capability_report",
            ACTION_SPECS["ast_patch_capability_report"],
            handle_ast_patch_capability_report,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "plan_semantic_edit",
            ACTION_SPECS["plan_semantic_edit"],
            handle_plan_semantic_edit,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "rename_symbol_semantic",
            ACTION_SPECS["rename_symbol_semantic"],
            handle_rename_symbol_semantic,
            plugin="code-intelligence",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "organize_imports",
            ACTION_SPECS["organize_imports"],
            handle_organize_imports,
            plugin="code-intelligence",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "detect_dead_code",
            ACTION_SPECS["detect_dead_code"],
            handle_detect_dead_code,
            plugin="code-intelligence",
            risk_level="low",
        ),
        ToolSpec(
            "cleanup_dead_code",
            ACTION_SPECS["cleanup_dead_code"],
            handle_cleanup_dead_code,
            plugin="code-intelligence",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "format_and_verify",
            ACTION_SPECS["format_and_verify"],
            handle_format_and_verify,
            plugin="code-intelligence",
            requires_approval=True,
            risk_level="medium",
        ),
    ]
)
