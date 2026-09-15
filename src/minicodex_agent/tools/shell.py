"""Shell, test, and terminal-session tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.project_inspector import choose_test_command
from minicodex_agent.project_policy import evaluate_command, read_effective_project_policy
from minicodex_agent.safety import assess_command_safety
from minicodex_agent.terminal_session import list_terminal_sessions, run_terminal_session
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.common import run_checked_command
from minicodex_agent.tools.context import ToolContext


def handle_run_command(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return run_checked_command(
        ctx,
        str(args["command"]),
        timeout=int(args.get("timeout", 60)),
        dry_run_label="komut çalıştırılmadı",
        reject_label="run_command işlemini",
    )


def handle_run_tests(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    command = str(args.get("command") or "").strip()
    if not command:
        chosen = choose_test_command(ctx.state.project_profile, ctx.config.test_command)
        if not chosen:
            return "Test komutu otomatik bulunamadı. Önce proje dosyalarını incele."
        command = chosen
    return run_checked_command(
        ctx,
        command,
        timeout=int(args.get("timeout", 120)),
        dry_run_label="test komutu çalıştırılmadı",
        reject_label="test komutunu",
    )


def handle_run_terminal_session(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    commands = args.get("commands", [])
    if not isinstance(commands, list):
        return "run_terminal_session için commands liste olmalı."
    command_list = [str(command) for command in commands]
    needs_manual = False
    notes: list[str] = []
    for command in command_list:
        safety_decision = assess_command_safety(
            command,
            profile=ctx.config.safety_profile,
            allow_network=ctx.config.allow_network_commands,
        )
        if not safety_decision.allowed:
            return "COMMAND BLOCK: " + safety_decision.render()
        if safety_decision.requires_manual_approval:
            needs_manual = True
            notes.append("Safety: " + safety_decision.render())
    if ctx.config.project_policy_enabled:
        policy = read_effective_project_policy(
            ctx.config.root, ctx.config.policy_file, ctx.config.enabled_plugins
        )
        for command in command_list:
            decision = evaluate_command(ctx.config.root, command, policy)
            if not decision.allowed:
                return "POLICY BLOCK: " + decision.render()
            if decision.requires_extra_approval:
                needs_manual = True
                notes.append("Policy: " + decision.render())
    if needs_manual and ctx.config.auto_approve:
        return "MANUAL APPROVAL REQUIRED: " + " | ".join(notes)
    if not ctx.config.dry_run and not ctx.confirm(
        "Birden fazla terminal komutu sırayla çalıştırılacak.\n" + "\n".join(notes),
        force_manual=needs_manual,
    ):
        return "Kullanıcı run_terminal_session işlemini reddetti."
    return run_terminal_session(
        ctx.config.root,
        command_list,
        profile=ctx.config.safety_profile,
        timeout_each=int(args.get("timeout_each", 60)),
        max_commands=int(args.get("max_commands", 8)),
        dry_run=ctx.config.dry_run,
        max_chars=ctx.config.max_observation_chars,
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


def handle_list_terminal_sessions(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_terminal_sessions(ctx.config.root, limit=int(args.get("limit", 10)))


register_tools(
    [
        ToolSpec(
            "run_command",
            ACTION_SPECS["run_command"],
            handle_run_command,
            plugin="execution",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "run_tests",
            ACTION_SPECS["run_tests"],
            handle_run_tests,
            plugin="execution",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "run_terminal_session",
            ACTION_SPECS["run_terminal_session"],
            handle_run_terminal_session,
            plugin="execution",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "list_terminal_sessions",
            ACTION_SPECS["list_terminal_sessions"],
            handle_list_terminal_sessions,
            plugin="execution",
        ),
    ]
)
