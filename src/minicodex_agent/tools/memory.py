"""Snapshot, task memory, and queue tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.commit_tools import generate_commit_message
from minicodex_agent.snapshot_tools import create_snapshot, list_snapshots, restore_snapshot
from minicodex_agent.task_memory import read_task_memory, save_task_memory
from minicodex_agent.task_queue import (
    dequeue_next_task,
    enqueue_task,
    list_task_queue,
    update_task_status,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def handle_create_snapshot(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    dry_run = ctx.config.dry_run
    if not dry_run and not ctx.confirm("Yerel geri dönüş snapshot'ı oluşturulacak."):
        return "Kullanıcı create_snapshot işlemini reddetti."
    result = create_snapshot(
        ctx.config.root,
        label=str(args.get("label", "manual")),
        max_files=int(args.get("max_files", 1000)),
        max_bytes_per_file=int(args.get("max_bytes_per_file", 500000)),
        dry_run=dry_run,
    )
    ctx.mark_auto_snapshot_handled()
    return result


def handle_list_snapshots(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_snapshots(ctx.config.root, limit=int(args.get("limit", 20)))


def handle_restore_snapshot(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    dry_run = bool(args.get("dry_run", ctx.config.dry_run))
    if not dry_run and not ctx.confirm(f"Snapshot geri yüklenecek: {args['snapshot_id']}"):
        return "Kullanıcı restore_snapshot işlemini reddetti."
    return restore_snapshot(
        ctx.config.root,
        snapshot_id=str(args["snapshot_id"]),
        dry_run=dry_run,
        create_restore_backup=bool(args.get("create_restore_backup", True)),
    )


def handle_read_task_memory(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_task_memory(
        ctx.config.root,
        limit=int(args.get("limit", 10)),
        query=str(args.get("query", "")),
    )


def handle_save_task_memory(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    changed_files = args.get("changed_files", [])
    checks_run = args.get("checks_run", [])
    if not isinstance(changed_files, list):
        changed_files = []
    if not isinstance(checks_run, list):
        checks_run = []
    return save_task_memory(
        ctx.config.root,
        goal=ctx.state.goal,
        summary=str(args["summary"]),
        changed_files=[str(path) for path in changed_files],
        checks_run=[str(check) for check in checks_run],
        success=bool(args.get("success", True)),
        dry_run=ctx.config.dry_run,
    )


def handle_generate_commit_message(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return generate_commit_message(
        ctx.config.root,
        goal=str(args.get("goal", ctx.state.goal)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_enqueue_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return enqueue_task(
        ctx.config.root,
        title=str(args["title"]),
        details=str(args.get("details", "")),
        priority=str(args.get("priority", "normal")),
        dry_run=ctx.config.dry_run,
    )


def handle_list_task_queue(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_task_queue(
        ctx.config.root,
        status=str(args.get("status", "")),
        limit=int(args.get("limit", 20)),
    )


def handle_update_task_status(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return update_task_status(
        ctx.config.root,
        task_id=str(args["task_id"]),
        status=str(args["status"]),
        note=str(args.get("note", "")),
        dry_run=ctx.config.dry_run,
    )


def handle_dequeue_next_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return dequeue_next_task(ctx.config.root, dry_run=ctx.config.dry_run)


register_tools(
    [
        ToolSpec(
            "create_snapshot",
            ACTION_SPECS["create_snapshot"],
            handle_create_snapshot,
            plugin="memory",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "list_snapshots", ACTION_SPECS["list_snapshots"], handle_list_snapshots, plugin="memory"
        ),
        ToolSpec(
            "restore_snapshot",
            ACTION_SPECS["restore_snapshot"],
            handle_restore_snapshot,
            plugin="memory",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "read_task_memory",
            ACTION_SPECS["read_task_memory"],
            handle_read_task_memory,
            plugin="memory",
        ),
        ToolSpec(
            "save_task_memory",
            ACTION_SPECS["save_task_memory"],
            handle_save_task_memory,
            plugin="memory",
        ),
        ToolSpec(
            "generate_commit_message",
            ACTION_SPECS["generate_commit_message"],
            handle_generate_commit_message,
            plugin="memory",
        ),
        ToolSpec(
            "enqueue_task", ACTION_SPECS["enqueue_task"], handle_enqueue_task, plugin="memory"
        ),
        ToolSpec(
            "list_task_queue",
            ACTION_SPECS["list_task_queue"],
            handle_list_task_queue,
            plugin="memory",
        ),
        ToolSpec(
            "update_task_status",
            ACTION_SPECS["update_task_status"],
            handle_update_task_status,
            plugin="memory",
        ),
        ToolSpec(
            "dequeue_next_task",
            ACTION_SPECS["dequeue_next_task"],
            handle_dequeue_next_task,
            plugin="memory",
        ),
    ]
)
