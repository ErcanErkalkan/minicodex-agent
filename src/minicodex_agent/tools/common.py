"""Shared helpers for MiniCodex tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.project_policy import (
    evaluate_command,
    evaluate_patch_paths,
    evaluate_write_path,
    read_effective_project_policy,
)
from minicodex_agent.safety import assess_command_safety
from minicodex_agent.shell_tools import run_command
from minicodex_agent.tools.context import ToolContext


def ensure_write_allowed(ctx: ToolContext, path: str) -> str | None:
    """Return a policy note or a POLICY BLOCK string for a write path."""

    if not ctx.config.project_policy_enabled:
        return ""
    decision = evaluate_write_path(
        ctx.config.root,
        path,
        read_effective_project_policy(
            ctx.config.root, ctx.config.policy_file, ctx.config.enabled_plugins
        ),
    )
    if not decision.allowed:
        return "POLICY BLOCK: " + decision.render()
    if decision.requires_extra_approval:
        return "\nPolicy note: " + decision.render()
    return ""


def ensure_patch_allowed(ctx: ToolContext, patch_text: str) -> str | None:
    """Return a policy note or a POLICY BLOCK string for a patch."""

    if not ctx.config.project_policy_enabled:
        return ""
    decision = evaluate_patch_paths(
        ctx.config.root,
        patch_text,
        read_effective_project_policy(
            ctx.config.root, ctx.config.policy_file, ctx.config.enabled_plugins
        ),
    )
    if not decision.allowed:
        return "POLICY BLOCK: " + decision.render()
    if decision.requires_extra_approval:
        return "\nPolicy note: " + decision.render()
    return ""


def run_checked_command(
    ctx: ToolContext,
    command: str,
    *,
    timeout: int,
    dry_run_label: str,
    reject_label: str,
) -> str:
    """Apply safety/policy/manual-approval checks and run one command."""

    safety_decision = assess_command_safety(
        command,
        profile=ctx.config.safety_profile,
        allow_network=ctx.config.allow_network_commands,
    )
    if not safety_decision.allowed:
        return "COMMAND BLOCK: " + safety_decision.render()

    needs_manual = safety_decision.requires_manual_approval
    notes = ["Safety: " + safety_decision.render()]

    if ctx.config.project_policy_enabled:
        decision = evaluate_command(
            ctx.config.root,
            command,
            read_effective_project_policy(
                ctx.config.root, ctx.config.policy_file, ctx.config.enabled_plugins
            ),
        )
        if not decision.allowed:
            return "POLICY BLOCK: " + decision.render()
        if decision.requires_extra_approval:
            needs_manual = True
            notes.append("Policy: " + decision.render())

    risk = safety_decision.risk
    if needs_manual and ctx.config.auto_approve:
        return "MANUAL APPROVAL REQUIRED: " + " | ".join(notes)
    if ctx.config.dry_run:
        return f"DRY-RUN: {dry_run_label}. Risk: {risk}\nKomut: {command}\n" + "\n".join(notes)
    if not ctx.confirm(
        f"Komut çalıştırılacak:\n{command}\nRisk: {risk}\n" + "\n".join(notes),
        force_manual=needs_manual,
    ):
        return f"Kullanıcı {reject_label} reddetti: {command}"

    return run_command(
        ctx.config.root,
        command=command,
        timeout=timeout,
        max_chars=ctx.config.max_observation_chars,
        profile=ctx.config.safety_profile,
        allow_network=ctx.config.allow_network_commands,
        sandbox_mode=ctx.config.sandbox_mode,
        sandbox_image=ctx.config.sandbox_image,
        sandbox_network=ctx.config.sandbox_network,
        sandbox_cpus=ctx.config.sandbox_cpus,
        sandbox_memory=ctx.config.sandbox_memory,
        sandbox_pids_limit=ctx.config.sandbox_pids_limit,
        sandbox_workspace_mode=ctx.config.sandbox_workspace_mode,
        sandbox_keep_workspace=ctx.config.sandbox_keep_workspace,
        sandbox_max_file_bytes=ctx.config.sandbox_max_file_bytes,
    )


def as_string_list(args: Mapping[str, Any], key: str) -> list[str] | None:
    """Extract a list[str] argument, returning None if it is not a list."""

    value = args.get(key, [])
    if not isinstance(value, list):
        return None
    return [str(item) for item in value]
