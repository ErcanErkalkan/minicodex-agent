"""Project-level MiniCodex settings stored under .minicodex/config.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import to_pretty_json

CONFIG_PATH = Path(".minicodex/config.json")
DEFAULT_PROJECT_CONFIG: dict[str, Any] = {
    "version": 26,
    "auto_apply_project_config": True,
    "default_safety_profile": "strict",
    "default_approval": "ask",
    "default_test_command": "auto",
    "sandbox_mode": "restricted",
    "sandbox_image": "python:3.12-slim",
    "sandbox_network": "none",
    "sandbox_cpus": "1",
    "sandbox_memory": "1g",
    "sandbox_pids_limit": 256,
    "sandbox_workspace_mode": "copy",
    "sandbox_keep_workspace": False,
    "sandbox_max_file_bytes": 2000000,
    "allow_network_commands": False,
    "allow_github_api_writes": False,
    "default_max_steps": 30,
    "auto_snapshot_before_edit": True,
    "scan_secrets_before_pr": True,
    "untrusted_workspace": False,
    "require_trusted_workspace_for_writes": False,
    "security_audit_max_files": 1000,
    "security_audit_report_max_chars": 24000,
    "external_security_timeout_seconds": 180,
    "log_enabled": True,
    "log_redaction": True,
    "max_log_value_chars": 6000,
    "preferred_provider": "openai",
    "preferred_model": "",
    "model_timeout_seconds": 60,
    "model_max_output_tokens": 2048,
    "model_max_retries": 2,
    "model_retry_backoff_seconds": 1.0,
    "model_repair_attempts": 2,
    "model_structured_output": True,
    "model_call_budget": 60,
    "model_cost_budget_usd": 0.0,
    "model_input_price_per_million": 0.0,
    "model_output_price_per_million": 0.0,
    "model_base_url": "",
    "model_api_key_env": "OPENAI_API_KEY",
    "model_reasoning_effort": "",
    "model_stream": False,
    "model_stream_ui": False,
    "model_action_protocol": "auto",
    "context_enabled": True,
    "context_max_chars": 22000,
    "context_instruction_max_chars": 6000,
    "context_relevant_files": 12,
    "context_observation_chars_each": 1600,
    "skills_enabled": True,
    "skills_max_selected": 6,
    "skills_max_summary_chars": 1000,
    "skills_read_max_chars": 8000,
    "structured_tool_results": True,
    "tool_result_content_chars": 12000,
    "patch_verify_after_apply": True,
    "patch_verify_python_syntax": False,
    "patch_fuzzy_apply": False,
    "test_plan_max_commands": 5,
    "test_output_max_chars": 12000,
    "test_failure_context_lines": 4,
    "flaky_retry_count": 1,
    "developer_ux_enabled": True,
    "review_after_run": False,
    "review_bundle_max_diff_chars": 16000,
    "eval_default_max_steps": 8,
    "eval_model_call_budget": 8,
    "eval_timeout_seconds": 120,
    "eval_report_max_chars": 24000,
    "telemetry_enabled": True,
    "telemetry_run_id": "",
    "telemetry_max_event_chars": 6000,
    "telemetry_jsonl": True,
    "prompt_profile": "auto",
    "prompt_max_chars": 0,
    "prompt_include_action_reference": True,
    "prompt_preview_max_chars": 12000,
    "enabled_plugins": [],
    "max_agent_batch_size": 5,
    "multi_agent_thread_max_messages": 12,
    "multi_agent_result_max_chars": 12000,
    "multi_agent_allow_parallel_writes": False,
    "long_horizon_enabled": False,
    "long_horizon_run_id": "",
    "long_horizon_auto_checkpoint_interval": 0,
    "long_horizon_resume_max_chars": 20000,
    "checkpoint_max_observation_chars": 12000,
    "policy_file": ".minicodex/policy.json",
    "lang": "en",
    "non_interactive": False,
    "default_answer": "",
    "notes": "Project-local MiniCodex settings. Empty enabled_plugins means all plugins are available.",
}


def project_config_path(root: Path) -> Path:
    """Return the absolute MiniCodex project config path."""

    return (root / CONFIG_PATH).resolve()


def read_project_config(root: Path) -> dict[str, Any]:
    """Read project config, returning defaults when no file exists."""

    path = project_config_path(root)
    if not path.exists():
        return dict(DEFAULT_PROJECT_CONFIG)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid MiniCodex config JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"MiniCodex config must be a JSON object: {path}")
    merged = dict(DEFAULT_PROJECT_CONFIG)
    merged.update(raw)
    return merged


def init_project_config(root: Path, overwrite: bool = False, dry_run: bool = False) -> str:
    """Create .minicodex/config.json with defaults."""

    path = project_config_path(root)
    if path.exists() and not overwrite:
        return (
            f"Project config already exists: {path.relative_to(root).as_posix()}\n\n"
            + to_pretty_json(read_project_config(root))
        )
    action = "overwrite" if path.exists() else "create"
    if dry_run:
        return (
            f"DRY-RUN: would {action} project config: {path.relative_to(root).as_posix()}\n\n"
            + to_pretty_json(DEFAULT_PROJECT_CONFIG)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(DEFAULT_PROJECT_CONFIG) + "\n", encoding="utf-8")
    return f"Project config created: {path.relative_to(root).as_posix()}\n\n" + to_pretty_json(
        DEFAULT_PROJECT_CONFIG
    )


def update_project_config(root: Path, updates: dict[str, Any], dry_run: bool = False) -> str:
    """Merge a dictionary of project config updates into the stored config."""

    if not isinstance(updates, dict):
        raise ValueError("updates must be a JSON object")
    current = read_project_config(root)
    current.update(updates)
    path = project_config_path(root)
    if dry_run:
        return (
            f"DRY-RUN: would update project config: {path.relative_to(root).as_posix()}\n\n"
            + to_pretty_json(current)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(current) + "\n", encoding="utf-8")
    return f"Project config updated: {path.relative_to(root).as_posix()}\n\n" + to_pretty_json(
        current
    )


def render_project_config(root: Path) -> str:
    """Return the current project config in readable JSON."""

    path = project_config_path(root)
    status = "stored" if path.exists() else "defaults only; file not created yet"
    return f"MiniCodex project config ({status}):\n" + to_pretty_json(read_project_config(root))
