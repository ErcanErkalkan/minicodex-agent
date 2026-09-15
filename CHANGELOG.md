# Changelog

## 4.4.23 - Release artifact and CLI polish hardening

- Aligned zip artifact names with the single top-level artifact root and exposed that invariant in release manifests.
- Added CI/release `ruff format --check .` coverage to match the pre-commit formatting policy.
- Removed the unused `types-python-dateutil` development dependency.
- Standardized public CLI help text in English and added checks to prevent mixed-language help regressions.

## 4.4.22 - Release positioning consistency

- Clarified package positioning so MiniCodex remains an alpha/developer-preview framework with release-readiness and quality-gate checks, not a claimed deployment-grade product.
- Reworded the older v4.4 quality-gate entry from overstated readiness language to “release-readiness / quality-gate baseline.”
- Added final-readiness validation that flags user-facing docs or changelog text that reintroduce deployment-grade claims inconsistent with the alpha classifier.

## 4.4.21 - Changelog structure hardening

- Normalized `CHANGELOG.md` to a single top-level `# Changelog` heading and one canonical entry per release version.
- Converted release headings to the consistent `## x.y.z - Title` format and removed duplicated historical sections that repeated 4.4.6, 4.4.3, 4.4.1, and 2.9.0.
- Added changelog structure validation to final readiness so duplicate versions, repeated `# Changelog` headings, `v`-prefixed headings, and out-of-order release entries are caught before packaging.
- Added regression coverage for changelog normalization and final-readiness reporting.

## 4.4.20 - Typecheck command consistency

- Standardized Python typecheck suggestions with CI and README by making src-layout projects prefer package-scoped `mypy src/<package>` commands instead of broad `mypy .`.
- Added regression coverage to prevent MiniCodex from recommending `mypy .` for its own src-layout package and to keep docs, CI, release, and language-adapter typecheck scope aligned.

## 4.4.19 - Documentation gate coverage

- Expanded documentation presence checks to include `docs/quickstart.md`, `docs/testing.md`, and Markdown files referenced from README documentation links.
- Added a documentation CLI example validator that parses documented `minicodex` commands against the real CLI parser without executing agent actions.
- Added regression coverage so missing user-facing docs or stale documented CLI flags fail the readiness documentation checks instead of silently passing.

## 4.4.18 - Framework detection false-positive fix

- Hardened framework detection to avoid treating detector pattern-table string literals, route catalogs, docs, or tests as application framework evidence.
- Replaced broad repository sample-text framework matching with dependency/config/path evidence and AST import/call evidence for Python web frameworks.
- Added regression coverage proving MiniCodex itself reports pytest tooling only, not false Django/FastAPI/Flask application frameworks, while real FastAPI/Flask imports remain detectable.

## 4.4.17 - Release manifest zip provenance

- Harden release package manifests so `--from-zip` derives version, top-level docs, source module counts, test counts, and generated-artifact findings exclusively from the zip artifact.
- Add explicit manifest provenance fields: `metadata_source`, `root_used_for_metadata`, `artifact_root_prefix`, and `normalized_file_count`.
- Count nested `src/minicodex_agent/**/*.py` modules and nested `tests/**/test_*.py` tests consistently for both zip and working-tree manifests.
- Add regression coverage proving fake working-tree metadata cannot contaminate zip-sourced manifests.

## 4.4.16 - Syntax-only test matrix plan

- Hardened the test matrix plan so the syntax step is explicitly bytecode-free and never aliases to `run_test_matrix.py`.
- Added `scripts/` to the syntax-check scope used by the readiness plan and recommended CI commands.
- Added regression coverage preventing `--max-files 0` from reappearing in the syntax/readiness path.

## 4.4.15 - Matrix coverage gate

- Replaced remaining monolithic CI/release coverage commands with a bounded, marker-aware, file-level coverage gate.
- Added `scripts/run_coverage_gate.py` so coverage collection uses per-file timeouts and the same marker policy as `scripts/run_test_matrix.py`.
- Updated testing documentation, architecture notes, final-readiness recommendations, and verification-tool specs to consistently recommend matrix-first testing plus file-level coverage.
- Added regression coverage to prevent reintroducing `pytest --cov` or plain `pytest -q` as package-level CI gates.

## 4.4.14 - Documented CLI flag compatibility

