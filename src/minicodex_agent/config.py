"""Configuration helpers for MiniCodex."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .provider_registry import get_provider_info, list_provider_names

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


@dataclass(frozen=True)
class AgentConfig:
    """Runtime configuration for the coding agent."""

    root: Path
    model: str
    provider: str = (
        "openai"  # openai | openai_compatible | ollama | lmstudio | llama_cpp | stub | echo
    )
    max_steps: int = 30
    approval: str = "ask"  # ask | auto
    show_diff: bool = True
    max_observation_chars: int = 12000
    max_file_read_chars: int = 24000
    safety_profile: str = "strict"  # strict | balanced | permissive
    log_dir: str = ".minicodex/runs"
    create_branch: bool = False
    test_command: str = "auto"
    dry_run: bool = False
    index_max_files: int = 500
    index_max_file_chars: int = 80000
    project_config_enabled: bool = True
    project_policy_enabled: bool = True
    allow_network_commands: bool = False
    allow_github_api_writes: bool = False
    sandbox_mode: str = "restricted"  # restricted | docker | podman
    sandbox_image: str = "python:3.12-slim"
    sandbox_network: str = "none"  # none | default | bridge | host
    sandbox_cpus: str = "1"
    sandbox_memory: str = "1g"
    sandbox_pids_limit: int = 256
    sandbox_workspace_mode: str = "copy"  # copy | mount
    sandbox_keep_workspace: bool = False
    sandbox_max_file_bytes: int = 2_000_000
    agent_workspace_mode: str = "direct"  # direct | isolated
    agent_workspace_apply: str = "never"  # never | ask | auto
    agent_workspace_keep: bool = False
    agent_workspace_max_file_bytes: int = 2_000_000
    agent_workspace_diff_max_chars: int = 24000
    log_enabled: bool = True
    log_redaction: bool = True
    max_log_value_chars: int = 6000
    auto_snapshot_before_edit: bool = True
    scan_secrets_before_pr: bool = True
    untrusted_workspace: bool = False
    require_trusted_workspace_for_writes: bool = False
    security_audit_max_files: int = 1000
    security_audit_report_max_chars: int = 24000
    external_security_timeout_seconds: int = 180
    max_agent_batch_size: int = 5
    multi_agent_thread_max_messages: int = 12
    multi_agent_result_max_chars: int = 12000
    multi_agent_allow_parallel_writes: bool = False
    long_horizon_enabled: bool = False
    long_horizon_run_id: str = ""
    long_horizon_auto_checkpoint_interval: int = 0
    long_horizon_resume_max_chars: int = 20000
    checkpoint_max_observation_chars: int = 12000
    enabled_plugins: tuple[str, ...] = ()
    policy_file: str = ".minicodex/policy.json"
    model_timeout_seconds: int = 60
    model_max_output_tokens: int = 2048
    model_max_retries: int = 2
    model_retry_backoff_seconds: float = 1.0
    model_repair_attempts: int = 2
    model_structured_output: bool = True
    model_call_budget: int = 60
    model_cost_budget_usd: float = 0.0
    model_input_price_per_million: float = 0.0
    model_output_price_per_million: float = 0.0
    model_base_url: str = ""
    model_api_key_env: str = "OPENAI_API_KEY"
    model_reasoning_effort: str = ""
    model_stream: bool = False
    model_stream_ui: bool = False
    model_action_protocol: str = "auto"  # auto | json_text | tool_calls
    context_enabled: bool = True
    context_max_chars: int = 22000
    context_instruction_max_chars: int = 6000
    context_relevant_files: int = 12
    context_observation_chars_each: int = 1600
    skills_enabled: bool = True
    skills_max_selected: int = 6
    skills_max_summary_chars: int = 1000
    skills_read_max_chars: int = 8000
    structured_tool_results: bool = True
    tool_result_content_chars: int = 12000
    patch_verify_after_apply: bool = True
    patch_verify_python_syntax: bool = False
    patch_fuzzy_apply: bool = False
    test_plan_max_commands: int = 5
    test_output_max_chars: int = 12000
    test_failure_context_lines: int = 4
    flaky_retry_count: int = 1
    developer_ux_enabled: bool = True
    review_after_run: bool = False
    review_bundle_max_diff_chars: int = 16000
    eval_default_max_steps: int = 8
    eval_model_call_budget: int = 8
    eval_timeout_seconds: int = 120
    eval_report_max_chars: int = 24000
    telemetry_enabled: bool = True
    telemetry_run_id: str = ""
    telemetry_max_event_chars: int = 6000
    telemetry_jsonl: bool = True
    prompt_profile: str = "auto"
    prompt_max_chars: int = 0
    prompt_include_action_reference: bool = True
    prompt_preview_max_chars: int = 12000
    lang: str = "en"
    non_interactive: bool = False
    default_answer: str = ""

    @property
    def auto_approve(self) -> bool:
        """Return True when write and shell actions should not prompt."""

        return self.approval == "auto"

    @property
    def resolved_log_dir(self) -> Path:
        """Return the absolute run-log base directory."""

        return (self.root / self.log_dir).resolve()


def load_env() -> None:
    """Load environment variables from .env when python-dotenv is installed."""

    if load_dotenv is not None:
        load_dotenv()


def require_api_key(provider: str = "openai", api_key_env: str = "OPENAI_API_KEY") -> str:
    """Return the configured API key for providers that require one, or raise clearly."""

    if not get_provider_info(provider).requires_api_key:
        return ""
    env_name = api_key_env or "OPENAI_API_KEY"
    api_key = os.getenv(env_name)
    if not api_key:
        raise RuntimeError(
            f"{env_name} bulunamadı. .env dosyası oluşturun veya ortam değişkeni olarak ayarlayın."
        )
    return api_key


def default_model() -> str:
    """Return the configured model name."""

    return os.getenv("MINICODEX_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.5")


def default_model_base_url() -> str:
    """Return the configured OpenAI-compatible base URL, if any."""

    return os.getenv("MINICODEX_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL", "")


def default_model_api_key_env() -> str:
    """Return the environment variable name used for API key lookup."""

    return os.getenv("MINICODEX_API_KEY_ENV", "OPENAI_API_KEY")


def default_provider() -> str:
    """Return the configured model provider."""

    return os.getenv("MINICODEX_PROVIDER", "openai")


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def apply_project_config(
    config: AgentConfig,
    *,
    explicit_options: set[str] | None = None,
) -> AgentConfig:
    """Apply .minicodex/config.json defaults to runtime config.

    CLI flags in explicit_options win over project config. This keeps project
    defaults convenient while preserving user intent for one-off runs.
    """

    if not config.project_config_enabled:
        return config

    from .project_settings import read_project_config  # local import avoids cycle

    project = read_project_config(config.root)
    if not bool(project.get("auto_apply_project_config", True)):
        return config

    explicit_options = explicit_options or set()
    updates: dict[str, Any] = {}
    if "provider" not in explicit_options:
        updates["provider"] = str(project.get("preferred_provider", config.provider))
    if "model" not in explicit_options:
        preferred_model = str(project.get("preferred_model", "")).strip()
        if preferred_model:
            updates["model"] = preferred_model
    if "approval" not in explicit_options:
        updates["approval"] = str(project.get("default_approval", config.approval))
    if "safety_profile" not in explicit_options:
        updates["safety_profile"] = str(
            project.get("default_safety_profile", config.safety_profile)
        )
    if "test_command" not in explicit_options:
        updates["test_command"] = str(project.get("default_test_command", config.test_command))
    if "max_steps" not in explicit_options:
        updates["max_steps"] = _as_int(project.get("default_max_steps"), config.max_steps)
    if "allow_network_commands" not in explicit_options:
        updates["allow_network_commands"] = bool(
            project.get("allow_network_commands", config.allow_network_commands)
        )
    if "sandbox_mode" not in explicit_options:
        updates["sandbox_mode"] = str(project.get("sandbox_mode", config.sandbox_mode))
    if "sandbox_image" not in explicit_options:
        updates["sandbox_image"] = str(project.get("sandbox_image", config.sandbox_image))
    if "sandbox_network" not in explicit_options:
        updates["sandbox_network"] = str(project.get("sandbox_network", config.sandbox_network))
    if "sandbox_cpus" not in explicit_options:
        updates["sandbox_cpus"] = str(project.get("sandbox_cpus", config.sandbox_cpus))
    if "sandbox_memory" not in explicit_options:
        updates["sandbox_memory"] = str(project.get("sandbox_memory", config.sandbox_memory))
    if "sandbox_pids_limit" not in explicit_options:
        updates["sandbox_pids_limit"] = _as_int(
            project.get("sandbox_pids_limit"), config.sandbox_pids_limit
        )
    if "sandbox_workspace_mode" not in explicit_options:
        updates["sandbox_workspace_mode"] = str(
            project.get("sandbox_workspace_mode", config.sandbox_workspace_mode)
        )
    if "sandbox_keep_workspace" not in explicit_options:
        updates["sandbox_keep_workspace"] = bool(
            project.get("sandbox_keep_workspace", config.sandbox_keep_workspace)
        )
    if "sandbox_max_file_bytes" not in explicit_options:
        updates["sandbox_max_file_bytes"] = _as_int(
            project.get("sandbox_max_file_bytes"), config.sandbox_max_file_bytes
        )
    if "agent_workspace_mode" not in explicit_options:
        updates["agent_workspace_mode"] = str(
            project.get("agent_workspace_mode", config.agent_workspace_mode)
        )
    if "agent_workspace_apply" not in explicit_options:
        updates["agent_workspace_apply"] = str(
            project.get("agent_workspace_apply", config.agent_workspace_apply)
        )
    if "agent_workspace_keep" not in explicit_options:
        updates["agent_workspace_keep"] = bool(
            project.get("agent_workspace_keep", config.agent_workspace_keep)
        )
    if "agent_workspace_max_file_bytes" not in explicit_options:
        updates["agent_workspace_max_file_bytes"] = _as_int(
            project.get("agent_workspace_max_file_bytes"), config.agent_workspace_max_file_bytes
        )
    if "agent_workspace_diff_max_chars" not in explicit_options:
        updates["agent_workspace_diff_max_chars"] = _as_int(
            project.get("agent_workspace_diff_max_chars"), config.agent_workspace_diff_max_chars
        )
    if "allow_github_api_writes" not in explicit_options:
        updates["allow_github_api_writes"] = bool(
            project.get("allow_github_api_writes", config.allow_github_api_writes)
        )
    if "log_enabled" not in explicit_options:
        updates["log_enabled"] = bool(project.get("log_enabled", config.log_enabled))
    if "log_redaction" not in explicit_options:
        updates["log_redaction"] = bool(project.get("log_redaction", config.log_redaction))
    if "max_log_value_chars" not in explicit_options:
        updates["max_log_value_chars"] = _as_int(
            project.get("max_log_value_chars"), config.max_log_value_chars
        )
    if "auto_snapshot_before_edit" not in explicit_options:
        updates["auto_snapshot_before_edit"] = bool(
            project.get("auto_snapshot_before_edit", config.auto_snapshot_before_edit)
        )
    if "scan_secrets_before_pr" not in explicit_options:
        updates["scan_secrets_before_pr"] = bool(
            project.get("scan_secrets_before_pr", config.scan_secrets_before_pr)
        )
    if "untrusted_workspace" not in explicit_options:
        updates["untrusted_workspace"] = bool(
            project.get("untrusted_workspace", config.untrusted_workspace)
        )
    if "require_trusted_workspace_for_writes" not in explicit_options:
        updates["require_trusted_workspace_for_writes"] = bool(
            project.get(
                "require_trusted_workspace_for_writes", config.require_trusted_workspace_for_writes
            )
        )
    if "security_audit_max_files" not in explicit_options:
        updates["security_audit_max_files"] = _as_int(
            project.get("security_audit_max_files"), config.security_audit_max_files
        )
    if "security_audit_report_max_chars" not in explicit_options:
        updates["security_audit_report_max_chars"] = _as_int(
            project.get("security_audit_report_max_chars"), config.security_audit_report_max_chars
        )
    if "external_security_timeout_seconds" not in explicit_options:
        updates["external_security_timeout_seconds"] = _as_int(
            project.get("external_security_timeout_seconds"),
            config.external_security_timeout_seconds,
        )
    if "max_agent_batch_size" not in explicit_options:
        updates["max_agent_batch_size"] = _as_int(
            project.get("max_agent_batch_size"), config.max_agent_batch_size
        )
    if "multi_agent_thread_max_messages" not in explicit_options:
        updates["multi_agent_thread_max_messages"] = _as_int(
            project.get("multi_agent_thread_max_messages"), config.multi_agent_thread_max_messages
        )
    if "multi_agent_result_max_chars" not in explicit_options:
        updates["multi_agent_result_max_chars"] = _as_int(
            project.get("multi_agent_result_max_chars"), config.multi_agent_result_max_chars
        )
    if "multi_agent_allow_parallel_writes" not in explicit_options:
        updates["multi_agent_allow_parallel_writes"] = bool(
            project.get(
                "multi_agent_allow_parallel_writes", config.multi_agent_allow_parallel_writes
            )
        )
    if "long_horizon_enabled" not in explicit_options:
        updates["long_horizon_enabled"] = bool(
            project.get("long_horizon_enabled", config.long_horizon_enabled)
        )
    if "long_horizon_run_id" not in explicit_options:
        updates["long_horizon_run_id"] = str(
            project.get("long_horizon_run_id", config.long_horizon_run_id)
        )
    if "long_horizon_auto_checkpoint_interval" not in explicit_options:
        updates["long_horizon_auto_checkpoint_interval"] = _as_int(
            project.get("long_horizon_auto_checkpoint_interval"),
            config.long_horizon_auto_checkpoint_interval,
        )
    if "long_horizon_resume_max_chars" not in explicit_options:
        updates["long_horizon_resume_max_chars"] = _as_int(
            project.get("long_horizon_resume_max_chars"), config.long_horizon_resume_max_chars
        )
    if "checkpoint_max_observation_chars" not in explicit_options:
        updates["checkpoint_max_observation_chars"] = _as_int(
            project.get("checkpoint_max_observation_chars"), config.checkpoint_max_observation_chars
        )
    if "enabled_plugins" not in explicit_options:
        plugins = project.get("enabled_plugins", list(config.enabled_plugins))
        if isinstance(plugins, list):
            updates["enabled_plugins"] = tuple(str(item) for item in plugins if str(item).strip())
    if "policy_file" not in explicit_options:
        updates["policy_file"] = str(project.get("policy_file", config.policy_file))

    if "skills_enabled" not in explicit_options:
        updates["skills_enabled"] = bool(project.get("skills_enabled", config.skills_enabled))
    if "skills_max_selected" not in explicit_options:
        updates["skills_max_selected"] = _as_int(
            project.get("skills_max_selected"), config.skills_max_selected
        )
    if "skills_max_summary_chars" not in explicit_options:
        updates["skills_max_summary_chars"] = _as_int(
            project.get("skills_max_summary_chars"), config.skills_max_summary_chars
        )
    if "skills_read_max_chars" not in explicit_options:
        updates["skills_read_max_chars"] = _as_int(
            project.get("skills_read_max_chars"), config.skills_read_max_chars
        )

    if "structured_tool_results" not in explicit_options:
        updates["structured_tool_results"] = bool(
            project.get("structured_tool_results", config.structured_tool_results)
        )
    if "tool_result_content_chars" not in explicit_options:
        updates["tool_result_content_chars"] = _as_int(
            project.get("tool_result_content_chars"), config.tool_result_content_chars
        )
    if "patch_verify_after_apply" not in explicit_options:
        updates["patch_verify_after_apply"] = bool(
            project.get("patch_verify_after_apply", config.patch_verify_after_apply)
        )
    if "patch_verify_python_syntax" not in explicit_options:
        updates["patch_verify_python_syntax"] = bool(
            project.get("patch_verify_python_syntax", config.patch_verify_python_syntax)
        )
    if "patch_fuzzy_apply" not in explicit_options:
        updates["patch_fuzzy_apply"] = bool(
            project.get("patch_fuzzy_apply", config.patch_fuzzy_apply)
        )

    if "test_plan_max_commands" not in explicit_options:
        updates["test_plan_max_commands"] = _as_int(
            project.get("test_plan_max_commands"), config.test_plan_max_commands
        )
    if "test_output_max_chars" not in explicit_options:
        updates["test_output_max_chars"] = _as_int(
            project.get("test_output_max_chars"), config.test_output_max_chars
        )
    if "test_failure_context_lines" not in explicit_options:
        updates["test_failure_context_lines"] = _as_int(
            project.get("test_failure_context_lines"), config.test_failure_context_lines
        )
    if "flaky_retry_count" not in explicit_options:
        updates["flaky_retry_count"] = _as_int(
            project.get("flaky_retry_count"), config.flaky_retry_count
        )
    if "developer_ux_enabled" not in explicit_options:
        updates["developer_ux_enabled"] = bool(
            project.get("developer_ux_enabled", config.developer_ux_enabled)
        )
    if "review_after_run" not in explicit_options:
        updates["review_after_run"] = bool(project.get("review_after_run", config.review_after_run))
    if "review_bundle_max_diff_chars" not in explicit_options:
        updates["review_bundle_max_diff_chars"] = _as_int(
            project.get("review_bundle_max_diff_chars"), config.review_bundle_max_diff_chars
        )
    if "eval_default_max_steps" not in explicit_options:
        updates["eval_default_max_steps"] = _as_int(
            project.get("eval_default_max_steps"), config.eval_default_max_steps
        )
    if "eval_model_call_budget" not in explicit_options:
        updates["eval_model_call_budget"] = _as_int(
            project.get("eval_model_call_budget"), config.eval_model_call_budget
        )
    if "eval_timeout_seconds" not in explicit_options:
        updates["eval_timeout_seconds"] = _as_int(
            project.get("eval_timeout_seconds"), config.eval_timeout_seconds
        )
    if "eval_report_max_chars" not in explicit_options:
        updates["eval_report_max_chars"] = _as_int(
            project.get("eval_report_max_chars"), config.eval_report_max_chars
        )
    if "telemetry_enabled" not in explicit_options:
        updates["telemetry_enabled"] = bool(
            project.get("telemetry_enabled", config.telemetry_enabled)
        )
    if "telemetry_run_id" not in explicit_options:
        updates["telemetry_run_id"] = str(project.get("telemetry_run_id", config.telemetry_run_id))
    if "telemetry_max_event_chars" not in explicit_options:
        updates["telemetry_max_event_chars"] = _as_int(
            project.get("telemetry_max_event_chars"), config.telemetry_max_event_chars
        )
    if "telemetry_jsonl" not in explicit_options:
        updates["telemetry_jsonl"] = bool(project.get("telemetry_jsonl", config.telemetry_jsonl))
    if "prompt_profile" not in explicit_options:
        updates["prompt_profile"] = str(project.get("prompt_profile", config.prompt_profile))
    if "prompt_max_chars" not in explicit_options:
        updates["prompt_max_chars"] = _as_int(
            project.get("prompt_max_chars"), config.prompt_max_chars
        )
    if "prompt_include_action_reference" not in explicit_options:
        updates["prompt_include_action_reference"] = bool(
            project.get("prompt_include_action_reference", config.prompt_include_action_reference)
        )
    if "prompt_preview_max_chars" not in explicit_options:
        updates["prompt_preview_max_chars"] = _as_int(
            project.get("prompt_preview_max_chars"), config.prompt_preview_max_chars
        )

    if "lang" not in explicit_options:
        updates["lang"] = str(project.get("lang", config.lang))
    if "non_interactive" not in explicit_options:
        updates["non_interactive"] = bool(project.get("non_interactive", config.non_interactive))
    if "default_answer" not in explicit_options:
        updates["default_answer"] = str(project.get("default_answer", config.default_answer))
    if "model_timeout_seconds" not in explicit_options:
        updates["model_timeout_seconds"] = _as_int(
            project.get("model_timeout_seconds"), config.model_timeout_seconds
        )
    if "model_max_output_tokens" not in explicit_options:
        updates["model_max_output_tokens"] = _as_int(
            project.get("model_max_output_tokens"), config.model_max_output_tokens
        )
    if "model_max_retries" not in explicit_options:
        updates["model_max_retries"] = _as_int(
            project.get("model_max_retries"), config.model_max_retries
        )
    if "model_retry_backoff_seconds" not in explicit_options:
        updates["model_retry_backoff_seconds"] = _as_float(
            project.get("model_retry_backoff_seconds"), config.model_retry_backoff_seconds
        )
    if "model_repair_attempts" not in explicit_options:
        updates["model_repair_attempts"] = _as_int(
            project.get("model_repair_attempts"), config.model_repair_attempts
        )
    if "model_structured_output" not in explicit_options:
        updates["model_structured_output"] = bool(
            project.get("model_structured_output", config.model_structured_output)
        )
    if "model_call_budget" not in explicit_options:
        updates["model_call_budget"] = _as_int(
            project.get("model_call_budget"), config.model_call_budget
        )
    if "model_cost_budget_usd" not in explicit_options:
        updates["model_cost_budget_usd"] = _as_float(
            project.get("model_cost_budget_usd"), config.model_cost_budget_usd
        )
    if "model_input_price_per_million" not in explicit_options:
        updates["model_input_price_per_million"] = _as_float(
            project.get("model_input_price_per_million"), config.model_input_price_per_million
        )
    if "model_output_price_per_million" not in explicit_options:
        updates["model_output_price_per_million"] = _as_float(
            project.get("model_output_price_per_million"), config.model_output_price_per_million
        )
    if "model_base_url" not in explicit_options:
        updates["model_base_url"] = str(project.get("model_base_url", config.model_base_url))
    if "model_api_key_env" not in explicit_options:
        updates["model_api_key_env"] = str(
            project.get("model_api_key_env", config.model_api_key_env)
        )
    if "model_reasoning_effort" not in explicit_options:
        updates["model_reasoning_effort"] = str(
            project.get("model_reasoning_effort", config.model_reasoning_effort)
        )
    if "model_stream" not in explicit_options:
        updates["model_stream"] = bool(project.get("model_stream", config.model_stream))
    if "model_stream_ui" not in explicit_options:
        updates["model_stream_ui"] = bool(project.get("model_stream_ui", config.model_stream_ui))
    if "model_action_protocol" not in explicit_options:
        updates["model_action_protocol"] = str(
            project.get("model_action_protocol", config.model_action_protocol)
        )
    if "context_enabled" not in explicit_options:
        updates["context_enabled"] = bool(project.get("context_enabled", config.context_enabled))
    if "context_max_chars" not in explicit_options:
        updates["context_max_chars"] = _as_int(
            project.get("context_max_chars"), config.context_max_chars
        )
    if "context_instruction_max_chars" not in explicit_options:
        updates["context_instruction_max_chars"] = _as_int(
            project.get("context_instruction_max_chars"), config.context_instruction_max_chars
        )
    if "context_relevant_files" not in explicit_options:
        updates["context_relevant_files"] = _as_int(
            project.get("context_relevant_files"), config.context_relevant_files
        )
    if "context_observation_chars_each" not in explicit_options:
        updates["context_observation_chars_each"] = _as_int(
            project.get("context_observation_chars_each"), config.context_observation_chars_each
        )

    # Keep values inside supported enums even if a user manually edited config badly.
    if updates.get("approval") not in {"ask", "auto"}:
        updates.pop("approval", None)
    if updates.get("safety_profile") not in {"strict", "balanced", "permissive"}:
        updates.pop("safety_profile", None)
    if updates.get("provider") not in set(list_provider_names()):
        updates.pop("provider", None)
    if updates.get("sandbox_mode") not in {"restricted", "docker", "podman"}:
        updates.pop("sandbox_mode", None)
    if updates.get("sandbox_network") not in {"none", "default", "bridge", "host"}:
        updates.pop("sandbox_network", None)
    if updates.get("sandbox_workspace_mode") not in {"copy", "mount"}:
        updates.pop("sandbox_workspace_mode", None)
    if updates.get("sandbox_pids_limit", config.sandbox_pids_limit) < 1:
        updates["sandbox_pids_limit"] = 1
    if updates.get("sandbox_max_file_bytes", config.sandbox_max_file_bytes) < 1024:
        updates["sandbox_max_file_bytes"] = 1024
    if updates.get("lang") not in {"en", "tr"}:
        updates.pop("lang", None)
    if updates.get("model_reasoning_effort") not in {
        "",
        "none",
        "off",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }:
        updates.pop("model_reasoning_effort", None)
    if updates.get("model_action_protocol") not in {"auto", "json_text", "tool_calls"}:
        updates.pop("model_action_protocol", None)
    if (
        "model_api_key_env" in updates
        and not str(updates["model_api_key_env"]).replace("_", "").isalnum()
    ):
        updates.pop("model_api_key_env", None)
    if updates.get("context_max_chars", config.context_max_chars) < 2000:
        updates["context_max_chars"] = 2000
    if updates.get("context_instruction_max_chars", config.context_instruction_max_chars) < 0:
        updates["context_instruction_max_chars"] = 0
    if updates.get("context_relevant_files", config.context_relevant_files) < 0:
        updates["context_relevant_files"] = 0
    if updates.get("context_observation_chars_each", config.context_observation_chars_each) < 400:
        updates["context_observation_chars_each"] = 400
    if updates.get("skills_max_selected", config.skills_max_selected) < 0:
        updates["skills_max_selected"] = 0
    if updates.get("skills_max_summary_chars", config.skills_max_summary_chars) < 200:
        updates["skills_max_summary_chars"] = 200
    if updates.get("skills_read_max_chars", config.skills_read_max_chars) < 1000:
        updates["skills_read_max_chars"] = 1000
    if updates.get("max_agent_batch_size", config.max_agent_batch_size) < 1:
        updates["max_agent_batch_size"] = 1
    if (
        updates.get(
            "long_horizon_auto_checkpoint_interval", config.long_horizon_auto_checkpoint_interval
        )
        < 0
    ):
        updates["long_horizon_auto_checkpoint_interval"] = 0
    if updates.get("long_horizon_resume_max_chars", config.long_horizon_resume_max_chars) < 4000:
        updates["long_horizon_resume_max_chars"] = 4000
    if (
        updates.get("checkpoint_max_observation_chars", config.checkpoint_max_observation_chars)
        < 1000
    ):
        updates["checkpoint_max_observation_chars"] = 1000
    if updates.get("test_plan_max_commands", config.test_plan_max_commands) < 1:
        updates["test_plan_max_commands"] = 1
    if updates.get("test_output_max_chars", config.test_output_max_chars) < 1000:
        updates["test_output_max_chars"] = 1000
    if updates.get("test_failure_context_lines", config.test_failure_context_lines) < 0:
        updates["test_failure_context_lines"] = 0
    if updates.get("flaky_retry_count", config.flaky_retry_count) < 0:
        updates["flaky_retry_count"] = 0
    if updates.get("review_bundle_max_diff_chars", config.review_bundle_max_diff_chars) < 1000:
        updates["review_bundle_max_diff_chars"] = 1000
    if updates.get("eval_default_max_steps", config.eval_default_max_steps) < 1:
        updates["eval_default_max_steps"] = 1
    if updates.get("eval_model_call_budget", config.eval_model_call_budget) < 1:
        updates["eval_model_call_budget"] = 1
    if updates.get("eval_timeout_seconds", config.eval_timeout_seconds) < 1:
        updates["eval_timeout_seconds"] = 1
    if updates.get("eval_report_max_chars", config.eval_report_max_chars) < 2000:
        updates["eval_report_max_chars"] = 2000
    if updates.get("telemetry_max_event_chars", config.telemetry_max_event_chars) < 1000:
        updates["telemetry_max_event_chars"] = 1000
    if "telemetry_run_id" in updates:
        run_id = str(updates["telemetry_run_id"]).strip()
        if run_id and (
            Path(run_id).is_absolute() or ".." in Path(run_id).parts or len(run_id) > 96
        ):
            updates.pop("telemetry_run_id", None)
    if updates.get("security_audit_max_files", config.security_audit_max_files) < 1:
        updates["security_audit_max_files"] = 1
    if (
        updates.get("security_audit_report_max_chars", config.security_audit_report_max_chars)
        < 4000
    ):
        updates["security_audit_report_max_chars"] = 4000
    if (
        updates.get("external_security_timeout_seconds", config.external_security_timeout_seconds)
        < 1
    ):
        updates["external_security_timeout_seconds"] = 1
    if "policy_file" in updates and (
        Path(str(updates["policy_file"])).is_absolute()
        or ".." in Path(str(updates["policy_file"])).parts
    ):
        updates.pop("policy_file", None)

    return replace(config, **updates)
