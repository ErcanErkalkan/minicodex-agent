"""Structured model-action schema validation for MiniCodex.

The model is only allowed to return a single JSON object with this shape:

{
  "thought": "short explanation",
  "action": "one registered action name",
  "args": { ... action-specific arguments ... }
}

This module is dependency-free but intentionally JSON-Schema-like: it provides
strict top-level validation, rejects extra action arguments, validates common
argument types, and can render a JSON Schema document for providers that support
structured output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

JSON_SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"


@dataclass(frozen=True)
class ArgSpec:
    """Schema information for one action argument."""

    kind: str = "any"
    enum: tuple[Any, ...] = ()
    description: str = ""

    def validate(self, action: str, name: str, value: Any) -> None:
        """Raise ActionValidationError when value violates this argument spec."""

        if self.enum and value not in self.enum:
            allowed = ", ".join(repr(item) for item in self.enum)
            raise ActionValidationError(
                f"Arg {name!r} for action {action!r} must be one of: {allowed}."
            )

        kind = self.kind
        if kind == "any":
            return
        if kind == "string":
            if not isinstance(value, str):
                raise ActionValidationError(_type_error(action, name, "string", value))
            return
        if kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ActionValidationError(_type_error(action, name, "integer", value))
            return
        if kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ActionValidationError(_type_error(action, name, "number", value))
            return
        if kind == "boolean":
            if not isinstance(value, bool):
                raise ActionValidationError(_type_error(action, name, "boolean", value))
            return
        if kind == "object":
            if not isinstance(value, Mapping):
                raise ActionValidationError(_type_error(action, name, "object", value))
            return
        if kind == "array":
            if not isinstance(value, list):
                raise ActionValidationError(_type_error(action, name, "array", value))
            return
        if kind == "array_string":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ActionValidationError(_type_error(action, name, "array<string>", value))
            return
        if kind == "array_object":
            if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
                raise ActionValidationError(_type_error(action, name, "array<object>", value))
            return
        raise ActionValidationError(f"Internal schema error: unknown ArgSpec kind {kind!r}.")

    def to_json_schema(self) -> dict[str, Any]:
        """Render this argument spec as a JSON Schema fragment."""

        if self.kind == "any":
            schema: dict[str, Any] = {}
        elif self.kind == "array_string":
            schema = {"type": "array", "items": {"type": "string"}}
        elif self.kind == "array_object":
            schema = {"type": "array", "items": {"type": "object"}}
        elif self.kind == "array":
            schema = {"type": "array"}
        elif self.kind in {"string", "integer", "number", "boolean", "object"}:
            schema = {"type": self.kind}
        else:
            schema = {}
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.description:
            schema["description"] = self.description
        return schema


@dataclass(frozen=True)
class ActionSpec:
    """Strict schema information for one model action."""

    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    arg_types: Mapping[str, ArgSpec] = field(default_factory=dict)
    description: str = ""

    @property
    def allowed_args(self) -> tuple[str, ...]:
        """Return all accepted argument names in stable order."""

        return self.required + self.optional

    def arg_spec(self, name: str) -> ArgSpec:
        """Return the schema for an argument, defaulting to permissive any."""

        return self.arg_types.get(name, ArgSpec())


S = ArgSpec("string")
I = ArgSpec("integer")  # noqa: E741
N = ArgSpec("number")
B = ArgSpec("boolean")
O = ArgSpec("object")  # noqa: E741
A = ArgSpec("array")
AS = ArgSpec("array_string")
AO = ArgSpec("array_object")
SEVERITY = ArgSpec("string", enum=("low", "medium", "high", "critical"))
STATUS = ArgSpec("string", enum=("todo", "doing", "done", "blocked", "cancelled"))
POLICY_KIND = ArgSpec("string", enum=("write_path", "command", "patch"))
APPROVAL_DECISION = ArgSpec("string", enum=("approved", "rejected", "needs_changes"))


def action_spec(
    required: Sequence[str] = (),
    optional: Sequence[str] = (),
    types: Mapping[str, ArgSpec] | None = None,
    description: str = "",
) -> ActionSpec:
    """Small helper to keep ACTION_SPECS readable."""

    return ActionSpec(tuple(required), tuple(optional), types or {}, description)


ACTION_SPECS: dict[str, ActionSpec] = {
    "run_setup_wizard": action_spec(
        optional=(
            "overwrite",
            "provider",
            "approval",
            "safety_profile",
            "test_command",
            "max_steps",
            "create_env_example",
            "create_policy",
            "create_plugin_example",
            "create_agent_instructions",
            "create_skill_example",
        ),
        types={
            "overwrite": B,
            "provider": S,
            "approval": ArgSpec("string", enum=("ask", "auto")),
            "safety_profile": ArgSpec("string", enum=("strict", "balanced", "permissive")),
            "test_command": S,
            "max_steps": I,
            "create_env_example": B,
            "create_policy": B,
            "create_plugin_example": B,
            "create_agent_instructions": B,
            "create_skill_example": B,
        },
    ),
    "create_demo_project": action_spec(
        required=("target_path",), optional=("overwrite",), types={"target_path": S, "overwrite": B}
    ),
    "release_checklist": action_spec(optional=("version",), types={"version": S}),
    "write_release_notes": action_spec(
        optional=("version", "output_path"), types={"version": S, "output_path": S}
    ),
    "project_health_report": action_spec(optional=("max_chars",), types={"max_chars": I}),
    "final_readiness_report": action_spec(
        optional=(
            "include_cli_smoke",
            "include_test_matrix",
            "include_security_audit",
            "include_verification_tools",
            "run_test_matrix",
            "test_matrix_max_files",
            "test_matrix_timeout",
            "test_matrix_group",
            "run_verification_tools",
            "timeout",
            "max_chars",
        ),
        types={
            "include_cli_smoke": B,
            "include_test_matrix": B,
            "include_security_audit": B,
            "include_verification_tools": B,
            "run_test_matrix": B,
            "test_matrix_max_files": I,
            "test_matrix_timeout": I,
            "test_matrix_group": ArgSpec(
                "string",
                enum=("fast", "unit", "integration", "subprocess", "sandbox", "slow", "all"),
            ),
            "run_verification_tools": B,
            "timeout": I,
            "max_chars": I,
        },
    ),
    "test_matrix_plan": action_spec(
        optional=("per_file_timeout", "group", "max_chars"),
        types={
            "per_file_timeout": I,
            "group": ArgSpec(
                "string",
                enum=("fast", "unit", "integration", "subprocess", "sandbox", "slow", "all"),
            ),
            "max_chars": I,
        },
    ),
    "release_package_manifest": action_spec(
        optional=("from_zip", "max_chars"), types={"from_zip": S, "max_chars": I}
    ),
    "clean_generated_artifacts": action_spec(
        optional=("dry_run", "include_build_outputs"),
        types={"dry_run": B, "include_build_outputs": B},
    ),
    "init_project_config": action_spec(optional=("overwrite",), types={"overwrite": B}),
    "read_project_config": action_spec(),
    "update_project_config": action_spec(required=("updates",), types={"updates": O}),
    "init_project_policy": action_spec(optional=("overwrite",), types={"overwrite": B}),
    "read_project_policy": action_spec(),
    "update_project_policy": action_spec(required=("updates",), types={"updates": O}),
    "check_project_policy": action_spec(
        required=("kind", "value"), types={"kind": POLICY_KIND, "value": S}
    ),
    "validate_plugins": action_spec(),
    "enabled_tools": action_spec(),
    "inspect_plugin": action_spec(required=("name",), types={"name": S}),
    "list_providers": action_spec(),
    "list_prompt_profiles": action_spec(),
    "render_prompt_bundle": action_spec(
        optional=("profile", "goal", "provider", "include_action_reference", "max_chars"),
        types={
            "profile": S,
            "goal": S,
            "provider": S,
            "include_action_reference": B,
            "max_chars": I,
        },
    ),
    "validate_prompt_contract": action_spec(
        optional=("profile", "goal", "provider", "include_action_reference", "max_chars"),
        types={
            "profile": S,
            "goal": S,
            "provider": S,
            "include_action_reference": B,
            "max_chars": I,
        },
    ),
    "list_plugins": action_spec(),
    "list_skills": action_spec(optional=("goal", "max_skills"), types={"goal": S, "max_skills": I}),
    "read_skill": action_spec(
        required=("name",), optional=("max_chars",), types={"name": S, "max_chars": I}
    ),
    "validate_skills": action_spec(optional=("max_skills",), types={"max_skills": I}),
    "init_skill": action_spec(
        required=("name",),
        optional=("description", "overwrite"),
        types={"name": S, "description": S, "overwrite": B},
    ),
    "tool_help": action_spec(optional=("tool",), types={"tool": S}),
    "review_change_set": action_spec(optional=("max_diff_chars",), types={"max_diff_chars": I}),
    "record_change_approval": action_spec(
        required=("decision",), optional=("note",), types={"decision": APPROVAL_DECISION, "note": S}
    ),
    "render_tui_panel": action_spec(
        optional=("goal", "max_diff_chars"), types={"goal": S, "max_diff_chars": I}
    ),
    "create_review_bundle": action_spec(
        optional=("title", "goal", "max_diff_chars"),
        types={"title": S, "goal": S, "max_diff_chars": I},
    ),
    "list_review_bundles": action_spec(optional=("limit",), types={"limit": I}),
    "read_review_bundle": action_spec(
        optional=("bundle_id", "max_chars"), types={"bundle_id": S, "max_chars": I}
    ),
    "record_review_decision": action_spec(
        required=("bundle_id", "decision"),
        optional=("note",),
        types={"bundle_id": S, "decision": APPROVAL_DECISION, "note": S},
    ),
    "run_summary": action_spec(
        optional=("run_id", "limit", "max_chars"), types={"run_id": S, "limit": I, "max_chars": I}
    ),
    "export_ide_bridge": action_spec(optional=("output_path",), types={"output_path": S}),
    "run_terminal_session": action_spec(
        required=("commands",),
        optional=("timeout_each", "max_commands"),
        types={"commands": AS, "timeout_each": I, "max_commands": I},
    ),
    "list_terminal_sessions": action_spec(optional=("limit",), types={"limit": I}),
    "list_files": action_spec(optional=("path", "max_files"), types={"path": S, "max_files": I}),
    "list_dir": action_spec(optional=("path", "max_entries"), types={"path": S, "max_entries": I}),
    "glob_file_search": action_spec(
        required=("pattern",),
        optional=("path", "max_matches"),
        types={"pattern": S, "path": S, "max_matches": I},
    ),
    "read_file": action_spec(
        required=("path",), optional=("max_chars",), types={"path": S, "max_chars": I}
    ),
    "read_file_range": action_spec(
        required=("path",),
        optional=("start_line", "end_line", "max_chars"),
        types={"path": S, "start_line": I, "end_line": I, "max_chars": I},
    ),
    "read_many_files": action_spec(
        required=("paths",), optional=("max_chars_each",), types={"paths": AS, "max_chars_each": I}
    ),
    "search_text": action_spec(
        required=("query",),
        optional=("path", "max_matches"),
        types={"query": S, "path": S, "max_matches": I},
    ),
    "rg_search": action_spec(
        required=("pattern",),
        optional=("path", "max_matches", "context_lines", "case_sensitive"),
        types={"pattern": S, "path": S, "max_matches": I, "context_lines": I, "case_sensitive": B},
    ),
    "search_code": action_spec(
        required=("query",),
        optional=("path", "max_matches", "context_lines"),
        types={"query": S, "path": S, "max_matches": I, "context_lines": I},
    ),
    "build_dependency_graph": action_spec(
        optional=("path", "max_files"), types={"path": S, "max_files": I}
    ),
    "index_project": action_spec(
        optional=("path", "max_files", "save"), types={"path": S, "max_files": I, "save": B}
    ),
    "detect_language_stack": action_spec(optional=("max_files",), types={"max_files": I}),
    "inspect_frameworks": action_spec(optional=("max_files",), types={"max_files": I}),
    "suggest_verification_commands": action_spec(
        optional=("changed_files", "purposes", "max_commands"),
        types={"changed_files": AS, "purposes": AS, "max_commands": I},
    ),
    "language_adapter_report": action_spec(
        optional=("max_files", "max_chars"), types={"max_files": I, "max_chars": I}
    ),
    "semantic_capability_report": action_spec(optional=("max_chars",), types={"max_chars": I}),
    "build_semantic_index": action_spec(
        optional=(
            "max_files",
            "max_symbols",
            "max_references_per_symbol",
            "include_routes",
            "max_chars",
        ),
        types={
            "max_files": I,
            "max_symbols": I,
            "max_references_per_symbol": I,
            "include_routes": B,
            "max_chars": I,
        },
    ),
    "find_symbol_references": action_spec(
        required=("symbol",),
        optional=("language", "path", "max_matches", "max_chars"),
        types={"symbol": S, "language": S, "path": S, "max_matches": I, "max_chars": I},
    ),
    "inspect_routes": action_spec(
        optional=("framework", "max_routes", "max_chars"),
        types={"framework": S, "max_routes": I, "max_chars": I},
    ),
    "create_snapshot": action_spec(
        optional=("label", "max_files", "max_bytes_per_file"),
        types={"label": S, "max_files": I, "max_bytes_per_file": I},
    ),
    "list_snapshots": action_spec(optional=("limit",), types={"limit": I}),
    "restore_snapshot": action_spec(
        required=("snapshot_id",),
        optional=("dry_run", "create_restore_backup"),
        types={"snapshot_id": S, "dry_run": B, "create_restore_backup": B},
    ),
    "read_task_memory": action_spec(optional=("limit", "query"), types={"limit": I, "query": S}),
    "save_task_memory": action_spec(
        required=("summary",),
        optional=("changed_files", "checks_run", "success"),
        types={"summary": S, "changed_files": AS, "checks_run": AS, "success": B},
    ),
    "generate_commit_message": action_spec(optional=("goal",), types={"goal": S}),
    "decompose_task": action_spec(
        optional=("goal", "max_steps"), types={"goal": S, "max_steps": I}
    ),
    "build_code_map": action_spec(
        optional=("path", "max_files"), types={"path": S, "max_files": I}
    ),
    "write_file": action_spec(required=("path", "content"), types={"path": S, "content": S}),
    "replace_in_file": action_spec(
        required=("path", "old", "new"),
        optional=("count",),
        types={"path": S, "old": S, "new": S, "count": I},
    ),
    "preview_replace_in_file": action_spec(
        required=("path", "old", "new"),
        optional=("count",),
        types={"path": S, "old": S, "new": S, "count": I},
    ),
    "plan_patch": action_spec(
        required=("patch",),
        optional=("fuzzy", "max_chars"),
        types={"patch": S, "fuzzy": B, "max_chars": I},
    ),
    "verify_patch": action_spec(
        required=("patch",),
        optional=("fuzzy", "verify_python_syntax"),
        types={"patch": S, "fuzzy": B, "verify_python_syntax": B},
    ),
    "apply_patch": action_spec(
        required=("patch",),
        optional=("fuzzy", "verify", "verify_python_syntax"),
        types={"patch": S, "fuzzy": B, "verify": B, "verify_python_syntax": B},
    ),
    "ast_patch_capability_report": action_spec(optional=("max_chars",), types={"max_chars": I}),
    "plan_semantic_edit": action_spec(
        required=("operation",),
        optional=("path", "language", "symbol", "new_name", "max_files", "max_chars"),
        types={
            "operation": S,
            "path": S,
            "language": S,
            "symbol": S,
            "new_name": S,
            "max_files": I,
            "max_chars": I,
        },
    ),
    "rename_symbol_semantic": action_spec(
        required=("old_name", "new_name"),
        optional=("language", "path", "max_files", "preview_only"),
        types={
            "old_name": S,
            "new_name": S,
            "language": S,
            "path": S,
            "max_files": I,
            "preview_only": B,
        },
    ),
    "organize_imports": action_spec(
        optional=("path", "language", "max_files", "preview_only"),
        types={"path": S, "language": S, "max_files": I, "preview_only": B},
    ),
    "detect_dead_code": action_spec(
        optional=("language", "path", "include_public", "max_files", "max_candidates", "max_chars"),
        types={
            "language": S,
            "path": S,
            "include_public": B,
            "max_files": I,
            "max_candidates": I,
            "max_chars": I,
        },
    ),
    "cleanup_dead_code": action_spec(
        optional=("names", "path", "include_public", "max_files", "preview_only"),
        types={"names": AS, "path": S, "include_public": B, "max_files": I, "preview_only": B},
    ),
    "format_and_verify": action_spec(
        required=("path",),
        optional=("formatter", "run_formatter", "verify_syntax", "timeout", "max_chars"),
        types={
            "path": S,
            "formatter": ArgSpec(
                "string",
                enum=(
                    "auto",
                    "ruff",
                    "black",
                    "prettier",
                    "gofmt",
                    "rustfmt",
                    "google-java-format",
                ),
            ),
            "run_formatter": B,
            "verify_syntax": B,
            "timeout": I,
            "max_chars": I,
        },
    ),
    "inspect_python_ast": action_spec(
        required=("path",), optional=("max_chars",), types={"path": S, "max_chars": I}
    ),
    "find_python_symbol": action_spec(
        required=("symbol",),
        optional=("path", "max_matches"),
        types={"symbol": S, "path": S, "max_matches": I},
    ),
    "rename_python_symbol": action_spec(
        required=("old_name", "new_name"),
        optional=("path", "max_files", "preview_only"),
        types={"old_name": S, "new_name": S, "path": S, "max_files": I, "preview_only": B},
    ),
    "validate_config": action_spec(
        required=("path",), optional=("max_chars",), types={"path": S, "max_chars": I}
    ),
    "scan_secrets": action_spec(
        optional=("path", "max_files", "max_bytes_per_file", "max_findings", "minimum_severity"),
        types={
            "path": S,
            "max_files": I,
            "max_bytes_per_file": I,
            "max_findings": I,
            "minimum_severity": SEVERITY,
        },
    ),
    "check_rollback_policy": action_spec(
        optional=("max_changed_files", "max_diff_lines"),
        types={"max_changed_files": I, "max_diff_lines": I},
    ),
    "run_external_secret_scan": action_spec(
        optional=("tool", "path", "timeout", "dry_run"),
        types={
            "tool": ArgSpec("string", enum=("gitleaks", "trufflehog", "auto")),
            "path": S,
            "timeout": I,
            "dry_run": B,
        },
    ),
    "run_sast_scan": action_spec(
        optional=("scanner", "timeout", "dry_run", "max_files", "minimum_severity"),
        types={
            "scanner": ArgSpec("string", enum=("auto", "semgrep", "builtin")),
            "timeout": I,
            "dry_run": B,
            "max_files": I,
            "minimum_severity": SEVERITY,
        },
    ),
    "run_dependency_audit": action_spec(
        optional=("timeout", "dry_run"), types={"timeout": I, "dry_run": B}
    ),
    "scan_repo_instructions": action_spec(optional=("max_files",), types={"max_files": I}),
    "validate_plugin_permissions": action_spec(),
    "workspace_trust_report": action_spec(
        optional=("untrusted_workspace",), types={"untrusted_workspace": B}
    ),
    "security_audit_report": action_spec(
        optional=("max_files", "untrusted_workspace"),
        types={"max_files": I, "untrusted_workspace": B},
    ),
    "enqueue_task": action_spec(
        required=("title",),
        optional=("details", "priority"),
        types={"title": S, "details": S, "priority": S},
    ),
    "list_task_queue": action_spec(
        optional=("status", "limit"), types={"status": STATUS, "limit": I}
    ),
    "update_task_status": action_spec(
        required=("task_id", "status"),
        optional=("note",),
        types={"task_id": S, "status": STATUS, "note": S},
    ),
    "dequeue_next_task": action_spec(),
    "plan_multi_agent_work": action_spec(
        optional=("goal", "max_agents"), types={"goal": S, "max_agents": I}
    ),
    "plan_subagent_threads": action_spec(
        optional=("goal", "max_agents", "roles", "max_steps_each", "model_call_budget_each"),
        types={
            "goal": S,
            "max_agents": I,
            "roles": AS,
            "max_steps_each": I,
            "model_call_budget_each": I,
        },
    ),
    "run_task_batch": action_spec(
        required=("tasks",),
        optional=("max_tasks", "dry_run"),
        types={"tasks": A, "max_tasks": I, "dry_run": B},
    ),
    "list_agent_batches": action_spec(optional=("limit",), types={"limit": I}),
    "run_multi_agent_work": action_spec(
        optional=(
            "goal",
            "max_agents",
            "execution_mode",
            "max_steps_each",
            "model_call_budget_each",
            "roles",
            "dry_run",
        ),
        types={
            "goal": S,
            "max_agents": I,
            "execution_mode": ArgSpec("string", enum=("sequential", "parallel")),
            "max_steps_each": I,
            "model_call_budget_each": I,
            "roles": AS,
            "dry_run": B,
        },
    ),
    "run_subagent_threads": action_spec(
        optional=(
            "goal",
            "max_agents",
            "execution_mode",
            "max_steps_each",
            "model_call_budget_each",
            "roles",
            "dry_run",
        ),
        types={
            "goal": S,
            "max_agents": I,
            "execution_mode": ArgSpec("string", enum=("sequential", "parallel")),
            "max_steps_each": I,
            "model_call_budget_each": I,
            "roles": AS,
            "dry_run": B,
        },
    ),
    "list_multi_agent_runs": action_spec(optional=("limit",), types={"limit": I}),
    "read_multi_agent_run": action_spec(
        required=("run_id",),
        optional=("include_observations", "max_chars"),
        types={"run_id": S, "include_observations": B, "max_chars": I},
    ),
    "create_long_task": action_spec(
        optional=("goal", "title", "acceptance_criteria", "milestones"),
        types={"goal": S, "title": S, "acceptance_criteria": AS, "milestones": AS},
    ),
    "list_long_tasks": action_spec(
        optional=("limit", "include_completed"), types={"limit": I, "include_completed": B}
    ),
    "read_long_task": action_spec(
        required=("run_id",),
        optional=("include_checkpoints", "max_chars"),
        types={"run_id": S, "include_checkpoints": B, "max_chars": I},
    ),
    "resume_long_task": action_spec(
        required=("run_id",), optional=("max_chars",), types={"run_id": S, "max_chars": I}
    ),
    "update_acceptance_criteria": action_spec(
        required=("run_id",),
        optional=("accepted", "blocked", "pending", "evidence"),
        types={"run_id": S, "accepted": AS, "blocked": AS, "pending": AS, "evidence": S},
    ),
    "create_checkpoint": action_spec(
        required=("run_id",),
        optional=(
            "label",
            "summary",
            "completed_milestones",
            "accepted_criteria",
            "changed_files",
            "checks_run",
            "next_steps",
            "observations_summary",
            "status",
        ),
        types={
            "run_id": S,
            "label": S,
            "summary": S,
            "completed_milestones": AS,
            "accepted_criteria": AS,
            "changed_files": AS,
            "checks_run": AS,
            "next_steps": AS,
            "observations_summary": S,
            "status": ArgSpec(
                "string", enum=("active", "paused", "blocked", "done", "completed", "cancelled")
            ),
        },
    ),
    "init_eval_suite": action_spec(
        optional=("overwrite", "dry_run"), types={"overwrite": B, "dry_run": B}
    ),
    "init_eval_baselines": action_spec(
        optional=("overwrite", "dry_run"), types={"overwrite": B, "dry_run": B}
    ),
    "list_eval_tasks": action_spec(
        optional=("category", "tag", "limit"), types={"category": S, "tag": S, "limit": I}
    ),
    "list_eval_baselines": action_spec(optional=("tag", "limit"), types={"tag": S, "limit": I}),
    "eval_coverage_report": action_spec(),
    "eval_baseline_plan": action_spec(
        required=("baseline_id",), optional=("run_id",), types={"baseline_id": S, "run_id": S}
    ),
    "compare_eval_baselines": action_spec(
        required=("baseline_run_id", "candidate_run_id"),
        optional=("min_success_delta",),
        types={"baseline_run_id": S, "candidate_run_id": S, "min_success_delta": N},
    ),
    "read_eval_task": action_spec(
        required=("task_id",),
        optional=("include_files", "max_chars"),
        types={"task_id": S, "include_files": B, "max_chars": I},
    ),
    "run_eval_task": action_spec(
        required=("task_id",),
        optional=("run_id", "max_steps", "model_call_budget", "timeout", "dry_run", "max_chars"),
        types={
            "task_id": S,
            "run_id": S,
            "max_steps": I,
            "model_call_budget": I,
            "timeout": I,
            "dry_run": B,
            "max_chars": I,
        },
    ),
    "run_eval_suite": action_spec(
        optional=(
            "task_ids",
            "run_id",
            "max_steps",
            "model_call_budget",
            "timeout",
            "dry_run",
            "max_chars",
        ),
        types={
            "task_ids": AS,
            "run_id": S,
            "max_steps": I,
            "model_call_budget": I,
            "timeout": I,
            "dry_run": B,
            "max_chars": I,
        },
    ),
    "list_eval_runs": action_spec(optional=("limit",), types={"limit": I}),
    "read_eval_run": action_spec(
        required=("run_id",), optional=("max_chars",), types={"run_id": S, "max_chars": I}
    ),
    "compare_eval_runs": action_spec(
        required=("baseline_run_id", "candidate_run_id"),
        types={"baseline_run_id": S, "candidate_run_id": S},
    ),
    "diagnose_patch_failure": action_spec(
        optional=("patch", "error"), types={"patch": S, "error": S}
    ),
    "list_telemetry_runs": action_spec(optional=("limit",), types={"limit": I}),
    "read_telemetry_run": action_spec(
        required=("run_id",),
        optional=("include_spans", "max_chars"),
        types={"run_id": S, "include_spans": B, "max_chars": I},
    ),
    "telemetry_summary": action_spec(
        optional=("limit", "max_chars"), types={"limit": I, "max_chars": I}
    ),
    "compare_telemetry_runs": action_spec(
        required=("baseline_run_id", "candidate_run_id"),
        optional=("max_chars",),
        types={"baseline_run_id": S, "candidate_run_id": S, "max_chars": I},
    ),
    "export_telemetry_bundle": action_spec(
        optional=("run_id", "max_chars", "dry_run"),
        types={"run_id": S, "max_chars": I, "dry_run": B},
    ),
    "list_model_prices": action_spec(optional=("max_chars",), types={"max_chars": I}),
    "optimization_dashboard": action_spec(
        optional=("limit", "max_chars"), types={"limit": I, "max_chars": I}
    ),
    "failure_dashboard": action_spec(
        optional=("limit", "max_chars"), types={"limit": I, "max_chars": I}
    ),
    "run_prompt_ab_comparison": action_spec(
        optional=(
            "task_ids",
            "prompt_profiles",
            "run_id",
            "max_steps",
            "model_call_budget",
            "timeout",
            "dry_run",
            "max_chars",
        ),
        types={
            "task_ids": AS,
            "prompt_profiles": AS,
            "run_id": S,
            "max_steps": I,
            "model_call_budget": I,
            "timeout": I,
            "dry_run": B,
            "max_chars": I,
        },
    ),
    "prepare_pr_summary": action_spec(),
    "detect_github_workflows": action_spec(optional=("max_chars",), types={"max_chars": I}),
    "init_github_action": action_spec(
        optional=("workflow_name", "overwrite", "dry_run"),
        types={"workflow_name": S, "overwrite": B, "dry_run": B},
    ),
    "parse_pr_comment_command": action_spec(
        required=("comment",), optional=("prefix",), types={"comment": S, "prefix": S}
    ),
    "prepare_commit_push_plan": action_spec(
        optional=("branch", "commit_message", "remote", "include_push"),
        types={"branch": S, "commit_message": S, "remote": S, "include_push": B},
    ),
    "summarize_github_ci_log": action_spec(
        optional=("output", "log_path", "workflow_name", "max_chars"),
        types={"output": S, "log_path": S, "workflow_name": S, "max_chars": I},
    ),
    "github_ci_fetch_preview": action_spec(
        optional=("owner", "repo", "run_id"), types={"owner": S, "repo": S, "run_id": S}
    ),
    "generate_github_app_manifest": action_spec(
        optional=("app_name", "webhook_url", "output_path", "overwrite", "dry_run", "max_chars"),
        types={
            "app_name": S,
            "webhook_url": S,
            "output_path": S,
            "overwrite": B,
            "dry_run": B,
            "max_chars": I,
        },
    ),
    "init_github_webhook_server": action_spec(
        optional=("output_path", "overwrite", "dry_run", "max_chars"),
        types={"output_path": S, "overwrite": B, "dry_run": B, "max_chars": I},
    ),
    "fetch_github_ci_log": action_spec(
        required=("run_id",),
        optional=("owner", "repo", "summarize", "max_log_chars", "timeout", "dry_run"),
        types={
            "run_id": S,
            "owner": S,
            "repo": S,
            "summarize": B,
            "max_log_chars": I,
            "timeout": I,
            "dry_run": B,
        },
    ),
    "execute_commit_push_workflow": action_spec(
        optional=("branch", "commit_message", "remote", "include_push", "dry_run", "timeout"),
        types={
            "branch": S,
            "commit_message": S,
            "remote": S,
            "include_push": B,
            "dry_run": B,
            "timeout": I,
        },
    ),
    "resolve_review_comments": action_spec(
        optional=("comments", "comments_json", "post", "pull_number", "owner", "repo"),
        types={
            "comments": AO,
            "comments_json": S,
            "post": B,
            "pull_number": I,
            "owner": S,
            "repo": S,
        },
    ),
    "prepare_github_artifact_upload": action_spec(
        optional=("workflow_name", "artifact_name", "paths"),
        types={"workflow_name": S, "artifact_name": S, "paths": AS},
    ),
    "create_github_review_comment": action_spec(
        required=("pull_number", "body"),
        optional=("event", "owner", "repo", "dry_run"),
        types={
            "pull_number": I,
            "body": S,
            "event": ArgSpec("string", enum=("COMMENT", "APPROVE", "REQUEST_CHANGES")),
            "owner": S,
            "repo": S,
            "dry_run": B,
        },
    ),
    "prepare_github_pr": action_spec(
        optional=("title", "body", "base", "draft"),
        types={"title": S, "body": S, "base": S, "draft": B},
    ),
    "prepare_github_issue": action_spec(
        required=("title", "body"),
        optional=("labels",),
        types={"title": S, "body": S, "labels": AS},
    ),
    "create_github_pr": action_spec(
        required=("title", "body"),
        optional=("base", "head", "draft", "owner", "repo", "dry_run"),
        types={
            "title": S,
            "body": S,
            "base": S,
            "head": S,
            "draft": B,
            "owner": S,
            "repo": S,
            "dry_run": B,
        },
    ),
    "create_github_issue": action_spec(
        required=("title", "body"),
        optional=("labels", "owner", "repo", "dry_run"),
        types={"title": S, "body": S, "labels": AS, "owner": S, "repo": S, "dry_run": B},
    ),
    "run_command": action_spec(
        required=("command",), optional=("timeout",), types={"command": S, "timeout": I}
    ),
    "run_tests": action_spec(optional=("command", "timeout"), types={"command": S, "timeout": I}),
    "plan_tests": action_spec(
        optional=(
            "changed_files",
            "failure_output",
            "command",
            "include_lint",
            "include_build",
            "include_typecheck",
            "max_commands",
        ),
        types={
            "changed_files": AS,
            "failure_output": S,
            "command": S,
            "include_lint": B,
            "include_build": B,
            "include_typecheck": B,
            "max_commands": I,
        },
    ),
    "run_targeted_tests": action_spec(
        optional=(
            "changed_files",
            "failure_output",
            "command",
            "include_lint",
            "include_build",
            "include_typecheck",
            "max_commands",
            "timeout",
            "stop_on_failure",
        ),
        types={
            "changed_files": AS,
            "failure_output": S,
            "command": S,
            "include_lint": B,
            "include_build": B,
            "include_typecheck": B,
            "max_commands": I,
            "timeout": I,
            "stop_on_failure": B,
        },
    ),
    "classify_test_failure": action_spec(
        optional=("output", "max_excerpt_chars"), types={"output": S, "max_excerpt_chars": I}
    ),
    "summarize_ci_log": action_spec(
        optional=("output", "max_chars"), types={"output": S, "max_chars": I}
    ),
    "detect_flaky_tests": action_spec(
        optional=("output", "prior_outputs"), types={"output": S, "prior_outputs": AS}
    ),
    "analyze_failure": action_spec(
        optional=("output", "context_lines"), types={"output": S, "context_lines": I}
    ),
    "inspect_project": action_spec(),
    "git_status": action_spec(),
    "git_diff": action_spec(),
    "update_plan": action_spec(required=("steps",), types={"steps": AS}),
    "ask_user": action_spec(required=("question",), types={"question": S}),
    "finish": action_spec(
        optional=("summary", "changed_files", "checks_run", "next_steps"),
        types={"summary": S, "changed_files": AS, "checks_run": AS, "next_steps": AS},
    ),
}


class ActionValidationError(ValueError):
    """Raised when a model action does not match the supported schema."""


def _type_error(action: str, name: str, expected: str, value: Any) -> str:
    return f"Arg {name!r} for action {action!r} must be {expected}; got {type(value).__name__}."


def validate_action(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one model action object.

    This is strict by design. Unknown top-level keys and unknown action args are
    rejected so the model cannot smuggle unreviewed parameters into tools.
    """

    if not isinstance(decision, Mapping):
        raise ActionValidationError("Model output must be a JSON object.")

    allowed_top_level = {"thought", "action", "args"}
    extra_top_level = sorted(set(decision) - allowed_top_level)
    if extra_top_level:
        raise ActionValidationError(
            "Model output has unsupported top-level key(s): " + ", ".join(extra_top_level)
        )

    action = decision.get("action")
    if not isinstance(action, str) or not action.strip():
        raise ActionValidationError("Model output must include a non-empty string action.")
    action = action.strip()

    if action not in ACTION_SPECS:
        allowed = ", ".join(sorted(ACTION_SPECS))
        raise ActionValidationError(f"Unsupported action: {action}. Allowed actions: {allowed}")

    thought = decision.get("thought", "")
    if not isinstance(thought, str):
        raise ActionValidationError("Model output field 'thought' must be a string.")

    args = decision.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, Mapping):
        raise ActionValidationError(f"Args for action {action} must be a JSON object.")

    spec = ACTION_SPECS[action]
    missing = [name for name in spec.required if name not in args]
    if missing:
        raise ActionValidationError(
            f"Action {action} is missing required arg(s): {', '.join(missing)}"
        )

    extra_args = sorted(set(args) - set(spec.allowed_args))
    if extra_args:
        raise ActionValidationError(
            f"Action {action} has unsupported arg(s): {', '.join(extra_args)}"
        )

    normalized_args = dict(args)
    for name, value in normalized_args.items():
        spec.arg_spec(name).validate(action, name, value)

    return {"thought": thought, "action": action, "args": normalized_args}


