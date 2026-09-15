"""Security, rollback, and secret-scan tool handlers."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, cast

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.rollback_policy import check_rollback_policy
from minicodex_agent.safety import safe_resolve
from minicodex_agent.secret_scanner import Severity, scan_secrets
from minicodex_agent.security_audit import (
    render_dependency_audit,
    render_sast_scan,
    scan_repo_instructions,
    security_audit_report,
    validate_plugin_permissions,
    workspace_trust_report,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.utils import subprocess_text, truncate


def handle_scan_secrets(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    minimum_severity = str(args.get("minimum_severity", "low"))
    if minimum_severity not in {"low", "medium", "high", "critical"}:
        return "Invalid minimum_severity. Use one of: low, medium, high, critical."
    return scan_secrets(
        ctx.config.root,
        start_path=str(args.get("path", ".")),
        max_files=int(args.get("max_files", 1000)),
        max_bytes_per_file=int(args.get("max_bytes_per_file", 600000)),
        max_findings=int(args.get("max_findings", 100)),
        minimum_severity=cast(Severity, minimum_severity),
        max_chars=ctx.config.max_observation_chars,
    )


def _external_secret_command(tool: str, target: str) -> list[str]:
    if tool == "gitleaks":
        return ["gitleaks", "detect", "--source", target, "--no-git", "--redact"]
    if tool == "trufflehog":
        return ["trufflehog", "filesystem", target, "--no-update"]
    raise ValueError(f"Unsupported external secret scanner: {tool}")


def handle_run_external_secret_scan(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    requested = str(args.get("tool", "auto"))
    target = safe_resolve(ctx.config.root, str(args.get("path", ".")))
    timeout = int(args.get("timeout", 180))
    dry_run = bool(args.get("dry_run", ctx.config.dry_run))

    candidates = ["gitleaks", "trufflehog"] if requested == "auto" else [requested]
    selected = next((tool for tool in candidates if shutil.which(tool)), "")
    if not selected:
        return (
            "External secret scanner not available. Install gitleaks or trufflehog, "
            "or use the built-in scan_secrets tool for a lightweight preflight check."
        )

    command = _external_secret_command(selected, str(target))
    if dry_run:
        return "DRY-RUN external secret scan command:\n" + " ".join(command)

    try:
        completed = subprocess.run(
            command,
            cwd=str(ctx.config.root),
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout, 900)),
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return truncate(
            f"External secret scan timed out after {timeout}s.\n"
            f"STDOUT:\n{subprocess_text(exc.stdout)}\n"
            f"STDERR:\n{subprocess_text(exc.stderr)}",
            ctx.config.max_observation_chars,
        )
    except OSError as exc:
        return f"External secret scan failed to start: {exc}"

    output = (
        f"External secret scanner: {selected}\n"
        f"Exit code: {completed.returncode}\n\n"
        f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
    )
    return truncate(output, ctx.config.max_observation_chars)


def handle_check_rollback_policy(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return check_rollback_policy(
        ctx.config.root,
        max_changed_files=int(args.get("max_changed_files", 8)),
        max_diff_lines=int(args.get("max_diff_lines", 300)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_run_sast_scan(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    scanner = str(args.get("scanner", "auto"))
    if scanner not in {"auto", "semgrep", "builtin"}:
        return "Invalid scanner. Use one of: auto, semgrep, builtin."
    minimum_severity = str(args.get("minimum_severity", "medium"))
    if minimum_severity not in {"low", "medium", "high", "critical"}:
        return "Invalid minimum_severity. Use one of: low, medium, high, critical."
    dry_run = bool(args.get("dry_run", ctx.config.dry_run))
    return render_sast_scan(
        ctx.config.root,
        scanner=scanner,
        timeout=int(args.get("timeout", ctx.config.external_security_timeout_seconds)),
        dry_run=dry_run,
        max_files=int(args.get("max_files", ctx.config.security_audit_max_files)),
        minimum_severity=minimum_severity,
        max_chars=ctx.config.max_observation_chars,
    )


def handle_run_dependency_audit(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    dry_run = bool(args.get("dry_run", ctx.config.dry_run))
    return render_dependency_audit(
        ctx.config.root,
        timeout=int(args.get("timeout", ctx.config.external_security_timeout_seconds)),
        dry_run=dry_run,
        max_chars=ctx.config.max_observation_chars,
        allow_network=ctx.config.allow_network_commands,
    )


def handle_scan_repo_instructions(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return scan_repo_instructions(
        ctx.config.root,
        max_files=int(args.get("max_files", 200)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_validate_plugin_permissions(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return validate_plugin_permissions(ctx.config.root, max_chars=ctx.config.max_observation_chars)


def handle_workspace_trust_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return workspace_trust_report(
        ctx.config.root,
        untrusted_workspace=bool(args.get("untrusted_workspace", ctx.config.untrusted_workspace)),
        sandbox_mode=ctx.config.sandbox_mode,
        sandbox_network=ctx.config.sandbox_network,
        approval=ctx.config.approval,
        allow_network_commands=ctx.config.allow_network_commands,
        allow_github_api_writes=ctx.config.allow_github_api_writes,
        max_chars=ctx.config.max_observation_chars,
    )


def handle_security_audit_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return security_audit_report(
        ctx.config.root,
        untrusted_workspace=bool(args.get("untrusted_workspace", ctx.config.untrusted_workspace)),
        sandbox_mode=ctx.config.sandbox_mode,
        sandbox_network=ctx.config.sandbox_network,
        approval=ctx.config.approval,
        allow_network_commands=ctx.config.allow_network_commands,
        allow_github_api_writes=ctx.config.allow_github_api_writes,
        max_files=int(args.get("max_files", ctx.config.security_audit_max_files)),
        max_chars=ctx.config.security_audit_report_max_chars,
    )


register_tools(
    [
        ToolSpec(
            "scan_secrets", ACTION_SPECS["scan_secrets"], handle_scan_secrets, plugin="security"
        ),
        ToolSpec(
            "check_rollback_policy",
            ACTION_SPECS["check_rollback_policy"],
            handle_check_rollback_policy,
            plugin="security",
        ),
        ToolSpec(
            "run_external_secret_scan",
            ACTION_SPECS["run_external_secret_scan"],
            handle_run_external_secret_scan,
            plugin="security",
            risk_level="medium",
        ),
        ToolSpec(
            "run_sast_scan",
            ACTION_SPECS["run_sast_scan"],
            handle_run_sast_scan,
            plugin="security",
            risk_level="medium",
        ),
        ToolSpec(
            "run_dependency_audit",
            ACTION_SPECS["run_dependency_audit"],
            handle_run_dependency_audit,
            plugin="security",
            risk_level="medium",
        ),
        ToolSpec(
            "scan_repo_instructions",
            ACTION_SPECS["scan_repo_instructions"],
            handle_scan_repo_instructions,
            plugin="security",
        ),
        ToolSpec(
            "validate_plugin_permissions",
            ACTION_SPECS["validate_plugin_permissions"],
            handle_validate_plugin_permissions,
            plugin="security",
        ),
        ToolSpec(
            "workspace_trust_report",
            ACTION_SPECS["workspace_trust_report"],
            handle_workspace_trust_report,
            plugin="security",
        ),
        ToolSpec(
            "security_audit_report",
            ACTION_SPECS["security_audit_report"],
            handle_security_audit_report,
            plugin="security",
        ),
    ]
)