- Added the documented `--project-health` CLI shortcut for the existing project health report, so `docs/usage.md` commands now execute without falling through to a model run.
- Added backward-compatible `--list-eval-tasks` support while keeping `--list-evals` as the canonical eval listing command.
- Added explicit `--no-github-api-writes` CLI support that overrides project config and keeps GitHub write operations disabled unless `--allow-github-api-writes` is intentionally selected.
- Added regression tests for the documented CLI flags and refreshed docs to identify canonical commands and safe GitHub write posture.
- Replaced misleading test-matrix syntax planning with a bytecode-free AST syntax checker script.
- Hardened zip release manifests so zip-mode version, docs, source-module, and test-file counts are derived from the immutable archive, not the mutable working tree.
- Aligned CI, release, and pre-commit examples with the marker-aware test matrix to reduce monolithic pytest timeout risk.

## 4.4.13 - Security and release documentation hardening

- Hardened repo-local instruction handling: AGENTS.md/.minicodex instructions are scanned before prompt inclusion, high/critical findings are blocked from context, and prompts state that repo instructions are untrusted unless validated.
- Added security audit fixture allowlisting with `tests/fixtures/unsafe_examples/` and `# minicodex-security-test-fixture` so intentional unsafe samples are not reported as real findings.
- Extended release/readiness helpers with `--release-package-manifest --from-zip ...`, `--clean-generated-artifacts`, generated artifact cleanup, and explicit ruff/mypy/build/twine/pytest-cov release quality gates.
- Split the oversized README into focused docs: usage, security, local LLMs, evals, GitHub, and architecture.

## 4.4.12 - GitHub workflow integration

- Upgraded GitHub integration from mostly preview helpers to a fuller GitHub-agent workflow layer.
- Added GitHub App manifest generation, signed webhook server scaffolding, real GitHub Actions CI log fetch support, review comment resolver/planned posting, gated branch/add/commit/push execution, and upload-artifact workflow support.
- Added tools: `generate_github_app_manifest`, `init_github_webhook_server`, `fetch_github_ci_log`, `execute_commit_push_workflow`, `resolve_review_comments`, `prepare_github_artifact_upload`, and `create_github_review_comment`.
- Strengthened security gates: real CI fetch requires network/API enablement, push/review-comment writes require explicit GitHub write enablement and manual approval, and dry-run/preview remains the default path.

## 4.4.11 - AST-aware patch/refactor layer

- Added an AST-aware patch/refactor layer with capability reporting, semantic edit planning, native Python AST validation, grammar-aware TypeScript/Java/Go/Rust token edits, import organization, conservative dead-code detection/cleanup, and formatter-after-edit verification.
- Added tools: `ast_patch_capability_report`, `plan_semantic_edit`, `rename_symbol_semantic`, `organize_imports`, `detect_dead_code`, `cleanup_dead_code`, and `format_and_verify`.
- Extended the code-intelligence plugin, action schema, trust gates, and prompt guidance so semantic refactors prefer AST-aware tools over raw text replacement.

## 4.4.10 - Semantic language layer

- Added a semantic language layer with Python AST symbols, grammar-aware TypeScript/Java/Go/Rust symbol extraction, cross-file symbol reference lookup, framework route inspection, and parser capability reporting.
- Added semantic code intelligence tools: semantic_capability_report, build_semantic_index, find_symbol_references, and inspect_routes.
- Added CLI shortcuts for semantic reports and extended code-intelligence plugin/action schema coverage.

## 4.4.9 - Expanded Codex-claim eval benchmarks

- Expanded built-in eval benchmarks with hard Codex-claim categories: multi-file Python bugfix, TypeScript/React refactor, Java/Maven test fix, security patch, dependency upgrade, CI repair, large diff review, malicious instruction defense, long-horizon, and multi-agent tasks.
- Added `eval_coverage_report` tool and `--eval-coverage-report` CLI.
- Added claim-suite baseline manifests for `gpt-5.3-codex`, `gpt-5.5`, Ollama Qwen coder, and LM Studio local models.
- Baseline command plans now include local model action protocol options where relevant.

## 4.4.8 - Local native tool-calling provider hardening

- Added native Chat Completions `tools/tool_calls` support for OpenAI-compatible/local providers.
- Added `--model-action-protocol auto|json_text|tool_calls`; `auto` now prefers native tool calls for Ollama/LM Studio/llama.cpp/OpenAI-compatible endpoints and falls back to JSON text when unsupported.
- Added real-time stream UI plumbing with `--model-stream-ui`.
- Added provider schema-reliability metrics for native tool calls, JSON-text actions, validation success/failure counts, and repair prompt counts.
- Split local model prompt guidance so native tool-call and JSON-text protocols are not mixed.

## 4.4.7 - Expanded eval benchmarks and baseline manifests

