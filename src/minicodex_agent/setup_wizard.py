"""First-run setup helpers for MiniCodex projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_policy import init_project_policy, read_project_policy, update_project_policy
from .project_settings import init_project_config, read_project_config, update_project_config
from .provider_registry import list_provider_names
from .utils import to_pretty_json

ENV_EXAMPLE = """# MiniCodex Agent environment
# Copy this file to .env and fill in your key when using provider=openai.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5
MINICODEX_PROVIDER=openai

# Optional local/OpenAI-compatible endpoint. Examples:
# MINICODEX_PROVIDER=ollama
# MINICODEX_MODEL=qwen3-coder
# MINICODEX_MODEL_BASE_URL=http://localhost:11434/v1
# MINICODEX_API_KEY_ENV=OPENAI_API_KEY

# Optional: only needed if you enable real GitHub API issue/PR creation.
GITHUB_TOKEN=
"""


AGENTS_MD_TEMPLATE = """# MiniCodex Project Instructions

These instructions are loaded automatically by MiniCodex before generic habits.

## Development workflow
- Read the relevant files before editing.
- Prefer minimal, targeted patches.
- Run targeted tests first, then broader checks when needed.
- Scan secrets before PR-ready summaries.

## Project-specific notes
- Add repository conventions here, such as preferred test commands, style rules, release steps, and forbidden paths.
"""

DEFAULT_TESTING_SKILL = """---
description: Plan and verify code changes with the smallest useful test set.
triggers: [test, tests, pytest, failing, ci, regression, verification]
tags: [testing, verification, ci]
---

# Targeted Test Verification

## When to use
- Use this skill when a task asks to fix failing tests, verify a patch, interpret CI logs, or choose what checks to run.

## Workflow
1. Use plan_tests before running broad test suites.
2. Prefer run_targeted_tests for changed files or failing test nodes.
3. Use classify_test_failure when output contains failures.
4. Read exact source lines before editing.
5. After patching, rerun the targeted test first and only then run broader checks.

