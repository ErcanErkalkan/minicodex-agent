"""Plugin registry for built-in and local JSON plugin manifests.

MiniCodex keeps plugin execution intentionally conservative: local
manifests can declare tool groups, prompts, policy hints, and metadata, but they
cannot inject arbitrary Python code. This gives teams a reviewable plugin layer
without turning the agent into an untrusted code runner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .action_schema import ACTION_SPECS
from .project_settings import read_project_config
from .utils import to_pretty_json, truncate

PLUGIN_DIR = Path(".minicodex/plugins")


@dataclass(frozen=True)
class PluginInfo:
    """Metadata for a MiniCodex plugin manifest."""

    name: str
    version: str
    description: str
    tools: tuple[str, ...]
    source: str
    prompts: tuple[str, ...] = ()
    policies: dict[str, Any] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize plugin metadata."""

        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tools": list(self.tools),
            "prompts": list(self.prompts),
            "policies": self.policies,
            "permissions": list(self.permissions),
            "source": self.source,
        }


@dataclass(frozen=True)
class ToolAccessDecision:
    """Result of resolving whether a model action is enabled by plugins."""

    allowed: bool
    action: str
    reason: str
    enabled_plugins: tuple[str, ...] = ()

    def render(self) -> str:
        """Return a readable one-line decision."""

        status = "allowed" if self.allowed else "blocked"
        plugins = ", ".join(self.enabled_plugins) if self.enabled_plugins else "<all/default>"
        return f"{status}: {self.reason}; enabled_plugins={plugins}"


# These are control-flow actions rather than project tools. They must remain
# available so the agent can ask for help, maintain a plan, and terminate even
# when a project intentionally enables a very small plugin set.
CONTROL_ACTIONS: tuple[str, ...] = ("ask_user", "finish", "update_plan")


