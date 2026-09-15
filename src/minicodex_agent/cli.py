"""Command-line interface for MiniCodex."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .agent import MiniCodexAgent
from .config import (
    AgentConfig,
    apply_project_config,
    default_model,
    default_model_api_key_env,
    default_model_base_url,
    default_provider,
    load_env,
    require_api_key,
)
from .demo_project import create_demo_project
from .dev_experience import create_review_bundle, export_ide_bridge, render_tui_panel
from .eval_runner import (
    compare_eval_baselines,
    eval_baseline_plan,
    eval_coverage_report,
    init_eval_baselines,
    init_eval_suite,
    list_eval_baselines,
    list_eval_tasks,
    run_eval_suite,
    run_eval_task,
)
from .failure_taxonomy import build_failure_taxonomy_dashboard
from .github_integration import (
    detect_github_workflows,
    generate_github_app_manifest,
    init_github_action,
    init_github_webhook_server,
    parse_pr_comment_command,
    prepare_github_artifact_upload,
)
from .i18n import tr
from .interactive import run_interactive_session
from .model_pricing import list_model_prices
from .prompt_ab import run_prompt_ab_comparison
from .prompt_engine import PROMPT_PROFILES, list_prompt_profiles, render_prompt_preview
from .provider_registry import get_provider_info, list_provider_names
from .quality_gate import (
    DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
    build_test_matrix_plan,
    clean_generated_artifacts,
    final_readiness_report,
    release_package_manifest,
)
from .release_tools import project_health_report
from .security_audit import scan_repo_instructions, security_audit_report
from .semantic_index import (
    build_semantic_index,
    find_symbol_references,
    inspect_routes,
    semantic_capability_report,
)
from .setup_wizard import run_setup_wizard
from .telemetry import (
    export_telemetry_bundle,
    read_telemetry_run,
    render_optimization_dashboard,
    summarize_telemetry,
)


def _explicit_cli_options(argv: list[str]) -> set[str]:
    """Return normalized option names explicitly present in argv."""

    mapping = {
        "--provider": "provider",
        "--model": "model",
        "--approval": "approval",
        "--safety-profile": "safety_profile",
        "--test-command": "test_command",
        "--max-steps": "max_steps",
        "--allow-network-commands": "allow_network_commands",
        "--allow-github-api-writes": "allow_github_api_writes",
        "--no-github-api-writes": "allow_github_api_writes",
        "--sandbox-mode": "sandbox_mode",
        "--sandbox-image": "sandbox_image",
        "--sandbox-network": "sandbox_network",
        "--sandbox-cpus": "sandbox_cpus",
        "--sandbox-memory": "sandbox_memory",
        "--sandbox-pids-limit": "sandbox_pids_limit",
        "--sandbox-workspace-mode": "sandbox_workspace_mode",
        "--sandbox-keep-workspace": "sandbox_keep_workspace",
        "--sandbox-max-file-bytes": "sandbox_max_file_bytes",
        "--agent-workspace-mode": "agent_workspace_mode",
        "--agent-workspace-apply": "agent_workspace_apply",
        "--agent-workspace-keep": "agent_workspace_keep",
        "--agent-workspace-max-file-bytes": "agent_workspace_max_file_bytes",
        "--agent-workspace-diff-max-chars": "agent_workspace_diff_max_chars",
        "--no-log": "log_enabled",
        "--log-dir": "log_dir",
        "--no-auto-snapshot-before-edit": "auto_snapshot_before_edit",
        "--model-timeout-seconds": "model_timeout_seconds",
        "--model-max-output-tokens": "model_max_output_tokens",
        "--model-max-retries": "model_max_retries",
        "--model-repair-attempts": "model_repair_attempts",
        "--model-retry-backoff-seconds": "model_retry_backoff_seconds",
        "--no-structured-output": "model_structured_output",
        "--model-call-budget": "model_call_budget",
        "--model-cost-budget-usd": "model_cost_budget_usd",
        "--model-input-price-per-million": "model_input_price_per_million",
        "--model-output-price-per-million": "model_output_price_per_million",
        "--model-base-url": "model_base_url",
        "--model-api-key-env": "model_api_key_env",
        "--model-reasoning-effort": "model_reasoning_effort",
        "--model-stream": "model_stream",
        "--model-stream-ui": "model_stream_ui",
        "--model-action-protocol": "model_action_protocol",
        "--no-context": "context_enabled",
        "--context-max-chars": "context_max_chars",
        "--context-instruction-max-chars": "context_instruction_max_chars",
        "--context-relevant-files": "context_relevant_files",
        "--context-observation-chars-each": "context_observation_chars_each",
        "--no-skills": "skills_enabled",
        "--skills-max-selected": "skills_max_selected",
        "--skills-max-summary-chars": "skills_max_summary_chars",
        "--skills-read-max-chars": "skills_read_max_chars",
        "--no-structured-tool-results": "structured_tool_results",
        "--tool-result-content-chars": "tool_result_content_chars",
        "--no-patch-verify-after-apply": "patch_verify_after_apply",
        "--patch-verify-python-syntax": "patch_verify_python_syntax",
        "--patch-fuzzy-apply": "patch_fuzzy_apply",
        "--test-plan-max-commands": "test_plan_max_commands",
        "--test-output-max-chars": "test_output_max_chars",
        "--test-failure-context-lines": "test_failure_context_lines",
        "--flaky-retry-count": "flaky_retry_count",
        "--review-after-run": "review_after_run",
        "--review-bundle-max-diff-chars": "review_bundle_max_diff_chars",
        "--eval-default-max-steps": "eval_default_max_steps",
        "--eval-model-call-budget": "eval_model_call_budget",
        "--eval-timeout-seconds": "eval_timeout_seconds",
        "--eval-report-max-chars": "eval_report_max_chars",
        "--no-telemetry": "telemetry_enabled",
        "--telemetry-run-id": "telemetry_run_id",
        "--telemetry-max-event-chars": "telemetry_max_event_chars",
        "--no-telemetry-jsonl": "telemetry_jsonl",
        "--prompt-profile": "prompt_profile",
        "--prompt-max-chars": "prompt_max_chars",
        "--no-prompt-action-reference": "prompt_include_action_reference",
        "--prompt-preview-max-chars": "prompt_preview_max_chars",
        "--no-scan-secrets-before-pr": "scan_secrets_before_pr",
        "--untrusted-workspace": "untrusted_workspace",
        "--require-trusted-workspace-for-writes": "require_trusted_workspace_for_writes",
        "--security-audit-max-files": "security_audit_max_files",
        "--security-audit-report-max-chars": "security_audit_report_max_chars",
        "--external-security-timeout-seconds": "external_security_timeout_seconds",
        "--max-agent-batch-size": "max_agent_batch_size",
        "--multi-agent-thread-max-messages": "multi_agent_thread_max_messages",
        "--multi-agent-result-max-chars": "multi_agent_result_max_chars",
        "--multi-agent-allow-parallel-writes": "multi_agent_allow_parallel_writes",
        "--long-horizon": "long_horizon_enabled",
        "--long-horizon-run-id": "long_horizon_run_id",
        "--long-horizon-auto-checkpoint-interval": "long_horizon_auto_checkpoint_interval",
        "--long-horizon-resume-max-chars": "long_horizon_resume_max_chars",
        "--checkpoint-max-observation-chars": "checkpoint_max_observation_chars",
        "--policy-file": "policy_file",
        "--lang": "lang",
        "--non-interactive": "non_interactive",
        "--default-answer": "default_answer",
    }
    return {name for flag, name in mapping.items() if flag in argv}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Developer-preview local Codex-like coding agent.")

    parser.add_argument(
        "goal",
        nargs="?",
        help="Agent goal. Example: 'Inspect the project, find issues, and run tests.'",
    )
    parser.add_argument("--root", default=".", help="Project folder. Default: current directory.")
    parser.add_argument("--model", default=default_model(), help="Model name to use.")
    parser.add_argument(
        "--provider",
        choices=list_provider_names(),
        default=default_provider(),
        help="Model provider: openai, openai_compatible, ollama/lmstudio/llama_cpp, stub, or echo.",
    )
    parser.add_argument("--max-steps", type=int, default=30, help="Maximum number of agent steps.")
    parser.add_argument(
        "--approval",
        choices=["ask", "auto"],
        default="ask",
        help="Approval mode for writes and command execution. ask prompts, auto approves automatically.",
    )
    parser.add_argument(
        "--safety-profile",
        choices=["strict", "balanced", "permissive"],
        default="strict",
        help="Command execution safety profile. Default: strict.",
    )
    parser.add_argument(
        "--test-command",
        default="auto",
        help="Test command used by run_tests. Default: auto.",
    )

    parser.add_argument(
        "--allow-network-commands",
        action="store_true",
        help="Allow network/install commands such as pip, npm, curl, and wget as a separate permission; manual approval is still required.",
    )
    github_writes_group = parser.add_mutually_exclusive_group()
    github_writes_group.add_argument(
        "--allow-github-api-writes",
        dest="allow_github_api_writes",
        action="store_true",
        help="Allow real GitHub API write operations such as creating issues or PRs; manual approval and a token are still required.",
    )
    github_writes_group.add_argument(
        "--no-github-api-writes",
        dest="allow_github_api_writes",
        action="store_false",
        help="Explicitly disable GitHub API write operations and override the project config value. This is the safe default.",
    )
    parser.add_argument(
        "--sandbox-mode",
        choices=["restricted", "docker", "podman"],
        default="restricted",
        help="Command execution mode. restricted uses local shell=False subprocesses; docker/podman use a container sandbox.",
    )
    parser.add_argument(
        "--sandbox-image",
        default="python:3.12-slim",
        help="Docker/Podman sandbox container image. Default: python:3.12-slim.",
    )
    parser.add_argument(
        "--sandbox-network",
        choices=["none", "default", "bridge", "host"],
        default="none",
        help="Container sandbox network policy. Without allow-network, the effective network remains none.",
    )
    parser.add_argument(
        "--sandbox-cpus",
        default="1",
        help="Container sandbox CPU limit, for example 1 or 2.",
    )
    parser.add_argument(
        "--sandbox-memory",
        default="1g",
        help="Container sandbox memory limit, for example 1g or 2048m.",
    )
    parser.add_argument(
        "--sandbox-pids-limit",
        type=int,
        default=256,
        help="Container sandbox process/PID limit.",
    )
    parser.add_argument(
        "--sandbox-workspace-mode",
        choices=["copy", "mount"],
        default="copy",
        help="Container workspace mode. copy creates a filtered isolated copy; mount bind-mounts the project root.",
    )
    parser.add_argument(
        "--sandbox-keep-workspace",
        action="store_true",
        help="Keep the copied container sandbox workspace for debugging instead of deleting it.",
    )
    parser.add_argument(
        "--sandbox-max-file-bytes",
        type=int,
        default=2000000,
        help="Maximum bytes per file copied into the container workspace.",
    )
    parser.add_argument(
        "--agent-workspace-mode",
        choices=["direct", "isolated"],
        default="direct",
        help="Agent run workspace mode. direct: existing behavior; isolated: all reads/writes/patches run on a filtered workspace copy.",
    )
    parser.add_argument(
        "--agent-workspace-apply",
        choices=["never", "ask", "auto"],
        default="never",
        help="What to do with isolated workspace changes at finish: never export only, ask before applying, or auto apply to original root.",
    )
    parser.add_argument(
        "--agent-workspace-keep",
        action="store_true",
        help="Keep the isolated agent workspace copy for debugging instead of removing it after diff/export.",
    )
    parser.add_argument(
        "--agent-workspace-max-file-bytes",
        type=int,
        default=2000000,
        help="Maximum file size copied into the isolated agent workspace.",
    )
    parser.add_argument(
        "--agent-workspace-diff-max-chars",
        type=int,
        default=24000,
        help="Maximum isolated workspace diff preview characters saved/rendered at finish.",
    )
    parser.add_argument(
        "--create-branch",
        action="store_true",
        help="Create a minicodex/... branch before starting in Git repositories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate file writes and command execution without making real changes.",
    )
    parser.add_argument(
        "--no-project-config",
        action="store_true",
        help="Do not apply .minicodex/config.json settings at runtime.",
    )
    parser.add_argument(
        "--no-project-policy",
        action="store_true",
        help="Disable .minicodex/policy.json write/command policy checks.",
    )
    parser.add_argument(
        "--log-dir",
        default=".minicodex/runs",
        help="Directory where run logs are stored.",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Disable RunLogger records completely; no files are written under .minicodex/runs.",
    )
    parser.add_argument(
        "--no-auto-snapshot-before-edit",
        action="store_true",
        help="Disable the automatic snapshot taken before the first write, patch, or refactor.",
    )
    parser.add_argument(
        "--no-scan-secrets-before-pr",
        action="store_true",
        help="Disable the high/critical secret-scan precheck before preparing or creating PRs.",
    )
    parser.add_argument(
        "--untrusted-workspace",
        action="store_true",
        help="Unknown repository mode: blocks high-impact write, command, and GitHub actions under auto approval and raises the risk in security reports.",
    )
    parser.add_argument(
        "--require-trusted-workspace-for-writes",
        action="store_true",
        help="Block file writes, patches, and GitHub write actions until the workspace is explicitly trusted.",
    )
    parser.add_argument(
        "--security-audit-max-files",
        type=int,
        default=1000,
        help="Maximum number of files scanned by the built-in SAST/security audit.",
    )
    parser.add_argument(
        "--security-audit-report-max-chars",
        type=int,
        default=24000,
        help="Maximum characters for security_audit_report and --security-audit output.",
    )
    parser.add_argument(
        "--external-security-timeout-seconds",
        type=int,
        default=180,
        help="Timeout in seconds for external security tools such as Semgrep, pip-audit, and gitleaks.",
    )
    parser.add_argument(
        "--max-agent-batch-size",
        type=int,
        default=5,
        help="Config-based maximum task/agent limit for run_task_batch and run_multi_agent_work.",
    )
    parser.add_argument(
        "--multi-agent-thread-max-messages",
        type=int,
        default=12,
        help="Maximum number of messages retained in subagent thread/mailbox transcripts.",
    )
    parser.add_argument(
        "--multi-agent-result-max-chars",
        type=int,
        default=12000,
        help="Maximum character budget for merged multi-agent results and thread messages.",
    )
    parser.add_argument(
        "--multi-agent-allow-parallel-writes",
        action="store_true",
        help="Allow write-capable subagent roles to run in parallel; disabled by default.",
    )
    parser.add_argument(
        "--long-horizon",
        action="store_true",
        help="Enable long-horizon task mode; prioritizes resume/checkpoint tools in prompts and metadata.",
    )
    parser.add_argument(
        "--long-horizon-run-id",
        default="",
        help="Existing long-horizon run_id to resume. If empty, the model may use create_long_task.",
    )
    parser.add_argument(
        "--long-horizon-auto-checkpoint-interval",
        type=int,
        default=0,
        help="0 disables it. Values greater than 0 write automatic checkpoints at the specified step interval.",
    )
    parser.add_argument(
        "--long-horizon-resume-max-chars",
        type=int,
        default=20000,
        help="Maximum character budget for resume_long_task output.",
    )
    parser.add_argument(
        "--checkpoint-max-observation-chars",
        type=int,
        default=12000,
        help="Maximum character budget for automatic checkpoint observation summaries.",
    )
    parser.add_argument(
        "--policy-file",
        default=".minicodex/policy.json",
        help="Project policy file path. Relative paths must stay inside the root.",
    )
    parser.add_argument(
        "--model-timeout-seconds",
        type=int,
        default=60,
        help="Timeout in seconds for each OpenAI/provider call.",
    )
    parser.add_argument(
        "--model-max-output-tokens",
        type=int,
        default=2048,
        help="Maximum output token limit for model responses.",
    )
    parser.add_argument(
        "--model-max-retries",
        type=int,
        default=2,
        help="Number of retries when a provider call fails.",
    )
    parser.add_argument(
        "--model-repair-attempts",
        type=int,
        default=2,
        help="Number of schema-repair attempts for invalid JSON/actions.",
    )
    parser.add_argument(
        "--model-retry-backoff-seconds",
        type=float,
        default=1.0,
        help="Initial backoff seconds between provider retry attempts.",
    )
    parser.add_argument(
        "--no-structured-output",
        action="store_true",
        help="Disable structured JSON-schema output requests even if the provider supports them.",
    )
    parser.add_argument(
        "--model-call-budget",
        type=int,
        default=60,
        help="Maximum model calls allowed within a single run.",
    )
    parser.add_argument(
        "--model-cost-budget-usd",
        type=float,
        default=0.0,
        help="Estimated cost limit. 0 disables it; calculated when price fields are provided.",
    )
    parser.add_argument(
        "--model-input-price-per-million",
        type=float,
        default=0.0,
        help="USD price per million input tokens for cost estimation.",
    )
    parser.add_argument(
        "--model-output-price-per-million",
        type=float,
        default=0.0,
        help="USD price per million output tokens for cost estimation.",
    )
    parser.add_argument(
        "--model-base-url",
        default=default_model_base_url(),
        help="OpenAI-compatible/local endpoint base URL. Example: http://localhost:11434/v1",
    )
    parser.add_argument(
        "--model-api-key-env",
        default=default_model_api_key_env(),
        help="Environment variable used to read the API key. Default: OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--model-reasoning-effort",
        choices=["", "none", "off", "minimal", "low", "medium", "high", "xhigh"],
        default="",
        help="Reasoning effort for supported models. If empty, it is not sent.",
    )
    parser.add_argument(
        "--model-stream",
        action="store_true",
        help="Request streaming responses from providers that support them; MiniCodex still aggregates the response into one text block.",
    )
    parser.add_argument(
        "--model-stream-ui",
        action="store_true",
        help="Write streaming provider deltas to stderr in real time for debugging/local model monitoring.",
    )
    parser.add_argument(
        "--model-action-protocol",
        choices=["auto", "json_text", "tool_calls"],
        default="auto",
        help="Model action protocol. auto tries native tool_calls for local/OpenAI-compatible providers and falls back to JSON text; json_text uses the legacy protocol; tool_calls requests native Chat Completions tools.",
    )
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="Disable adding the repo instructions, relevant files, and compacted observations context pack to the model prompt.",
    )
    parser.add_argument(
        "--context-max-chars",
        type=int,
        default=22000,
        help="Approximate maximum character budget for the context pack.",
    )
    parser.add_argument(
        "--context-instruction-max-chars",
        type=int,
        default=6000,
        help="Total character budget for AGENTS.md and repository instructions.",
    )
    parser.add_argument(
        "--context-relevant-files",
        type=int,
        default=12,
        help="Number of ranked relevant files added to the prompt.",
    )
    parser.add_argument(
        "--context-observation-chars-each",
        type=int,
        default=1600,
        help="Post-compaction character budget for each older tool observation.",
    )
    parser.add_argument(
        "--no-skills",
        action="store_true",
        help="Repo-local .minicodex/skills catalog discovery and prompt hints are disabled.",
    )
    parser.add_argument(
        "--skills-max-selected",
        type=int,
        default=6,
        help="Maximum ranked repo-local skills included in the context catalog.",
    )
    parser.add_argument(
        "--skills-max-summary-chars",
        type=int,
        default=1000,
        help="Maximum summary characters per discovered skill in the context catalog.",
    )
    parser.add_argument(
        "--skills-read-max-chars",
        type=int,
        default=8000,
        help="Maximum full SKILL.md characters returned by read_skill.",
    )
    parser.add_argument(
        "--no-structured-tool-results",
        action="store_true",
        help="Disable wrapping agent observations in the TOOL_RESULT_JSON envelope.",
    )
    parser.add_argument(
        "--tool-result-content-chars",
        type=int,
        default=12000,
        help="Maximum character budget for structured tool result content fields.",
    )
    parser.add_argument(
        "--no-patch-verify-after-apply",
        action="store_true",
        help="Disable the planned file-state verification step after apply_patch.",
    )
    parser.add_argument(
        "--patch-verify-python-syntax",
        action="store_true",
        help="Run Python syntax validation when a patch touches .py files.",
    )
    parser.add_argument(
        "--patch-fuzzy-apply",
        action="store_true",
        help="Use conservative fuzzy matching when patch hunk line numbers have drifted slightly.",
    )

    parser.add_argument(
        "--test-plan-max-commands",
        type=int,
        default=5,
        help="Maximum number of commands generated for plan_tests/run_targeted_tests.",
    )
    parser.add_argument(
        "--test-output-max-chars",
        type=int,
        default=12000,
        help="Maximum characters retained in Test/CI failure-classification output.",
    )
    parser.add_argument(
        "--test-failure-context-lines",
        type=int,
        default=4,
        help="Default number of context lines read around file locations during failure analysis.",
    )
    parser.add_argument(
        "--flaky-retry-count",
        type=int,
        default=1,
        help="Rerun count recommended/configured when flakiness is suspected.",
    )
    parser.add_argument(
        "--dev-panel",
        action="store_true",
        help="Show the terminal developer panel with status and diff preview without calling the model, then exit.",
    )
    parser.add_argument(
        "--review-after-run",
        action="store_true",
        help="Create a review bundle under .minicodex/review_bundles after the run finishes.",
    )
    parser.add_argument(
        "--review-bundle-max-diff-chars",
        type=int,
        default=16000,
        help="Maximum characters for review bundle diff previews.",
    )
    parser.add_argument(
        "--export-ide-bridge",
        action="store_true",
        help="Create the .minicodex/ide/bridge.json descriptor without calling the model, then exit.",
    )
    parser.add_argument(
        "--init-evals",
        action="store_true",
        help="Create starter eval tasks under .minicodex/evals/tasks without calling the model, then exit.",
    )
    parser.add_argument(
        "--eval-overwrite",
        action="store_true",
        help="Overwrite existing files during --init-evals / --init-eval-baselines.",
    )
    parser.add_argument(
        "--init-eval-baselines",
        action="store_true",
        help="Create provider/model baseline manifests under .minicodex/evals/baselines without calling the model, then exit.",
    )
    parser.add_argument(
        "--list-eval-baselines",
        action="store_true",
        help="List registered or built-in eval baseline manifests without calling the model, then exit.",
    )
    parser.add_argument(
        "--eval-coverage-report",
        action="store_true",
        help="Generate an eval category/model baseline coverage report for Codex-like performance claims, then exit.",
    )
    parser.add_argument(
        "--eval-baseline-plan",
        metavar="BASELINE_ID",
        help="Generate an executable CLI command plan for a baseline manifest, then exit.",
    )
    parser.add_argument(
        "--compare-eval-baselines",
        nargs=2,
        metavar=("BASELINE_RUN", "CANDIDATE_RUN"),
        help="Compare two eval run reports with regression/improvement information, then exit.",
    )
    parser.add_argument(
        "--eval-min-success-delta",
        type=float,
        default=0.0,
        help="Minimum average score delta for --compare-eval-baselines.",
    )
    parser.add_argument(
        "--list-evals",
        dest="list_evals",
        action="store_true",
        help="List registered eval tasks without calling the model, then exit.",
    )
    parser.add_argument(
        "--list-eval-tasks",
        dest="list_evals",
        action="store_true",
        help="Backward-compatible alias for --list-evals.",
    )
    parser.add_argument(
        "--run-eval",
        metavar="TASK_ID",
        help="Run a specific eval task in a disposable workspace, then exit.",
    )
    parser.add_argument(
        "--run-eval-suite",
        action="store_true",
        help="Run all registered eval tasks and write an aggregate report.",
    )
    parser.add_argument(
        "--eval-run-id",
        default="",
        help="Optional run id for the eval run.",
    )
    parser.add_argument(
        "--eval-default-max-steps",
        type=int,
        default=8,
        help="Default max_steps for eval task agent runs.",
    )
    parser.add_argument(
        "--eval-model-call-budget",
        type=int,
        default=8,
        help="Default model-call budget per eval task.",
    )
    parser.add_argument(
        "--eval-timeout-seconds",
        type=int,
        default=120,
        help="Eval verification command timeout value.",
    )
    parser.add_argument(
        "--eval-report-max-chars",
        type=int,
        default=24000,
        help="Maximum characters in eval tool/CLI reports.",
    )
    parser.add_argument(
        "--no-telemetry",
        action="store_true",
        help="Disable local telemetry trace/span records.",
    )
    parser.add_argument(
        "--telemetry-run-id",
        default="",
        help="Optional run id for telemetry traces.",
    )
    parser.add_argument(
        "--telemetry-max-event-chars",
        type=int,
        default=6000,
        help="Maximum character budget for telemetry event/string fields.",
    )
    parser.add_argument(
        "--no-telemetry-jsonl",
        action="store_true",
        help="Disable the events.jsonl stream file when writing telemetry trace.json.",
    )
    parser.add_argument(
        "--telemetry-summary",
        action="store_true",
        help="Show the latest telemetry run summary without calling the model, then exit.",
    )
    parser.add_argument(
        "--read-telemetry-run",
        default="",
        help="Read the specified telemetry run id without calling the model, then exit.",
    )
    parser.add_argument(
        "--export-telemetry-bundle",
        action="store_true",
        help="Create a telemetry summary bundle without calling the model, then exit.",
    )
    parser.add_argument(
        "--model-price-table",
        action="store_true",
        help="Print the known provider/model price catalog, then exit.",
    )
    parser.add_argument(
        "--optimization-dashboard",
        action="store_true",
        help="Print the telemetry optimization dashboard report, then exit.",
    )
    parser.add_argument(
        "--failure-dashboard",
        action="store_true",
        help="Print the failure taxonomy dashboard report, then exit.",
    )
    parser.add_argument(
        "--run-prompt-ab",
        action="store_true",
        help="Run a prompt-profile A/B eval comparison, then exit.",
    )
    parser.add_argument(
        "--prompt-ab-profiles",
        default="auto,local-model",
        help="Comma-separated prompt profiles. Default: auto,local-model.",
    )
    parser.add_argument(
        "--prompt-ab-tasks",
        default="",
        help="Comma-separated eval task id list. If empty, core/early tasks are used.",
    )
    parser.add_argument(
        "--prompt-profile",
        choices=list(PROMPT_PROFILES),
        default="auto",
        help="Modular system prompt profile. auto infers from goal/provider.",
    )
    parser.add_argument(
        "--prompt-max-chars",
        type=int,
        default=0,
        help="Maximum rendered system prompt characters. 0 means unlimited.",
    )
    parser.add_argument(
        "--no-prompt-action-reference",
        action="store_true",
        help="Do not include the large generated action reference in the system prompt.",
    )
    parser.add_argument(
        "--prompt-preview-max-chars",
        type=int,
        default=12000,
        help="Maximum characters for --prompt-preview output.",
    )
    parser.add_argument(
        "--prompt-preview",
        action="store_true",
        help="Show the active prompt bundle preview without calling the model, then exit.",
    )
    parser.add_argument(
        "--list-prompt-profiles",
        action="store_true",
        help="List available prompt profiles without calling the model, then exit.",
    )

    parser.add_argument(
        "--semantic-capability-report",
        action="store_true",
        help="Generate a semantic parser/backend coverage report without calling the model, then exit.",
    )
    parser.add_argument(
        "--build-semantic-index",
        action="store_true",
        help="Generate a repository symbol/reference/route semantic index report without calling the model, then exit.",
    )
    parser.add_argument(
        "--find-symbol-references",
        metavar="SYMBOL",
        help="Find symbol definitions and cross-file references without calling the model, then exit.",
    )
    parser.add_argument(
        "--inspect-routes",
        action="store_true",
        help="Generate a framework route/API endpoint report without calling the model, then exit.",
    )
    parser.add_argument(
        "--semantic-max-files",
        type=int,
        default=1600,
        help="Maximum number of source files for the semantic index.",
    )
    parser.add_argument(
        "--semantic-max-symbols",
        type=int,
        default=1000,
        help="Maximum number of symbols for the semantic index.",
    )
    parser.add_argument(
        "--semantic-max-references",
        type=int,
        default=80,
        help="Maximum number of references for --find-symbol-references.",
    )

    parser.add_argument(
        "--detect-github-workflows",
        action="store_true",
        help="Inspect .github/workflows files without calling the model, then exit.",
    )
    parser.add_argument(
        "--init-github-action",
        action="store_true",
        help="Create a safe MiniCodex GitHub Actions workflow template without calling the model, then exit.",
    )
    parser.add_argument(
        "--github-workflow-name",
        default="minicodex-agent.yml",
        help="Workflow file name for --init-github-action.",
    )
    parser.add_argument(
        "--github-workflow-overwrite",
        action="store_true",
        help="Overwrite an existing workflow file during --init-github-action.",
    )
    parser.add_argument(
        "--parse-pr-comment",
        default="",
        help="Parse a /minicodex PR comment command without calling the model, then exit.",
    )

    parser.add_argument(
        "--generate-github-app-manifest",
        action="store_true",
        help="Generate a MiniCodex GitHub App manifest template without calling the model.",
    )
    parser.add_argument(
        "--github-app-name",
        default="MiniCodex Agent",
        help="App name for --generate-github-app-manifest.",
    )
    parser.add_argument(
        "--github-webhook-url",
        default="",
        help="Webhook URL value in the GitHub App manifest.",
    )
    parser.add_argument(
        "--init-github-webhook-server",
        action="store_true",
        help="Create a signature-validating webhook server scaffold without calling the model.",
    )
    parser.add_argument(
        "--prepare-github-artifact-upload",
        action="store_true",
        help="Generate a GitHub Actions upload-artifact step without calling the model.",
    )

    parser.add_argument(
        "--security-audit",
        action="store_true",
        help="Generate a local-only product security audit report without calling the model, then exit.",
    )
    parser.add_argument(
        "--scan-repo-instructions",
        action="store_true",
        help="Scan AGENTS.md/.minicodex/skills instructions for prompt-injection/secret-exfiltration risks without calling the model, then exit.",
    )

    parser.add_argument(
        "--project-health",
        action="store_true",
        help="Generate a project health/readiness summary report without calling the model, then exit.",
    )

    parser.add_argument(
        "--final-readiness",
        action="store_true",
        help="Generate a release-readiness report without calling the model; includes security, bounded test-matrix, and verification gates.",
    )
    parser.add_argument(
        "--final-readiness-skip-security",
        action="store_true",
        help="Skip the local security gate inside --final-readiness.",
    )
    parser.add_argument(
        "--final-readiness-skip-test-run",
        action="store_true",
        help="Do not run the bounded test matrix inside --final-readiness; only produce the plan/warning.",
    )
    parser.add_argument(
        "--final-readiness-test-max-files",
        type=int,
        default=3,
        help="Test-matrix file limit used during --final-readiness; 0 means the full matrix.",
    )
    parser.add_argument(
        "--final-readiness-test-timeout",
        type=int,
        default=20,
        help="Per-file timeout in seconds for the --final-readiness bounded test matrix.",
    )
    parser.add_argument(
        "--final-readiness-test-group",
        choices=["fast", "unit", "integration", "subprocess", "sandbox", "slow", "all"],
        default="fast",
        help="Marker-aware test-matrix group to run during --final-readiness.",
    )
    parser.add_argument(
        "--final-readiness-run-verification-tools",
        action="store_true",
        help="Run installed build/lint/typecheck tools inside --final-readiness.",
    )
    parser.add_argument(
        "--final-readiness-verification-timeout",
        type=int,
        default=DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
        help="Per-command timeout in seconds for verification tools run by --final-readiness.",
    )
    parser.add_argument(
        "--test-matrix-plan",
        action="store_true",
        help="Generate the file-level test-matrix plan that reduces monolithic pytest timeout risk without calling the model, then exit.",
    )
    parser.add_argument(
        "--release-package-manifest",
        action="store_true",
        help="Generate the package content and generated-artifact cleanliness manifest without calling the model, then exit.",
    )
    parser.add_argument(
        "--from-zip",
        default="",
        help="Inspect the given zip archive instead of the working tree for --release-package-manifest.",
    )
    parser.add_argument(
        "--clean-generated-artifacts",
        action="store_true",
        help="Clean generated artifacts such as .pytest_cache, __pycache__, build, and dist without calling the model, then exit.",
    )
    parser.add_argument(
        "--clean-generated-artifacts-dry-run",
        action="store_true",
        help="Report what --clean-generated-artifacts would clean without deleting anything.",
    )

    parser.add_argument(
        "--index-max-files",
        type=int,
        default=500,
        help="Maximum number of files scanned by index_project.",
    )
    parser.add_argument(
        "--index-max-file-chars",
        type=int,
        default=80000,
        help="Maximum characters inspected per file during index_project.",
    )
    parser.add_argument(
        "--lang",
        choices=["en", "tr"],
        default="en",
        help="CLI output language. Default: en. Use tr for Turkish prompts/output chrome.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never block on input(); fail or use --default-answer for ask_user prompts.",
    )
    parser.add_argument(
        "--default-answer",
        default="",
        help="Answer used by ask_user in --non-interactive mode.",
    )
    parser.add_argument("--no-diff", action="store_true", help="Do not show git diff at the end.")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Open REPL mode so you can enter multiple tasks in one terminal session instead of a single command.",
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create .minicodex/config.json, policy, .env.example, and a plugin example for the project.",
    )
    parser.add_argument(
        "--setup-overwrite",
        action="store_true",
        help="Overwrite existing MiniCodex files during --setup.",
    )
    parser.add_argument(
        "--create-demo",
        metavar="PATH",
        help="Create a small Python demo project for safe testing, then exit.",
    )
    parser.add_argument(
        "--create-demo-overwrite",
        action="store_true",
        help="Allow --create-demo to overwrite a non-empty target directory.",
    )

    return parser.parse_args()


def main() -> None:
    """CLI entry point."""

    load_env()
    explicit = _explicit_cli_options(sys.argv[1:])
    args = parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(tr("folder_not_found", args.lang, root=root))
        sys.exit(1)

    config = AgentConfig(
        root=root,
        model=args.model,
        provider=args.provider,
        max_steps=args.max_steps,
        approval=args.approval,
        show_diff=not args.no_diff,
        safety_profile=args.safety_profile,
        log_dir=args.log_dir,
        create_branch=args.create_branch,
        test_command=args.test_command,
        dry_run=args.dry_run,
        index_max_files=args.index_max_files,
        index_max_file_chars=args.index_max_file_chars,
        project_config_enabled=not args.no_project_config,
        project_policy_enabled=not args.no_project_policy,
        allow_network_commands=args.allow_network_commands,
        allow_github_api_writes=args.allow_github_api_writes,
        sandbox_mode=args.sandbox_mode,
        sandbox_image=args.sandbox_image,
        sandbox_network=args.sandbox_network,
        sandbox_cpus=args.sandbox_cpus,
        sandbox_memory=args.sandbox_memory,
        sandbox_pids_limit=args.sandbox_pids_limit,
        sandbox_workspace_mode=args.sandbox_workspace_mode,
        sandbox_keep_workspace=args.sandbox_keep_workspace,
        sandbox_max_file_bytes=args.sandbox_max_file_bytes,
        agent_workspace_mode=args.agent_workspace_mode,
        agent_workspace_apply=args.agent_workspace_apply,
        agent_workspace_keep=args.agent_workspace_keep,
        agent_workspace_max_file_bytes=args.agent_workspace_max_file_bytes,
        agent_workspace_diff_max_chars=args.agent_workspace_diff_max_chars,
        log_enabled=not args.no_log,
        auto_snapshot_before_edit=not args.no_auto_snapshot_before_edit,
        scan_secrets_before_pr=not args.no_scan_secrets_before_pr,
        untrusted_workspace=args.untrusted_workspace,
        require_trusted_workspace_for_writes=args.require_trusted_workspace_for_writes,
        security_audit_max_files=args.security_audit_max_files,
        security_audit_report_max_chars=args.security_audit_report_max_chars,
        external_security_timeout_seconds=args.external_security_timeout_seconds,
        max_agent_batch_size=args.max_agent_batch_size,
        multi_agent_thread_max_messages=args.multi_agent_thread_max_messages,
        multi_agent_result_max_chars=args.multi_agent_result_max_chars,
        multi_agent_allow_parallel_writes=args.multi_agent_allow_parallel_writes,
        long_horizon_enabled=args.long_horizon,
        long_horizon_run_id=args.long_horizon_run_id,
        long_horizon_auto_checkpoint_interval=args.long_horizon_auto_checkpoint_interval,
        long_horizon_resume_max_chars=args.long_horizon_resume_max_chars,
        checkpoint_max_observation_chars=args.checkpoint_max_observation_chars,
        policy_file=args.policy_file,
        model_timeout_seconds=args.model_timeout_seconds,
        model_max_output_tokens=args.model_max_output_tokens,
        model_max_retries=args.model_max_retries,
        model_retry_backoff_seconds=args.model_retry_backoff_seconds,
        model_repair_attempts=args.model_repair_attempts,
        model_structured_output=not args.no_structured_output,
        model_call_budget=args.model_call_budget,
        model_cost_budget_usd=args.model_cost_budget_usd,
        model_input_price_per_million=args.model_input_price_per_million,
        model_output_price_per_million=args.model_output_price_per_million,
        model_base_url=args.model_base_url,
        model_api_key_env=args.model_api_key_env,
        model_reasoning_effort=args.model_reasoning_effort,
        model_stream=args.model_stream,
        model_stream_ui=args.model_stream_ui,
        model_action_protocol=args.model_action_protocol,
        context_enabled=not args.no_context,
        context_max_chars=args.context_max_chars,
        context_instruction_max_chars=args.context_instruction_max_chars,
        context_relevant_files=args.context_relevant_files,
        context_observation_chars_each=args.context_observation_chars_each,
        skills_enabled=not args.no_skills,
        skills_max_selected=args.skills_max_selected,
        skills_max_summary_chars=args.skills_max_summary_chars,
        skills_read_max_chars=args.skills_read_max_chars,
        structured_tool_results=not args.no_structured_tool_results,
        tool_result_content_chars=args.tool_result_content_chars,
        patch_verify_after_apply=not args.no_patch_verify_after_apply,
        patch_verify_python_syntax=args.patch_verify_python_syntax,
        patch_fuzzy_apply=args.patch_fuzzy_apply,
        test_plan_max_commands=args.test_plan_max_commands,
        test_output_max_chars=args.test_output_max_chars,
        test_failure_context_lines=args.test_failure_context_lines,
        flaky_retry_count=args.flaky_retry_count,
        review_after_run=args.review_after_run,
        review_bundle_max_diff_chars=args.review_bundle_max_diff_chars,
        eval_default_max_steps=args.eval_default_max_steps,
        eval_model_call_budget=args.eval_model_call_budget,
        eval_timeout_seconds=args.eval_timeout_seconds,
        eval_report_max_chars=args.eval_report_max_chars,
        telemetry_enabled=not args.no_telemetry,
        telemetry_run_id=args.telemetry_run_id,
        telemetry_max_event_chars=args.telemetry_max_event_chars,
        telemetry_jsonl=not args.no_telemetry_jsonl,
        prompt_profile=args.prompt_profile,
        prompt_max_chars=args.prompt_max_chars,
        prompt_include_action_reference=not args.no_prompt_action_reference,
        prompt_preview_max_chars=args.prompt_preview_max_chars,
        lang=args.lang,
        non_interactive=args.non_interactive,
        default_answer=args.default_answer,
    )
    try:
        config = apply_project_config(config, explicit_options=explicit)
    except Exception as exc:  # noqa: BLE001 - config errors should be user-friendly
        print(tr("config_read_failed", args.lang, error=exc))
        sys.exit(1)

    if "model" not in explicit and config.provider != "openai" and config.model == default_model():
        config = replace(config, model=get_provider_info(config.provider).default_model)

    if args.dev_panel:
        print(
            render_tui_panel(
                root, goal=args.goal or "", max_diff_chars=config.review_bundle_max_diff_chars
            )
        )
        return

    if args.export_ide_bridge:
        print(export_ide_bridge(root, dry_run=config.dry_run))
        return

    if args.init_evals:
        print(init_eval_suite(root, overwrite=args.eval_overwrite, dry_run=config.dry_run))
        return

    if args.init_eval_baselines:
        print(init_eval_baselines(root, overwrite=args.eval_overwrite, dry_run=config.dry_run))
        return

    if args.list_evals:
        from .utils import to_pretty_json

        print(to_pretty_json({"tasks": list_eval_tasks(root)}))
        return

    if args.list_eval_baselines:
        from .utils import to_pretty_json

        print(to_pretty_json({"baselines": list_eval_baselines(root)}))
        return

    if args.eval_coverage_report:
        from .utils import to_pretty_json

        print(to_pretty_json(eval_coverage_report(root)))
        return

    if args.eval_baseline_plan:
        from .utils import to_pretty_json

        print(
            to_pretty_json(
                eval_baseline_plan(root, args.eval_baseline_plan, run_id=args.eval_run_id or None)
            )
        )
        return

    if args.compare_eval_baselines:
        from .utils import to_pretty_json

        print(
            to_pretty_json(
                compare_eval_baselines(
                    root,
                    args.compare_eval_baselines[0],
                    args.compare_eval_baselines[1],
                    min_success_delta=args.eval_min_success_delta,
                )
            )
        )
        return

    if args.detect_github_workflows:
        print(detect_github_workflows(root, max_chars=config.max_observation_chars))
        return

    if args.init_github_action:
        print(
            init_github_action(
                root,
                workflow_name=args.github_workflow_name,
                overwrite=args.github_workflow_overwrite,
                dry_run=config.dry_run,
            )
        )
        return

    if args.parse_pr_comment:
        print(
            parse_pr_comment_command(args.parse_pr_comment, max_chars=config.max_observation_chars)
        )
        return

    if args.generate_github_app_manifest:
        print(
            generate_github_app_manifest(
                root,
                app_name=args.github_app_name,
                webhook_url=args.github_webhook_url,
                overwrite=args.github_workflow_overwrite,
                dry_run=config.dry_run,
                max_chars=config.max_observation_chars,
            )
        )
        return

    if args.init_github_webhook_server:
        print(
            init_github_webhook_server(
                root,
                overwrite=args.github_workflow_overwrite,
                dry_run=config.dry_run,
                max_chars=config.max_observation_chars,
            )
        )
        return

    if args.prepare_github_artifact_upload:
        print(
            prepare_github_artifact_upload(
                root,
                workflow_name=args.github_workflow_name,
                max_chars=config.max_observation_chars,
            )
        )
        return

    if args.security_audit:
        print(
            security_audit_report(
                root,
                untrusted_workspace=config.untrusted_workspace,
                sandbox_mode=config.sandbox_mode,
                sandbox_network=config.sandbox_network,
                approval=config.approval,
                allow_network_commands=config.allow_network_commands,
                allow_github_api_writes=config.allow_github_api_writes,
                max_files=config.security_audit_max_files,
                max_chars=config.security_audit_report_max_chars,
            )
        )
        return

    if args.scan_repo_instructions:
        print(scan_repo_instructions(root, max_chars=config.max_observation_chars))
        return

    if args.project_health:
        print(project_health_report(root, max_chars=config.max_observation_chars))
        return

    if args.final_readiness:
        print(
            final_readiness_report(
                root,
                include_security_audit=not args.final_readiness_skip_security,
                run_test_matrix=not args.final_readiness_skip_test_run,
                test_matrix_max_files=args.final_readiness_test_max_files,
                test_matrix_timeout=args.final_readiness_test_timeout,
                test_matrix_group=args.final_readiness_test_group,
                run_verification_tools=args.final_readiness_run_verification_tools,
                verification_timeout=args.final_readiness_verification_timeout,
                timeout=45,
                max_chars=max(config.max_observation_chars, 80000),
            )
        )
        return

    if args.test_matrix_plan:
        from .utils import to_pretty_json

        print(to_pretty_json(build_test_matrix_plan(root, group="all")))
        return

    if args.release_package_manifest:
        print(
            release_package_manifest(
                root, from_zip=args.from_zip or None, max_chars=config.max_observation_chars
            )
        )
        return

    if args.clean_generated_artifacts:
        from .utils import to_pretty_json

        print(
            to_pretty_json(
                clean_generated_artifacts(root, dry_run=args.clean_generated_artifacts_dry_run)
            )
        )
        return

    if args.model_price_table:
        from .utils import to_pretty_json

        print(to_pretty_json({"prices": list_model_prices()}))
        return

    if args.telemetry_summary:
        print(summarize_telemetry(root, limit=20, max_chars=config.max_observation_chars))
        return

    if args.optimization_dashboard:
        print(render_optimization_dashboard(root, limit=20, max_chars=config.max_observation_chars))
        return

    if args.failure_dashboard:
        from .utils import to_pretty_json

        print(to_pretty_json(build_failure_taxonomy_dashboard(root, limit=20)))
        return

    if args.run_prompt_ab:
        from .utils import to_pretty_json

        profiles = [item.strip() for item in args.prompt_ab_profiles.split(",") if item.strip()]
        task_ids = [item.strip() for item in args.prompt_ab_tasks.split(",") if item.strip()]
        comparison_result = run_prompt_ab_comparison(
            root,
            config,
            task_ids,
            profiles,
            run_id=args.eval_run_id or None,
            max_steps=config.eval_default_max_steps,
            model_call_budget=config.eval_model_call_budget,
            timeout=config.eval_timeout_seconds,
            dry_run=config.dry_run,
        )
        print(to_pretty_json(comparison_result))
        return

    if args.read_telemetry_run:
        print(
            read_telemetry_run(
                root,
                args.read_telemetry_run,
                include_spans=True,
                max_chars=config.max_observation_chars,
            )
        )
        return

    if args.export_telemetry_bundle:
        print(
            export_telemetry_bundle(
                root, max_chars=config.max_observation_chars, dry_run=config.dry_run
            )
        )
        return

    if args.list_prompt_profiles:
        from .utils import to_pretty_json

        print(to_pretty_json({"profiles": list_prompt_profiles()}))
        return

    if args.prompt_preview:
        print(
            render_prompt_preview(
                profile=config.prompt_profile,
                goal=args.goal or "",
                provider=config.provider,
                include_action_reference=config.prompt_include_action_reference,
                max_chars=config.prompt_preview_max_chars,
            )
        )
        return

    if args.semantic_capability_report:
        from .utils import to_pretty_json

        print(to_pretty_json(semantic_capability_report().to_dict()))
        return

    if args.build_semantic_index:
        print(
            build_semantic_index(
                root,
                max_files=args.semantic_max_files,
                max_symbols=args.semantic_max_symbols,
                max_references_per_symbol=min(args.semantic_max_references, 20),
                include_routes=True,
            ).summary(max_chars=config.max_observation_chars)
        )
        return

    if args.find_symbol_references:
        from .utils import to_pretty_json, truncate

        print(
            truncate(
                to_pretty_json(
                    find_symbol_references(
                        root,
                        args.find_symbol_references,
                        max_matches=args.semantic_max_references,
                    )
                ),
                config.max_observation_chars,
            )
        )
        return

    if args.inspect_routes:
        from .utils import to_pretty_json, truncate

        print(truncate(to_pretty_json(inspect_routes(root)), config.max_observation_chars))
        return

    if args.create_demo:
        print(
            create_demo_project(
                (root / args.create_demo).resolve(),
                overwrite=args.create_demo_overwrite,
                dry_run=config.dry_run,
            )
        )
        return

    if args.setup:
        print(
            run_setup_wizard(
                root,
                overwrite=args.setup_overwrite,
                provider=config.provider,
                approval=config.approval,
                safety_profile=config.safety_profile,
                test_command=config.test_command,
                max_steps=config.max_steps,
                dry_run=config.dry_run,
            )
        )
        return

    try:
        require_api_key(config.provider, config.model_api_key_env)
    except RuntimeError as exc:
        print(f"Error: {exc}" if config.lang == "en" else f"Hata: {exc}")
        sys.exit(1)

    if args.run_eval:
        from .utils import to_pretty_json, truncate

        print(
            truncate(
                to_pretty_json(
                    run_eval_task(
                        root,
                        config,
                        args.run_eval,
                        run_id=args.eval_run_id or None,
                        max_steps=config.eval_default_max_steps,
                        model_call_budget=config.eval_model_call_budget,
                        timeout=config.eval_timeout_seconds,
                        dry_run=config.dry_run,
                    )
                ),
                config.eval_report_max_chars,
            )
        )
        return

    if args.run_eval_suite:
        from .utils import to_pretty_json, truncate

        print(
            truncate(
                to_pretty_json(
                    run_eval_suite(
                        root,
                        config,
                        run_id=args.eval_run_id or None,
                        max_steps=config.eval_default_max_steps,
                        model_call_budget=config.eval_model_call_budget,
                        timeout=config.eval_timeout_seconds,
                        dry_run=config.dry_run,
                    )
                ),
                config.eval_report_max_chars,
            )
        )
        return

    if args.interactive:
        if config.non_interactive:
            print(
                "Error: --interactive cannot be combined with --non-interactive."
                if config.lang == "en"
                else "Hata: --interactive ve --non-interactive birlikte kullanılamaz."
            )
            sys.exit(1)
        run_interactive_session(config)
        return

    if not args.goal:
        print(tr("goal_required", config.lang))
        sys.exit(1)

    run_result = MiniCodexAgent(config).run(args.goal)
    if config.review_after_run:
        print(
            create_review_bundle(
                root,
                title="MiniCodex post-run review",
                goal=args.goal,
                max_diff_chars=config.review_bundle_max_diff_chars,
                dry_run=config.dry_run,
            )
        )
    sys.exit(int(run_result.exit_code))


if __name__ == "__main__":
    main()