- Expanded the built-in eval suite from smoke/docs tasks into mixed-language benchmark coverage: Python bugfix/security/CI repair, TypeScript, React accessibility, Java, Go, Rust, and malicious repo instruction defense.
- Added provider/model eval baseline manifests for `stub`, OpenAI/Codex-style, Ollama, LM Studio, and full release regression plans.
- Added `init_eval_baselines`, `list_eval_baselines`, `eval_baseline_plan`, and `compare_eval_baselines` tools.
- Added CLI shortcuts: `--init-eval-baselines`, `--list-eval-baselines`, `--eval-baseline-plan`, and `--compare-eval-baselines`.
- Added regression tests to ensure baselines reference real built-in tasks and expose reproducible commands without making API calls.

## 4.4.6 - Marker-aware test matrix and CI split fix

- Added automatic pytest marker assignment for `unit`, `integration`, `subprocess`, `sandbox`, and `slow` tests via `tests/conftest.py`.
- Upgraded `scripts/run_test_matrix.py` with marker groups, group-specific timeouts, JSONL progress streaming, and graceful handling of deselected files.
- Updated final-readiness to use a fast marker-aware bounded test gate by default while still supporting full/integration/subprocess/sandbox/slow groups.
- Added marker-aware test matrix planning and documentation so CI can split fast PR checks from heavier scheduled/full checks.

## 4.4.5 - Run-wide isolated workspace fix

- Added agent-level isolated workspace mode so all file reads/writes/patches can run on a filtered workspace copy instead of the original project tree.
- Added reviewable isolated workspace diff and manifest exports under `.minicodex/agent_workspaces/`.
- Added explicit apply policy: `never`, `ask`, or `auto`, with sensitive paths blocked during sync-back.
- Added CLI flags for run-wide workspace isolation and regression tests for diff/export/apply behavior.

## 4.4.4 - Bytecode-clean final readiness fix

- Prevented final-readiness and bounded test-matrix checks from leaving `__pycache__` / `.pyc` artifacts in the project tree.
- Added structural bytecode cleanup metadata to final readiness reports.
- Updated CLI smoke/test-matrix subprocesses to run with `-B` and `PYTHONDONTWRITEBYTECODE=1`.
- Replaced test-matrix `compileall` bytecode generation with syntax-only in-memory compilation.

## 4.4.3 - Machine-readable JSON report truncation fix

- Fixed final-readiness and release-manifest JSON rendering so reports are never cut mid-token.
- Added structured `truncated`, `omitted_count`, and size metadata when reports exceed requested max chars.
- Updated quality-gate tool output to render bounded valid JSON for test matrix plans.

## 4.4.2 - Final readiness security and verification gates

- Added a release-blocking security gate to final readiness reports.
- Added bounded test-matrix execution results to final readiness.
- Added build/lint/typecheck verification gate with optional execution.
- Added safe PYTHONDONTWRITEBYTECODE handling for readiness subprocesses.
- Added --max-files support to scripts/run_test_matrix.py for bounded readiness checks.

## 4.4.1 - Security audit false-positive hardening

- Fixed built-in SAST false positives from Python string literals and rule-definition fixtures.
- Replaced OpenAI-shaped fake test secret with a non-provider redaction fixture value.
- Added regression tests ensuring scanner rules still detect executable unsafe code.

## 4.4.0 - Final readiness / quality-gate layer

- Added a final readiness layer with deterministic version, syntax, registry, documentation, generated-artifact, and CLI smoke checks.
- Added tools: `final_readiness_report`, `test_matrix_plan`, and `release_package_manifest`.
- Added CLI shortcuts: `--final-readiness`, `--test-matrix-plan`, and `--release-package-manifest`.
- Added `scripts/run_test_matrix.py` to run tests by file with per-file timeouts, avoiding monolithic pytest timeout behavior caused by subprocess-heavy tests.
- Added the `quality-gates` built-in plugin and regression tests in `tests/test_quality_gate_layer_v45.py`.
- Updated package docs and release reports for a v4.4 release-readiness / quality-gate baseline.

## 4.3.0 - Product security layer

- Added product-level security audit helpers: `security_audit_report`, `run_sast_scan`, `run_dependency_audit`, `scan_repo_instructions`, `validate_plugin_permissions`, and `workspace_trust_report`.
- Added built-in lightweight SAST fallback for risky patterns such as `shell=True`, `eval`, `exec`, unsafe YAML loading, Node `child_process.exec`, and committed private keys.
- Added dependency audit command planning for Python, Node, pnpm/yarn, Rust, and Go projects while keeping network-dependent execution opt-in.
- Added repo-local instruction prompt-injection scanning for `AGENTS.md`, `.minicodex/instructions.md`, skills, and plugin manifests.
- Added local plugin permission declarations and validation for filesystem, command, GitHub, memory, telemetry, and security-audit permissions.
- Added untrusted workspace guardrails that block high-impact actions when `--untrusted-workspace` is combined with `--approval auto`.
- Added security CLI shortcuts: `--security-audit`, `--scan-repo-instructions`, `--untrusted-workspace`, and related budget/timeout settings.

