"""Central ToolSpec registry and dispatch for MiniCodex tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .action_schema import ACTION_SPECS, ActionSpec
from .plugin_registry import check_tool_access
from .tools.context import ToolContext

ToolHandler = Callable[[ToolContext, Mapping[str, Any]], str]


@dataclass(frozen=True)
class ToolSpec:
    """Runtime description of a MiniCodex tool.

    The registry uses the same ActionSpec objects as model-action validation so
    prompt/help/schema views and execution stay aligned.
    """

    name: str
    schema: ActionSpec
    handler: ToolHandler
    plugin: str
    requires_approval: bool = False
    risk_level: str = "low"
    description: str = ""


_TOOL_REGISTRY: dict[str, ToolSpec] = {}
_MODULES_LOADED = False

UNTRUSTED_APPROVAL_ACTIONS: tuple[str, ...] = (
    "write_file",
    "replace_in_file",
    "apply_patch",
    "rename_symbol_semantic",
    "organize_imports",
    "cleanup_dead_code",
    "format_and_verify",
    "restore_snapshot",
    "run_command",
    "run_tests",
    "run_targeted_tests",
    "run_terminal_session",
    "create_github_pr",
    "create_github_issue",
    "create_github_review_comment",
    "execute_commit_push_workflow",
    "init_github_webhook_server",
    "generate_github_app_manifest",
    "init_github_action",
    "update_project_config",
    "update_project_policy",
)

TRUST_REQUIRED_WRITE_ACTIONS: tuple[str, ...] = (
    "write_file",
    "replace_in_file",
    "apply_patch",
    "rename_symbol_semantic",
    "organize_imports",
    "cleanup_dead_code",
    "format_and_verify",
    "restore_snapshot",
    "create_github_pr",
    "create_github_issue",
    "create_github_review_comment",
    "execute_commit_push_workflow",
    "init_github_webhook_server",
    "generate_github_app_manifest",
)


def register_tool(spec: ToolSpec) -> None:
    """Register one tool, rejecting duplicates and missing schemas."""

    if spec.name not in ACTION_SPECS:
        raise ValueError(f"Tool {spec.name!r} has no ActionSpec entry.")
    if spec.name in _TOOL_REGISTRY:
        raise ValueError(f"Tool {spec.name!r} is already registered.")
    _TOOL_REGISTRY[spec.name] = spec


def register_tools(specs: list[ToolSpec]) -> None:
    """Register multiple tools."""

    for spec in specs:
        register_tool(spec)


def _load_builtin_tool_modules() -> None:
    """Import built-in tool modules once so their ToolSpecs register."""

    global _MODULES_LOADED
    if _MODULES_LOADED:
        return

    # Imports are intentionally local to avoid cycles during package import.
    from .tools import (  # noqa: F401  # noqa: F401
        control,
        diagnostics,
        evals,
        filesystem,
        git,
        github,
        languages,
        long_horizon,
        memory,
        multi_agent,
        project,
        prompting,
        python_tools,
        quality,
        security,
        shell,
        skills,
        telemetry,
        testing,
        ux,
    )

    _MODULES_LOADED = True


def get_tool_registry() -> dict[str, ToolSpec]:
    """Return a copy of the complete tool registry."""

    _load_builtin_tool_modules()
    return dict(_TOOL_REGISTRY)


def get_tool_spec(name: str) -> ToolSpec | None:
    """Return the ToolSpec for one action name."""

    _load_builtin_tool_modules()
    return _TOOL_REGISTRY.get(name)


def dispatch_tool(ctx: ToolContext, action: str, args: Mapping[str, Any]) -> str:
    """Dispatch an action through plugin enforcement and the ToolSpec registry."""

    if not ctx.config.project_config_enabled:
        configured_plugins: tuple[str, ...] | None = ()
    else:
        configured_plugins = ctx.config.enabled_plugins or None
    access = check_tool_access(ctx.config.root, action, configured_plugins=configured_plugins)
    if not access.allowed:
        return "TOOL BLOCK: " + access.render()

    spec = get_tool_spec(action)
    if spec is None:
        return f"Bilinmeyen action: {action}"

    if (
        ctx.config.untrusted_workspace
        and ctx.config.approval == "auto"
        and action in UNTRUSTED_APPROVAL_ACTIONS
    ):
        return (
            "TOOL BLOCK: untrusted_workspace requires manual approval for "
            f"high-impact action '{action}'. Re-run with --approval ask, or disable "
            "untrusted workspace only after reviewing the repository."
        )

    if ctx.config.require_trusted_workspace_for_writes and action in TRUST_REQUIRED_WRITE_ACTIONS:
        return (
            "TOOL BLOCK: require_trusted_workspace_for_writes is enabled; "
            f"action '{action}' is blocked until the workspace is explicitly trusted."
        )

    return spec.handler(ctx, args)


def render_runtime_tool_reference(allowed_actions: Iterable[str] | None = None) -> str:
    """Render the executable tool registry for diagnostics/docs."""

    registry = get_tool_registry()
    allowed = set(allowed_actions) if allowed_actions is not None else None
    lines: list[str] = []
    for name in sorted(registry):
        if allowed is not None and name not in allowed:
            continue
        spec = registry[name]
        required = ", ".join(spec.schema.required) if spec.schema.required else "-"
        optional = ", ".join(spec.schema.optional) if spec.schema.optional else "-"
        lines.append(
            f"- {name} [{spec.plugin}/{spec.risk_level}]: "
            f"required=[{required}] optional=[{optional}] approval={spec.requires_approval}"
        )
    return "\n".join(lines)