## Guardrails
- Do not hide failing checks.
- Report skipped checks and why they were skipped.
"""

DEFAULT_PLUGIN_MANIFEST = {
    "name": "local-project-defaults",
    "version": "2.0.0",
    "description": "Project-local MiniCodex defaults and team conventions.",
    "tools": [],
    "prompts": [
        {
            "name": "safe-fix-test-loop",
            "text": "Inspect project, create a plan, snapshot before risky edits, make minimal changes, run tests, scan secrets, and summarize changes.",
        }
    ],
    "policies": {
        "notes": "This manifest is declarative. MiniCodex validates and enforces enabled tool/policy metadata; arbitrary plugin code is not executed.",
    },
}


def _write_text_if_needed(path: Path, content: str, overwrite: bool, dry_run: bool = False) -> str:
    """Write text unless the file already exists and overwrite is false."""

    if path.exists() and not overwrite:
        return f"kept existing {path.name}"
    action = "overwrite" if path.exists() else "write"
    if dry_run:
        return f"DRY-RUN: would {action} {path.name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.name}"


def run_setup_wizard(
    root: Path,
    *,
    overwrite: bool = False,
    provider: str = "openai",
    approval: str = "ask",
    safety_profile: str = "strict",
    test_command: str = "auto",
    max_steps: int = 30,
    create_env_example: bool = True,
    create_policy: bool = True,
    create_plugin_example: bool = True,
    create_agent_instructions: bool = True,
    create_skill_example: bool = True,
    dry_run: bool = False,
) -> str:
    """Create a practical first-run MiniCodex setup for a project.

    This is intentionally non-interactive so it can be called safely by the
    agent and by tests. The CLI presents it as a setup wizard command.
    """

    if provider not in set(list_provider_names()):
        raise ValueError("provider must be one of: " + ", ".join(list_provider_names()))
    if approval not in {"ask", "auto"}:
        raise ValueError("approval must be ask or auto")
    if safety_profile not in {"strict", "balanced", "permissive"}:
        raise ValueError("safety_profile must be strict, balanced, or permissive")

    messages: list[str] = []
    messages.append(init_project_config(root, overwrite=overwrite, dry_run=dry_run))
    updates: dict[str, Any] = {
        "version": 13,
        "preferred_provider": provider,
        "preferred_model": "",
        "default_approval": approval,
        "default_safety_profile": safety_profile,
        "default_test_command": test_command,
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
        "default_max_steps": int(max_steps),
        "scan_secrets_before_pr": True,
        "auto_snapshot_before_edit": True,
        "enabled_plugins": [],
        "max_agent_batch_size": 5,
        "policy_file": ".minicodex/policy.json",
        "log_enabled": True,
        "log_redaction": True,
        "max_log_value_chars": 6000,
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
        "lang": "en",
        "non_interactive": False,
        "default_answer": "",
    }
    messages.append(update_project_config(root, updates, dry_run=dry_run))

    if create_policy:
        messages.append(init_project_policy(root, overwrite=overwrite, dry_run=dry_run))
        policy = read_project_policy(root)
        # Keep setup safe by default and make explicit that secrets/runtime logs
        # should not be written by the agent.
        blocked = list(
            dict.fromkeys(
                list(policy.get("blocked_write_globs", []))
                + [
                    ".env",
                    ".env.*",
                    ".env.local",
                    ".env.*.local",
                    ".minicodex/runs/**",
                    ".minicodex/snapshots/**",
                ]
            )
        )
        allowed = list(
            dict.fromkeys([".env.example", *list(policy.get("allowed_write_globs", []))])
        )
        messages.append(
            update_project_policy(
                root,
                {
                    "version": 13,
                    "allowed_write_globs": allowed,
                    "blocked_write_globs": blocked,
                    "allow_env_examples": True,
                },
                dry_run=dry_run,
            )
        )

    if create_env_example:
        messages.append(
            _write_text_if_needed(root / ".env.example", ENV_EXAMPLE, overwrite, dry_run=dry_run)
        )

    if create_agent_instructions:
        messages.append(
            _write_text_if_needed(
                root / "AGENTS.md", AGENTS_MD_TEMPLATE, overwrite, dry_run=dry_run
            )
        )

    if create_skill_example:
        skill_path = root / ".minicodex" / "skills" / "targeted-testing" / "SKILL.md"
        messages.append(
            _write_text_if_needed(skill_path, DEFAULT_TESTING_SKILL, overwrite, dry_run=dry_run)
        )

    if create_plugin_example:
        plugin_path = root / ".minicodex" / "plugins" / "local-project-defaults.json"
        messages.append(
            _write_text_if_needed(
                plugin_path,
                to_pretty_json(DEFAULT_PLUGIN_MANIFEST) + "\n",
                overwrite,
                dry_run=dry_run,
            )
        )

    final_config = updates if dry_run else read_project_config(root)
    final_policy = read_project_policy(root)
    if dry_run and create_policy:
        final_policy = {**final_policy, "version": 7, "allow_env_examples": True}
    summary = {
        "created_or_updated": [
            ".minicodex/config.json",
            ".minicodex/policy.json",
            ".env.example",
            "AGENTS.md",
            ".minicodex/skills/targeted-testing/SKILL.md",
            ".minicodex/plugins/local-project-defaults.json",
        ],
        "provider": final_config.get("preferred_provider"),
        "approval": final_config.get("default_approval"),
        "safety_profile": final_config.get("default_safety_profile"),
        "test_command": final_config.get("default_test_command"),
        "policy_enabled": final_policy.get("enabled"),
        "next_steps": [
            "Copy .env.example to .env and set OPENAI_API_KEY if using provider=openai.",
            "For local LLMs, use --provider ollama --model qwen3-coder or set MINICODEX_MODEL_BASE_URL.",
            "Edit AGENTS.md with project-specific rules and add SKILL.md files under .minicodex/skills for repeatable workflows.",
            "Run: minicodex 'inspect project, run tests, and summarize risks' --root . --dry-run",
            "Run: minicodex --interactive --root . for an IDE-like terminal workflow.",
        ],
    }
    prefix = (
        "DRY-RUN: MiniCodex setup wizard not written."
        if dry_run
        else "MiniCodex setup wizard completed."
    )
    return prefix + "\n\n" + "\n---\n".join(messages) + "\n\nSummary:\n" + to_pretty_json(summary)