## 4.2.0 - Modular prompt layer

- Added a profile-aware modular prompt engine with versioned prompt sections and task profiles.
- Added prompt profiles: `auto`, `general`, `bugfix`, `review`, `refactor`, `test-ci`, `security`, `docs`, `github`, `eval`, `long-horizon`, `local-model`, and `frontend`.
- Added provider/goal-based prompt inference and per-run prompt bundle metadata.
- Added CLI shortcuts: `--prompt-profile`, `--prompt-preview`, `--list-prompt-profiles`, `--prompt-max-chars`, `--no-prompt-action-reference`, and `--prompt-preview-max-chars`.
- Added prompt tools: `list_prompt_profiles`, `render_prompt_bundle`, and `validate_prompt_contract`.
- Updated `ModelClient` so every agent run can use a profile-aware system prompt instead of the old global prompt string.
- Added project-config defaults and a `prompting` built-in plugin.
- Added regression tests in `tests/test_prompt_layer_v43.py`.

## 4.1.0 - Observability / telemetry layer

- Added local telemetry traces with span timing, token/cost ledger aggregation, risk events, prompt versioning, and sanitized JSON/JSONL exports.
- Added observability tools: `list_telemetry_runs`, `read_telemetry_run`, `telemetry_summary`, `compare_telemetry_runs`, and `export_telemetry_bundle`.
- Added CLI shortcuts: `--telemetry-summary`, `--read-telemetry-run`, `--export-telemetry-bundle`, `--telemetry-run-id`, and `--no-telemetry`.
- Added project-config defaults for telemetry and an `observability` built-in plugin.

## 4.0.0 - GitHub workflow layer

- Added GitHub Actions workflow inspection and a conservative MiniCodex workflow template generator.
- Added PR slash-command parsing for `/minicodex ...` comments with safe dry-run defaults.
- Added branch/commit/push planning without executing git side effects.
- Added GitHub Actions CI log summarization and CI fetch previews for `gh run view`/REST endpoints.
- Registered the new GitHub integration tools in action schema, runtime registry, and built-in plugin metadata.

## 3.9.0 - Eval benchmark harness

- Added an eval/benchmark harness for measuring agent quality across model, prompt, context, and tool changes.
- Added deterministic eval task descriptors under `.minicodex/evals/tasks/*.json` with fixture files, expected file assertions, verification commands, and metadata.
- Added disposable eval workspaces under `.minicodex/evals/runs/<run_id>/<task_id>/workspace` and aggregate reports under `.minicodex/evals/reports/*.json`.
- Added tools: `init_eval_suite`, `list_eval_tasks`, `read_eval_task`, `run_eval_task`, `run_eval_suite`, `list_eval_runs`, `read_eval_run`, and `compare_eval_runs`.
- Added scoring for required/forbidden changed files, file contains/not-contains checks, verification command exit codes, agent exit code, model call/token/cost usage, duration, and changed-file metrics.
- Added CLI shortcuts: `--init-evals`, `--list-evals`, `--run-eval`, `--run-eval-suite`, `--eval-run-id`, and eval budget/report controls.
- Added the `evals` built-in plugin and regression tests in `tests/test_eval_layer_v40.py`.

## 3.8.0 - Language/framework intelligence layer

- Added a language/framework intelligence layer for multi-language repositories.
- Added dependency-free adapters for Python, TypeScript/JavaScript, Java/Kotlin, Go, and Rust.
- Added tools: `detect_language_stack`, `inspect_frameworks`, `suggest_verification_commands`, and `language_adapter_report`.
- Extended project profiles with `languages`, `frameworks`, `typecheck_commands`, and `format_commands`.
- Added framework/toolchain detection for FastAPI, Django, Flask, pytest, Next.js, React, Vite, Vue, Angular, NestJS, Express, Spring Boot, JUnit, Gin, Fiber, Go Echo, Axum, Actix Web, Rocket, and Tauri.
- Updated `plan_tests`/`run_targeted_tests` with `include_typecheck` so verification loops can include language-aware typecheck commands.
- Updated prompt guidance, action schema, runtime registry, plugin metadata, and relevant-file key config discovery for language-aware workflows.
- Added regression tests in `tests/test_language_layer_v39.py`.

## 3.7.0 - Developer experience layer