def _action_schema_variant(name: str, spec: ActionSpec) -> dict[str, Any]:
    arg_properties = {
        arg_name: spec.arg_spec(arg_name).to_json_schema() for arg_name in spec.allowed_args
    }
    arg_schema = {
        "type": "object",
        "properties": arg_properties,
        "required": list(spec.required),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string"},
            "action": {"const": name},
            "args": arg_schema,
        },
        "required": ["thought", "action", "args"],
        "additionalProperties": False,
    }


def build_model_action_json_schema() -> dict[str, Any]:
    """Return a strict JSON Schema for provider structured-output mode."""

    return {
        "$schema": JSON_SCHEMA_VERSION,
        "title": "MiniCodexModelAction",
        "description": "A single MiniCodex model action.",
        "oneOf": [
            _action_schema_variant(name, spec) for name, spec in sorted(ACTION_SPECS.items())
        ],
    }


MODEL_ACTION_JSON_SCHEMA = build_model_action_json_schema()


def render_action_reference() -> str:
    """Return a compact action reference for prompts and diagnostics."""

    lines: list[str] = []
    for name, spec in sorted(ACTION_SPECS.items()):
        required = ", ".join(spec.required) if spec.required else "-"
        optional = ", ".join(spec.optional) if spec.optional else "-"
        typed_args: list[str] = []
        for arg_name in spec.allowed_args:
            typed_args.append(f"{arg_name}:{spec.arg_spec(arg_name).kind}")
        type_msg = ", ".join(typed_args) if typed_args else "-"
        lines.append(
            f"- {name}: required=[{required}] optional=[{optional}] arg_types=[{type_msg}]"
        )
    return "\n".join(lines)