BUILTIN_PLUGINS: tuple[PluginInfo, ...] = (
    PluginInfo(
        name="filesystem",
        version="1.0",
        description="Workspace-safe file listing, reading, writing, previewing, and patching tools.",
        tools=(
            "list_files",
            "list_dir",
            "glob_file_search",
            "read_file",
            "read_file_range",
            "read_many_files",
            "write_file",
            "replace_in_file",
            "preview_replace_in_file",
            "plan_patch",
            "verify_patch",
            "apply_patch",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="code-intelligence",
        version="1.0",
        description="Project indexing, semantic code intelligence, language/framework analysis, AST-aware refactor helpers, and safe rename tools.",
        tools=(
            "index_project",
            "search_text",
            "rg_search",
            "search_code",
            "build_code_map",
            "build_dependency_graph",
            "detect_language_stack",
            "inspect_frameworks",
            "suggest_verification_commands",
            "language_adapter_report",
            "semantic_capability_report",
            "build_semantic_index",
            "find_symbol_references",
            "inspect_routes",
            "inspect_python_ast",
            "find_python_symbol",
            "rename_python_symbol",
            "ast_patch_capability_report",
            "plan_semantic_edit",
            "rename_symbol_semantic",
            "organize_imports",
            "detect_dead_code",
            "cleanup_dead_code",
            "format_and_verify",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="git-and-release",
        version="1.2",
        description="Git status/diff, PR/issue preparation, GitHub App/webhook scaffolding, Actions CI fetch, artifact upload, review comment resolution, commit/push workflow, and rollback checks.",
        tools=(
            "git_status",
            "git_diff",
            "prepare_pr_summary",
            "detect_github_workflows",
            "init_github_action",
            "parse_pr_comment_command",
            "prepare_commit_push_plan",
            "summarize_github_ci_log",
            "github_ci_fetch_preview",
            "generate_github_app_manifest",
            "init_github_webhook_server",
            "fetch_github_ci_log",
            "execute_commit_push_workflow",
            "resolve_review_comments",
            "prepare_github_artifact_upload",
            "create_github_review_comment",
            "prepare_github_pr",
            "prepare_github_issue",
            "create_github_pr",
            "create_github_issue",
            "generate_commit_message",
            "check_rollback_policy",
            "review_change_set",
            "record_change_approval",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="security",
        version="1.0",
        description="Product-level local security audits: secrets, SAST, dependency audit planning, repo-instruction injection checks, plugin permissions, and workspace trust gates.",
        tools=(
            "scan_secrets",
            "run_external_secret_scan",
            "run_sast_scan",
            "run_dependency_audit",
            "scan_repo_instructions",
            "validate_plugin_permissions",
            "workspace_trust_report",
            "security_audit_report",
        ),
        source="builtin",
        permissions=("security:audit",),
    ),
    PluginInfo(
        name="workflow",
        version="1.0",
        description="Task memory, task queue, snapshots, secret scanning, settings, providers, and terminal sessions.",
        tools=(
            "create_snapshot",
            "list_snapshots",
            "restore_snapshot",
            "read_task_memory",
            "save_task_memory",
            "enqueue_task",
            "list_task_queue",
            "dequeue_next_task",
            "update_task_status",
            "scan_secrets",
            "run_external_secret_scan",
            "run_terminal_session",
            "list_terminal_sessions",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="onboarding",
        version="1.1",
        description="Setup wizard, demo project generation, health reports, final readiness, and release-readiness helpers.",
        tools=(
            "run_setup_wizard",
            "create_demo_project",
            "project_health_report",
            "final_readiness_report",
            "test_matrix_plan",
            "release_package_manifest",
            "clean_generated_artifacts",
            "release_checklist",
            "write_release_notes",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="quality-gates",
        version="1.0",
        description="Final project readiness, deterministic test matrix planning, and release package cleanliness reports.",
        tools=(
            "final_readiness_report",
            "test_matrix_plan",
            "release_package_manifest",
            "clean_generated_artifacts",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="policy",
        version="1.0",
        description="Project-local config and policy inspection/enforcement tools.",
        tools=(
            "init_project_config",
            "read_project_config",
            "update_project_config",
            "init_project_policy",
            "read_project_policy",
            "update_project_policy",
            "check_project_policy",
            "validate_plugins",
            "enabled_tools",
            "inspect_plugin",
            "list_providers",
            "list_plugins",
            "tool_help",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="skills",
        version="1.0",
        description="Repo-local AGENTS.md and .minicodex/skills progressive-disclosure workflow tools.",
        tools=("list_skills", "read_skill", "validate_skills", "init_skill"),
        source="builtin",
    ),
    PluginInfo(
        name="execution",
        version="1.1",
        description="Bounded command execution, targeted test planning/runs, and failure analysis tools.",
        tools=("run_command", "run_tests", "plan_tests", "run_targeted_tests", "analyze_failure"),
        source="builtin",
    ),
    PluginInfo(
        name="diagnostics",
        version="1.1",
        description="Project inspection, task decomposition, config validation, test/CI classification, and patch-failure diagnostics.",
        tools=(
            "inspect_project",
            "decompose_task",
            "validate_config",
            "classify_test_failure",
            "summarize_ci_log",
            "detect_flaky_tests",
            "diagnose_patch_failure",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="long-horizon",
        version="1.0",
        description="Long-running task state with acceptance criteria, milestones, checkpoints, and resume packs.",
        tools=(
            "create_long_task",
            "list_long_tasks",
            "read_long_task",
            "resume_long_task",
            "update_acceptance_criteria",
            "create_checkpoint",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="multi-agent",
        version="1.1",
        description="Bounded local subagent threads with role isolation, mailbox handoffs, result merging, plus legacy task-batch bookkeeping.",
        tools=(
            "plan_multi_agent_work",
            "plan_subagent_threads",
            "run_multi_agent_work",
            "run_subagent_threads",
            "list_multi_agent_runs",
            "read_multi_agent_run",
            "run_task_batch",
            "list_agent_batches",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="developer-ux",
        version="1.0",
        description="Terminal developer panel, review bundles, run summaries, and IDE bridge descriptors.",
        tools=(
            "render_tui_panel",
            "create_review_bundle",
            "list_review_bundles",
            "read_review_bundle",
            "record_review_decision",
            "run_summary",
            "export_ide_bridge",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="prompting",
        version="1.0",
        description="Modular prompt profiles, prompt preview, and prompt contract validation helpers.",
        tools=(
            "list_prompt_profiles",
            "render_prompt_bundle",
            "validate_prompt_contract",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="observability",
        version="1.0",
        description="Local trace/span telemetry, token/cost ledgers, risk events, and run comparison helpers.",
        tools=(
            "list_telemetry_runs",
            "read_telemetry_run",
            "telemetry_summary",
            "compare_telemetry_runs",
            "export_telemetry_bundle",
            "list_model_prices",
            "optimization_dashboard",
            "failure_dashboard",
        ),
        source="builtin",
    ),
    PluginInfo(
        name="evals",
        version="1.0",
        description="Deterministic benchmark tasks, provider/model baseline manifests, disposable eval workspaces, scoring, and run comparison tools.",
        tools=(
            "init_eval_suite",
            "init_eval_baselines",
            "list_eval_tasks",
            "list_eval_baselines",
            "eval_coverage_report",
            "eval_baseline_plan",
            "compare_eval_baselines",
            "read_eval_task",
            "run_eval_task",
            "run_eval_suite",
            "list_eval_runs",
            "read_eval_run",
            "compare_eval_runs",
            "run_prompt_ab_comparison",
        ),
        source="builtin",
    ),
)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def validate_plugin_manifest_data(data: dict[str, Any], source: str = "<memory>") -> list[str]:
    """Return validation errors for a plugin manifest dictionary."""

    errors: list[str] = []
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name must be a non-empty string")
    if "version" in data and not isinstance(data.get("version"), str):
        errors.append("version must be a string when provided")
    if "description" in data and not isinstance(data.get("description"), str):
        errors.append("description must be a string when provided")
    tools = data.get("tools", [])
    if not isinstance(tools, list):
        errors.append("tools must be a list")
    else:
        for tool in tools:
            if not isinstance(tool, str):
                errors.append("each tool must be a string")
            elif tool not in ACTION_SPECS:
                errors.append(f"unknown tool in {source}: {tool}")
    prompts = data.get("prompts", [])
    if prompts and not isinstance(prompts, list):
        errors.append("prompts must be a list when provided")
    policies = data.get("policies", {})
    if policies and not isinstance(policies, dict):
        errors.append("policies must be an object when provided")
    permissions = data.get("permissions", [])
    if permissions and not isinstance(permissions, list):
        errors.append("permissions must be a list when provided")
    elif isinstance(permissions, list):
        for permission in permissions:
            if not isinstance(permission, str):
                errors.append("each permission must be a string")
    return errors


def _plugin_from_manifest(path: Path, data: dict[str, Any]) -> PluginInfo:
    name = str(data.get("name") or path.stem)
    version = str(data.get("version") or "0.1")
    description = str(data.get("description") or "Local plugin manifest")
    tools = tuple(_as_str_list(data.get("tools")))
    prompts = tuple(_as_str_list(data.get("prompts")))
    policies = data.get("policies", {})
    if not isinstance(policies, dict):
        policies = {}
    permissions = tuple(_as_str_list(data.get("permissions")))
    return PluginInfo(
        name=name,
        version=version,
        description=description,
        tools=tools,
        prompts=prompts,
        policies=policies,
        permissions=permissions,
        source=str(path),
    )


def list_plugin_infos(root: Path, include_invalid: bool = True) -> list[PluginInfo]:
    """Return built-in plugins plus local JSON plugin manifests.

    Invalid tool names are kept visible for diagnostics; validate_plugin_manifests
    reports them explicitly, and list_enabled_tools ignores unknown tools.
    """

    plugins = list(BUILTIN_PLUGINS)
    plugin_dir = root / PLUGIN_DIR
    if not plugin_dir.exists():
        return plugins
    for path in sorted(plugin_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        errors = validate_plugin_manifest_data(raw, str(path))
        if errors and not include_invalid:
            continue
        plugins.append(_plugin_from_manifest(path, raw))
    return plugins


def validate_plugin_manifests(root: Path) -> str:
    """Validate all local plugin manifests and render a report."""

    plugin_dir = root / PLUGIN_DIR
    if not plugin_dir.exists():
        return "No local plugin directory found: .minicodex/plugins"

    reports: list[dict[str, Any]] = []
    for path in sorted(plugin_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            reports.append(
                {"path": str(path.relative_to(root)), "valid": False, "errors": [str(exc)]}
            )
            continue
        except OSError as exc:
            reports.append(
                {"path": str(path.relative_to(root)), "valid": False, "errors": [str(exc)]}
            )
            continue
        if not isinstance(raw, dict):
            reports.append(
                {
                    "path": str(path.relative_to(root)),
                    "valid": False,
                    "errors": ["manifest must be an object"],
                }
            )
            continue
        errors = validate_plugin_manifest_data(raw, str(path.relative_to(root)))
        reports.append({"path": str(path.relative_to(root)), "valid": not errors, "errors": errors})

    return "Plugin validation report:\n" + to_pretty_json(reports)


def enabled_plugin_names(
    root: Path, configured: list[str] | tuple[str, ...] | None = None
) -> list[str]:
    """Return project-configured enabled plugin names.

    Missing/empty enabled_plugins means all plugins are visible. Runtime
    callers may pass an already-applied config value so --no-project-config or
    CLI/project-config precedence is respected consistently.
    """

    if configured is not None:
        return _as_str_list(list(configured))
    config = read_project_config(root)
    names = config.get("enabled_plugins", [])
    return _as_str_list(names)


def list_active_plugin_infos(
    root: Path, configured: list[str] | tuple[str, ...] | None = None
) -> list[PluginInfo]:
    """Return valid plugins that are active under enabled_plugins.

    Empty enabled_plugins means all valid plugins are active. A non-empty list is
    an allow-list: unmatched names intentionally result in fewer/no project
    tools instead of falling back to every action.
    """

    enabled = set(enabled_plugin_names(root, configured))
    plugins = list_plugin_infos(root, include_invalid=False)
    if not enabled:
        return plugins
    return [plugin for plugin in plugins if plugin.name in enabled]


def list_active_plugin_policies(
    root: Path, configured: list[str] | tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Return policy blocks from currently active plugin manifests."""

    policies: list[dict[str, Any]] = []
    for plugin in list_active_plugin_infos(root, configured):
        if plugin.policies:
            policies.append(dict(plugin.policies))
    return policies


def list_enabled_tools(
    root: Path,
    *,
    include_control: bool = True,
    configured: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Return the union of tools exposed by active plugins."""

    tools: set[str] = set(CONTROL_ACTIONS if include_control else ())
    for plugin in list_active_plugin_infos(root, configured):
        tools.update(tool for tool in plugin.tools if tool in ACTION_SPECS)
    return sorted(tools)


def check_tool_access(
    root: Path, action: str, *, configured_plugins: list[str] | tuple[str, ...] | None = None
) -> ToolAccessDecision:
    """Return whether action is enabled by project plugin configuration."""

    if action in CONTROL_ACTIONS:
        return ToolAccessDecision(True, action, "control action is always available")
    if action not in ACTION_SPECS:
        return ToolAccessDecision(False, action, "unknown MiniCodex action")

    enabled_plugins = tuple(
        plugin.name for plugin in list_active_plugin_infos(root, configured_plugins)
    )
    enabled_tools = set(
        list_enabled_tools(root, include_control=False, configured=configured_plugins)
    )
    if action in enabled_tools:
        return ToolAccessDecision(
            True, action, f"tool '{action}' is exposed by an active plugin", enabled_plugins
        )

    configured = enabled_plugin_names(root, configured_plugins)
    if configured:
        reason = f"tool '{action}' is not exposed by enabled_plugins"
    else:
        reason = f"tool '{action}' is not exposed by any valid plugin"
    return ToolAccessDecision(False, action, reason, enabled_plugins)


def is_tool_enabled(
    root: Path, action: str, *, configured_plugins: list[str] | tuple[str, ...] | None = None
) -> bool:
    """Return True when action is enabled by active plugins or is control-flow."""

    return check_tool_access(root, action, configured_plugins=configured_plugins).allowed


def render_enabled_tools(root: Path) -> str:
    """Render tools exposed after project plugin filtering."""

    return "Enabled MiniCodex tools:\n" + to_pretty_json(list_enabled_tools(root))


def inspect_plugin(root: Path, name: str) -> str:
    """Render one plugin manifest by name."""

    for plugin in list_plugin_infos(root):
        if plugin.name == name:
            return "Plugin details:\n" + to_pretty_json(plugin.to_dict())
    return f"Plugin not found: {name}"


def render_plugins(root: Path) -> str:
    """Render available plugin metadata."""

    data = [plugin.to_dict() for plugin in list_plugin_infos(root)]
    return "Available MiniCodex plugins:\n" + to_pretty_json(data)


def render_tool_help(tool_name: str | None = None) -> str:
    """Render supported action/tool schemas."""

    if tool_name:
        spec = ACTION_SPECS.get(tool_name)
        if spec is None:
            return f"Unknown tool: {tool_name}"
        return to_pretty_json(
            {
                "tool": tool_name,
                "required": list(spec.required),
                "optional": list(spec.optional),
            }
        )
    rows = {
        name: {"required": list(spec.required), "optional": list(spec.optional)}
        for name, spec in sorted(ACTION_SPECS.items())
    }
    return truncate("Supported MiniCodex tools:\n" + to_pretty_json(rows), 24000)