- Added a developer-experience layer for terminal review and IDE-oriented workflows.
- Added tools: `render_tui_panel`, `create_review_bundle`, `list_review_bundles`, `read_review_bundle`, `record_review_decision`, `run_summary`, and `export_ide_bridge`.
- Added JSON review bundles under `.minicodex/review_bundles/*.json` with status, numstat, staged/unstaged diff previews, and approval decisions.
- Added a dependency-free terminal developer panel for status and diff preview without calling a model.
- Added saved-run summaries for `.minicodex/runs` transcripts so agents and humans can inspect prior runs compactly.
- Added `.minicodex/ide/bridge.json` export for future VS Code/IDE integrations.
- Added CLI flags: `--dev-panel`, `--review-after-run`, `--review-bundle-max-diff-chars`, and `--export-ide-bridge`.
- Updated action schema, runtime registry, plugin metadata, project config, and prompt guidance for developer UX workflows.
- Added regression tests in `tests/test_dev_experience_layer_v38.py`.

## 3.6.0 - Long-horizon task layer

- Added a long-horizon task layer for durable multi-session work.
- Added JSON-backed `.minicodex/long_horizon/runs/*.json` state files with goals, acceptance criteria, milestones, and checkpoints.
- Added tools: `create_long_task`, `list_long_tasks`, `read_long_task`, `resume_long_task`, `update_acceptance_criteria`, and `create_checkpoint`.
- Added compact resume packs so future runs can continue from the latest checkpoint without replaying the full transcript.
- Added optional automatic checkpointing with `--long-horizon`, `--long-horizon-run-id`, and `--long-horizon-auto-checkpoint-interval`.
- Updated config defaults, plugin metadata, runtime registry, action schema, CLI help, and prompt guidance for long tasks.
- Added regression tests in `tests/test_long_horizon_layer_v37.py`.

## 3.5.0 - Subagent orchestration

- Added Codex-style subagent thread orchestration on top of bounded role workers.
- Added `AgentThread`, `AgentMailbox`, and `AgentResultMerger` primitives for auditable parent/child coordination.
- Added `plan_subagent_threads`, `run_subagent_threads`, and `read_multi_agent_run` tools.
- Enhanced `run_multi_agent_work` payloads with `threads`, `mailbox`, `thread_model`, and `merged_result`.
- Added mailbox handoffs: each completed role posts a result message to `recipient=all` for later workers.
- Added configurable transcript/result budgets: `multi_agent_thread_max_messages`, `multi_agent_result_max_chars`, and `multi_agent_allow_parallel_writes`.
- Updated action schema, runtime registry, plugin metadata, CLI/config defaults, and prompt rules for subagent threads.
- Added regression tests in `tests/test_multi_agent_layer_v36.py`.

## 3.4.0 - Repo-local skill manager

- Added repo-local skill manager with front-matter parsing, ranking, validation, and safe progressive disclosure.
- Added skill tools: `list_skills`, `read_skill`, `validate_skills`, and `init_skill`.
- Added `skills` built-in plugin and registered skill actions in the strict action schema.
- Extended context pack skill metadata with title, description, triggers, tags, and when-to-use hints.
- Added CLI/project config fields for skill discovery and read budgets.
- Setup wizard now creates `AGENTS.md` plus an example `.minicodex/skills/targeted-testing/SKILL.md`.
- Added regression tests in `tests/test_skill_layer_v35.py`.

## 3.3.0 - Test/CI verification layer

- Added a Test/CI verification layer for Codex-like edit loops.
- Added `plan_tests` and `run_targeted_tests` tools.
- Added targeted test selection from changed files and failure output for Python, Node, Go, Rust, and Maven Java.
- Added `classify_test_failure` with syntax/import/assertion/typecheck/lint/build/timeout/dependency categories.
- Added `summarize_ci_log` for CI job/step/failure extraction.
- Added `detect_flaky_tests` for flaky/rerun/intermittent signals and inconsistent rerun results.
- Added project-config and CLI controls for test-plan size, output compaction, failure context lines, and flaky retry count.
- Updated agent prompt to prefer targeted verification before broad suites.
- Added regression tests in `tests/test_test_ci_layer_v34.py`.

## 3.2.0 - Patch/edit layer hardening

- Added a stronger patch/edit layer for Codex-like edit reliability.
- Added `plan_patch` and `verify_patch` tools to the filesystem plugin and action schema.
- Added machine-readable patch plan summaries with touched files, operation kind, hunk counts, additions/deletions, and risk warnings.
- Added post-apply verification to `apply_patch`; touched files must match the planned post-patch state.
- Added optional Python syntax verification for patched `.py` files.
- Added conservative fuzzy hunk matching controls through tool args/config/CLI.
- Hardened patch path safety so sensitive files such as `.env`, private keys, and credential files cannot be patched through the patch engine.
- Added patch-layer regression tests.

## 3.1.0 - Sandbox layer hardening

