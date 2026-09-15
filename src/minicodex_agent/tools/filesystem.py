"""Filesystem and patch tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.fs_tools import (
    glob_file_search,
    list_dir,
    list_files,
    preview_replace_in_file,
    read_file,
    read_file_range,
    replace_in_file,
    write_file,
)
from minicodex_agent.index_tools import index_project, read_many_files, rg_search, search_text
from minicodex_agent.patch_tools import (
    apply_unified_patch,
    render_patch_plan,
    validate_unified_patch,
    verify_unified_patch,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.common import ensure_patch_allowed, ensure_write_allowed
from minicodex_agent.tools.context import ToolContext


def handle_list_files(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_files(
        ctx.config.root,
        start_path=str(args.get("path", ".")),
        max_files=int(args.get("max_files", 200)),
    )


def handle_list_dir(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_dir(
        ctx.config.root,
        user_path=str(args.get("path", ".")),
        max_entries=int(args.get("max_entries", 200)),
    )


def handle_glob_file_search(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return glob_file_search(
        ctx.config.root,
        pattern=str(args["pattern"]),
        start_path=str(args.get("path", ".")),
        max_matches=int(args.get("max_matches", 200)),
    )


def handle_read_file(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_file(
        ctx.config.root,
        user_path=str(args["path"]),
        max_chars=int(args.get("max_chars", ctx.config.max_file_read_chars)),
    )


def handle_read_file_range(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_file_range(
        ctx.config.root,
        user_path=str(args["path"]),
        start_line=int(args.get("start_line", 1)),
        end_line=int(args["end_line"]) if "end_line" in args else None,
        max_chars=int(args.get("max_chars", ctx.config.max_file_read_chars)),
    )


def handle_read_many_files(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    paths = args.get("paths", [])
    if not isinstance(paths, list):
        return "read_many_files için paths liste olmalı."
    return read_many_files(
        ctx.config.root,
        paths=[str(path) for path in paths],
        max_chars_each=int(args.get("max_chars_each", 12000)),
    )


def handle_search_text(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return search_text(
        ctx.config.root,
        query=str(args["query"]),
        start_path=str(args.get("path", ".")),
        max_matches=int(args.get("max_matches", 50)),
    )


def handle_rg_search(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return rg_search(
        ctx.config.root,
        pattern=str(args["pattern"]),
        start_path=str(args.get("path", ".")),
        max_matches=int(args.get("max_matches", 80)),
        context_lines=int(args.get("context_lines", 0)),
        case_sensitive=bool(args.get("case_sensitive", False)),
    )


def handle_index_project(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return index_project(
        ctx.config.root,
        start_path=str(args.get("path", ".")),
        max_files=int(args.get("max_files", ctx.config.index_max_files)),
        max_file_chars=ctx.config.index_max_file_chars,
        save=bool(args.get("save", True)),
        dry_run=ctx.config.dry_run,
    )


def handle_write_file(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    path = str(args["path"])
    policy_note = ensure_write_allowed(ctx, path)
    if policy_note and policy_note.startswith("POLICY BLOCK"):
        return policy_note
    if not ctx.confirm(f"Dosya yazılacak/değiştirilecek: {path}{policy_note or ''}"):
        return f"Kullanıcı write_file işlemini reddetti: {path}"
    snapshot_ok, snapshot_note = ctx.ensure_auto_snapshot_before_edit("write_file", path)
    if not snapshot_ok:
        return snapshot_note
    result = write_file(ctx.config.root, path, str(args["content"]), dry_run=ctx.config.dry_run)
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


def handle_preview_replace_in_file(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return preview_replace_in_file(
        ctx.config.root,
        user_path=str(args["path"]),
        old=str(args["old"]),
        new=str(args["new"]),
        count=int(args.get("count", 1)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_replace_in_file(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    path = str(args["path"])
    policy_note = ensure_write_allowed(ctx, path)
    if policy_note and policy_note.startswith("POLICY BLOCK"):
        return policy_note
    if not ctx.confirm(f"Dosyada değişiklik yapılacak: {path}{policy_note or ''}"):
        return f"Kullanıcı replace_in_file işlemini reddetti: {path}"
    snapshot_ok, snapshot_note = ctx.ensure_auto_snapshot_before_edit("replace_in_file", path)
    if not snapshot_ok:
        return snapshot_note
    result = replace_in_file(
        ctx.config.root,
        user_path=path,
        old=str(args["old"]),
        new=str(args["new"]),
        count=int(args.get("count", 1)),
        dry_run=ctx.config.dry_run,
    )
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


def handle_plan_patch(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    patch = str(args["patch"])
    policy_note = ensure_patch_allowed(ctx, patch)
    if policy_note and policy_note.startswith("POLICY BLOCK"):
        return policy_note
    try:
        return render_patch_plan(
            ctx.config.root,
            patch_text=patch,
            fuzzy=bool(args.get("fuzzy", False)),
            max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
        )
    except ValueError as exc:
        return f"PATCH PLAN FAILED: {exc}"


def handle_verify_patch(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    patch = str(args["patch"])
    policy_note = ensure_patch_allowed(ctx, patch)
    if policy_note and policy_note.startswith("POLICY BLOCK"):
        return policy_note
    try:
        return verify_unified_patch(
            ctx.config.root,
            patch_text=patch,
            fuzzy=bool(args.get("fuzzy", False)),
            verify_python_syntax=bool(
                args.get("verify_python_syntax", ctx.config.patch_verify_python_syntax)
            ),
        )
    except ValueError as exc:
        return f"PATCH VERIFY FAILED: {exc}"


def handle_apply_patch(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    patch = str(args["patch"])
    policy_note = ensure_patch_allowed(ctx, patch)
    if policy_note and policy_note.startswith("POLICY BLOCK"):
        return policy_note

    # Validate and preview the full patch before asking for approval or taking
    # the automatic pre-edit snapshot. This prevents noisy snapshots for patches
    # that cannot be applied at all.
    try:
        preview = validate_unified_patch(
            ctx.config.root,
            patch_text=patch,
            fuzzy=bool(args.get("fuzzy", ctx.config.patch_fuzzy_apply)),
            max_chars=ctx.config.max_observation_chars,
        )
    except ValueError as exc:
        return f"PATCH VALIDATION FAILED: {exc}"

    if not ctx.confirm(
        f"Unified diff patch uygulanacak.{policy_note or ''}\n\nÖnizleme:\n{preview}"
    ):
        return "Kullanıcı apply_patch işlemini reddetti."
    snapshot_ok, snapshot_note = ctx.ensure_auto_snapshot_before_edit("apply_patch", "unified diff")
    if not snapshot_ok:
        return snapshot_note
    result = apply_unified_patch(
        ctx.config.root,
        patch_text=patch,
        dry_run=ctx.config.dry_run,
        max_chars=ctx.config.max_observation_chars,
        fuzzy=bool(args.get("fuzzy", ctx.config.patch_fuzzy_apply)),
        verify=bool(args.get("verify", ctx.config.patch_verify_after_apply)),
        verify_python_syntax=bool(
            args.get("verify_python_syntax", ctx.config.patch_verify_python_syntax)
        ),
    )
    return (snapshot_note + "\n\n" if snapshot_note else "") + result


register_tools(
    [
        ToolSpec("list_files", ACTION_SPECS["list_files"], handle_list_files, plugin="filesystem"),
        ToolSpec("list_dir", ACTION_SPECS["list_dir"], handle_list_dir, plugin="filesystem"),
        ToolSpec(
            "glob_file_search",
            ACTION_SPECS["glob_file_search"],
            handle_glob_file_search,
            plugin="filesystem",
        ),
        ToolSpec("read_file", ACTION_SPECS["read_file"], handle_read_file, plugin="filesystem"),
        ToolSpec(
            "read_file_range",
            ACTION_SPECS["read_file_range"],
            handle_read_file_range,
            plugin="filesystem",
        ),
        ToolSpec(
            "read_many_files",
            ACTION_SPECS["read_many_files"],
            handle_read_many_files,
            plugin="filesystem",
        ),
        ToolSpec(
            "search_text", ACTION_SPECS["search_text"], handle_search_text, plugin="filesystem"
        ),
        ToolSpec("rg_search", ACTION_SPECS["rg_search"], handle_rg_search, plugin="filesystem"),
        ToolSpec(
            "index_project",
            ACTION_SPECS["index_project"],
            handle_index_project,
            plugin="filesystem",
        ),
        ToolSpec(
            "write_file",
            ACTION_SPECS["write_file"],
            handle_write_file,
            plugin="filesystem",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "preview_replace_in_file",
            ACTION_SPECS["preview_replace_in_file"],
            handle_preview_replace_in_file,
            plugin="filesystem",
        ),
        ToolSpec("plan_patch", ACTION_SPECS["plan_patch"], handle_plan_patch, plugin="filesystem"),
        ToolSpec(
            "verify_patch", ACTION_SPECS["verify_patch"], handle_verify_patch, plugin="filesystem"
        ),
        ToolSpec(
            "replace_in_file",
            ACTION_SPECS["replace_in_file"],
            handle_replace_in_file,
            plugin="filesystem",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "apply_patch",
            ACTION_SPECS["apply_patch"],
            handle_apply_patch,
            plugin="filesystem",
            requires_approval=True,
            risk_level="high",
        ),
    ]
)