- Added a hardened sandbox layer in `src/minicodex_agent/sandbox.py`.
- Added Podman support alongside Docker.
- Container sandbox modes now use a disposable filtered workspace copy by default instead of directly mutating the project root.
- Excluded `.env`, private-key/credential paths, `.minicodex`, caches, binary artifacts, and oversized files from sandbox workspace copies.
- Added configurable network policy, CPU, memory, PID, image, workspace mode, keep-workspace, and max-file-size controls.
- Added CLI/project-config support for the new sandbox controls.
- Added sandbox configuration reporting in command observations and run metadata.
- Added regression tests in `tests/test_sandbox_layer_v32.py`.

## 3.0.0 - Structured tool results

- Added structured `TOOL_RESULT_JSON` observations for the agent loop.
- Added standard tool-result fields: `ok`, `status`, `summary`, `content`, `data`, `files_read`, `files_changed`, `commands_run`, `warnings`, `errors`, and `truncated`.
- Kept low-level tool handlers and `dispatch_tool` backwards-compatible with plain-text returns.
- Added `--no-structured-tool-results` and `--tool-result-content-chars` runtime controls.
- Added targeted navigation/search tools: `list_dir`, `glob_file_search`, `read_file_range`, and `rg_search`.
- Exposed new tools in action schemas, runtime registry, and built-in plugin metadata.
- Added regression tests in `tests/test_structured_tools_v31.py`.

## 2.9.0 - Bounded context layer

- Added a bounded context pack in each model prompt.
- Added automatic repo instruction loading for `AGENTS.md`, `.minicodex/instructions.md`, `.minicodex/AGENTS.md`, `docs/testing.md`, and `CONTRIBUTING.md`.
- Added repo-local skill discovery from `.minicodex/skills/*/SKILL.md` with goal-based ranking.
- Added ranked relevant-file hints using path, symbol, key-file, and content signals while still requiring file reads before edits.
- Added command/test/diff observation compaction that preserves failure lines and trims noisy output.
- Added context config and CLI controls: `--no-context`, `--context-max-chars`, `--context-instruction-max-chars`, `--context-relevant-files`, and `--context-observation-chars-each`.
- Added regression tests in `tests/test_context_layer_v30.py`.

## 2.8.0 - Local provider support

- Added `openai_compatible`, `ollama`, `lmstudio`, and `llama_cpp` providers for local/self-hosted OpenAI-compatible Chat Completions endpoints.
- Added provider-level base URL, API-key-env, reasoning-effort, and streaming controls.
- Kept the official `openai` provider on the Responses API with structured JSON-schema output and safer fallback behavior.
- Added project-config support for `preferred_model`, `model_base_url`, `model_api_key_env`, `model_reasoning_effort`, and `model_stream`.
- Added provider-specific default models when local providers are selected without an explicit `--model`.
- Added regression tests for local provider routing, Chat Completions payloads, config propagation, and fallback behavior.

## 2.7.0 - CLI language selection

- Added `--lang en|tr` for user-visible CLI language control.
- Added `--non-interactive` and `--default-answer` so `ask_user` and approval paths do not block CI unexpectedly.
- Expanded package metadata with author/email, SPDX-style license, classifiers, keywords, and project URLs.
- Kept dev dependencies aligned with release/check commands: pytest, pytest-cov, ruff, mypy, build, twine, and type stubs.
- Added Dependabot, release workflow, and gitleaks-based security workflow.
- Replaced the hand-written prompt tool list with an auto-generated `ACTION_SPECS` reference.
- Added `run_external_secret_scan` for gitleaks/trufflehog integration when installed.
- Improved snapshots with `.minicodex/snapshot_ignore`, file hash/mode/mtime metadata, and pre-restore safety snapshots.
- Improved local code search ranking and added `build_dependency_graph`.

## 2.6.0 - Deterministic CLI exit codes

- Added deterministic CLI exit-code strategy for CI/CD use.
- `MiniCodexAgent.run()` now returns a structured `RunResult`.
- CLI maps user/config, model/action, test, policy, and tool failures to stable process exit codes.
- Added regression tests for success, model/action failure, failed tests, policy blocks, tool failures, max-step exhaustion, and CLI propagation.

## 2.5.0 - Runtime config enforcement

- Applied project config fields consistently at runtime instead of leaving them as documentation-only settings.
- Added runtime config fields for `scan_secrets_before_pr`, `max_agent_batch_size`, `enabled_plugins`, and `policy_file`.
- Wired `enabled_plugins` through the `ToolSpec` dispatch gate while preserving `--no-project-config` behavior.
- Added custom `policy_file` support for policy read/update/check and command/write/patch enforcement.
- Enforced `scan_secrets_before_pr` before PR draft/API workflows, blocking high/critical findings by default.
- Applied `max_agent_batch_size` to legacy task batches and bounded multi-agent role execution.
- Added regression tests for all newly wired runtime config fields.

## 2.4.0 - Bounded multi-agent execution

- Added real bounded local multi-agent execution via `run_multi_agent_work`.
- Added per-role worker state, model client, tool allowlist, step budget, and model-call budget.
- Added read-only parallel execution mode with automatic downgrade to sequential when write-capable roles are selected.
- Added persisted `.minicodex/multi_agent_runs/*.json` summaries and `list_multi_agent_runs`.
- Kept `plan_multi_agent_work` for planning and `run_task_batch` as legacy task-batch bookkeeping.

## 2.3.0 - GitHub REST integration

- Added real GitHub REST API integration tools: `create_github_pr` and `create_github_issue`.
- Kept safe command-draft helpers: `prepare_github_pr` and `prepare_github_issue`.
- Added `--allow-github-api-writes` and `allow_github_api_writes` project config.
- Real GitHub writes now require a GitHub token and manual confirmation even in auto-approval mode.
- Added dry-run API request previews and GitHub integration tests.

## 2.2.0 - Developer-preview metadata wording

### Changed
- Reworded README and package metadata so MiniCodex is presented as a developer-preview / experimental local coding-agent framework, not a drop-in Codex replacement.
- Updated the project description to use “safety guardrails” instead of stronger product-safety language.
- Clarified that the intended use is controlled local experiments, education, and supervised developer workflows.

## 2.1.0 - README test-count cleanup

### Fixed
- Removed stale fixed test-count claims from README.
- Replaced count-based marketing language with a stable description of the pytest suite, coverage gate, CLI integration tests, security regressions, and smoke workflows.
- Clarified that users should run the current test/coverage commands to verify the exact suite size in their checkout.

## 2.0.0 - Professional quality and CI layer

- Added a professional quality/CI test layer.
- Added CLI integration tests for setup, demo generation, missing-goal errors, and invalid-root errors.
- Added agent run-loop integration tests using a deterministic model client.
- Added tool-dispatch integration coverage across filesystem, shell, project, memory, Git/GitHub, security, and Python analysis tools.
- Added security regression coverage for shell-injection blocking, approval behavior, and terminal session execution.
- Added config-validation, action-schema, model retry, interactive REPL, and package metadata tests.
- Added coverage configuration with an 85% release gate.
- Added GitHub Actions CI for Python 3.10/3.11/3.12, Ruff, mypy, pytest coverage, package build, twine check, and CLI smoke testing.
- Added `.pre-commit-config.yaml` and `docs/testing.md`.
- Expanded the suite to 145 passing tests with 85.33% source coverage in the local verification environment.

## 1.9.0 - Default policy cleanup

- Fixed the default project policy contradiction around `.env.example`.
- Added `allow_env_examples=true` so documented env example/template files can be written while real `.env` files remain blocked.
- Kept `.env`, `.env.*`, `.env.local`, and `.env.*.local` blocked by default, with a narrow exception for `.env.example`, `.env.sample`, and `.env.template` style files.
- Updated setup wizard policy generation so creating `.env.example` no longer conflicts with the policy it creates.
- Added regression tests for `.env.example` allowance and real env-file blocking.

## 1.8.0 - Transactional patch engine

- Reworked `apply_patch` into a transactional patch engine.
- Added preflight validation before filesystem mutation.
- Added support for text file creation, modification, deletion, rename/move, and chmod-style mode changes from git diffs.
- Added conservative fuzzy hunk positioning support in the patch engine.
- Improved CRLF preservation for added lines.
- Added best-effort rollback if a multi-file patch fails mid-transaction.
- Switched patch backups to collision-resistant UUID suffixes.
- Binary patch payloads are detected and explicitly rejected instead of partially applying.

## 1.7.0 - Strict action validation

- Added strict action-specific model output validation.
- Rejected unsupported top-level keys and unsupported action arguments.
- Added argument type validation for strings, integers, booleans, arrays, objects, enums, and severity/status fields.
- Added generated JSON Schema for MiniCodex model actions.
- OpenAI provider now requests structured JSON-schema output when supported.
- Added repair retry loop for invalid JSON/action schema responses.
- Added provider timeout, max-output-token, retry/backoff, model call budget, and optional estimated cost budget controls.
- Added CLI flags for model I/O limits and structured output.
- Added regression tests for strict schema validation, structured output call arguments, model budget, and repair behavior.

## 1.6.0 - Runtime action dispatcher refactor

- Refactored runtime action execution from the large `agent.py` if/elif dispatcher into a central `ToolSpec` registry.
- Added `tool_registry.py` with `ToolSpec`, registry loading, runtime dispatch, and generated runtime tool reference.
- Added modular built-in tool handler modules under `src/minicodex_agent/tools/`: filesystem, shell, git, security, project, memory, github, Python diagnostics/refactor, diagnostics, and control.
- Kept plugin enforcement in the registry dispatch path so disabled tools are blocked before handlers run.
- Added `ToolContext` to pass config, state, logger, approval, print, and auto-snapshot dependencies to handlers without importing the agent class.
- Reduced `agent.py` from roughly 1024 lines to roughly 344 lines.
- Added registry coverage tests proving every `ACTION_SPECS` action has an executable `ToolSpec` and schema reference.

## 1.5.0 - Snapshot policy enforcement

- Implemented runtime enforcement for `auto_snapshot_before_edit`.
- Added a one-per-run automatic snapshot gate before the first real `write_file`, `replace_in_file`, `apply_patch`, or non-preview `rename_python_symbol` edit.
- Added `--no-auto-snapshot-before-edit` CLI override and project-config application for the snapshot setting.
- Snapshot failures now require manual confirmation before continuing, even under `approval=auto`.
- Skipped automatic snapshots during dry-run/preview-only operations.
- Added UUID suffixes to snapshot IDs to avoid same-second collisions.
- Added regression tests for automatic snapshot creation, dry-run skip, config disable, and snapshot-failure blocking.

## 1.4.0 - Run logger redaction

- Added default redaction for RunLogger metadata, events, plans, and final JSON outputs.
- Added recursive log sanitization for model arguments, observations, command output, diffs, and file-content-like strings.
- Added per-value log truncation to avoid storing large command outputs or diffs in `.minicodex/runs`.
- Added `--no-log` and `log_enabled` config support to disable run logging completely.
- Added `log_redaction=true` and `max_log_value_chars` project config defaults.
- Added regression tests proving API keys are not written into run logs and disabled logging creates no files.

## 1.3.0 - Secret scanner false-positive reduction

- Reduced secret-scanner false positives by limiting high-entropy checks to assignment/value contexts.
- Added secret finding severity levels: low, medium, high, and critical.
- Added PR/release blocking semantics: only high and critical findings block by default.
- Suppressed common placeholder values in `.env.example` and documentation-style examples.
- Skipped noisy contexts such as TOML section headers, imports, function/class definitions, and normal Python references.
- Added `minimum_severity` filtering to the `scan_secrets` action.
- Updated project health reports to include severity counts and explicit blocking status.
- Added regression tests for placeholders, normal code contexts, assignment-only entropy checks, and severity filtering.

## 1.2.0 - Shell-free command execution

- Replaced shell-based command execution with argv-based `subprocess.run(..., shell=False)`.
- Added shell-control syntax rejection for pipes, redirection, chaining, newlines, and command substitution.
- Made `strict` the default safety profile.
- Added explicit network/install command permission via `allow_network_commands` / `--allow-network-commands`.
- Prevented high-risk and network/install commands from silently running under `approval=auto`.
- Added `sandbox_mode` / `--sandbox-mode restricted|docker`; Docker mode is best-effort and disables container network.
- Added command-sandbox regression tests.

## 1.1.0 - Plugin allowlist enforcement

- Enforced `enabled_plugins` at runtime before every model action.
- Added `check_tool_access` / `is_tool_enabled` plugin access decisions.
- Added execution and diagnostics built-in plugin coverage so every action is mapped or explicitly control-flow.
- Merged enabled plugin `policies` into effective project policy for writes, patches, and commands.
- Added regression tests for tool blocking and plugin policy enforcement.

## 1.0.0 - First-run setup wizard

- Added first-run setup wizard.
- Added demo project generator.
- Added project health report helper.
- Added release checklist and release notes helper.
- Added CLI flags: `--setup`, `--setup-overwrite`, `--create-demo`, `--create-demo-overwrite`.
- Updated package metadata and docs for the first stable release.
- Kept policy-aware file and command operations from v0.9.
- Kept snapshots, rollback checks, task memory, task queue, provider registry, plugin manifest validation, secret scanning, and PR preparation.

## 0.9.0 - Project policy enforcement

- Added project policy enforcement.
- Added plugin manifest validation and enabled-tool listing.
- Added bounded multi-agent task planning and task batch records.

## 0.8.0 - Project config and provider registry

- Added project config, provider registry, change review, terminal sessions, and plugin manifests.

## 0.7.0 - Interactive mode and rollback checks

- Added interactive mode, secret scanning, rollback policy checks, and task queue.

## 0.6.0 - Snapshots and task memory

- Added snapshots, task memory, commit message generation, task decomposition, and code maps.
