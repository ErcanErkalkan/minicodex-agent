# MiniCodex Agent - Unified Project Documentation

> Canonical documentation consolidated from the project's user guides, changelog, and archived engineering reports. Security-test fixture Markdown is intentionally excluded.

## Contents

- [Project documentation](#project-documentation)
- [Changelog](#changelog)
- [Historical engineering reports](#historical-engineering-reports)
- [Source inventory](#source-inventory)

## Project Documentation

### MiniCodex Agent

_Source: `README.md`_

MiniCodex Agent is a local, tool-based coding-agent framework for repository analysis, safe edits, tests, evals, telemetry, prompt optimization, GitHub workflows, and release readiness.

Current package version: **4.4.23**.

#### What is included

- Local coding-agent loop with strict action schema validation.
- Provider abstraction for OpenAI/OpenAI-compatible, Ollama, LM Studio, llama.cpp, stub, and echo providers.
- Context pack with relevant files, compacted observations, skill metadata, and security-gated repo-local instructions.
- Tool registry for filesystem, shell, testing, code search, patching, security, telemetry, evals, GitHub, and quality gates.
- Local security layer: secret scan, SAST fallback, repo-instruction prompt-injection scan, plugin permission validation, and workspace trust reports.
- Eval layer with built-in tasks, provider baselines, telemetry-linked eval reports, and deterministic prompt A/B comparison.
- Optimization telemetry: token/cost breakdown, latency histograms, failure taxonomy, optimization dashboard, and model price catalog.
- Release gates: marker-aware test matrix, final readiness report, documentation CLI example validation, release package manifest, generated artifact cleanup, CI quality-tool checks.

#### Install

```bash
python -m pip install -e ".[dev]"
```

For a minimal runtime install:

```bash
python -m pip install -e .
```

#### Quick start

```bash
minicodex "inspect the project and suggest the safest next test" --root . --provider stub --max-steps 1
```

Run a local readiness report:

```bash
minicodex --final-readiness --root .
```

Run security checks only:

```bash
minicodex --security-audit --root .
minicodex --scan-repo-instructions --root .
```

Inspect optimization telemetry:

```bash
minicodex --optimization-dashboard --root .
minicodex --failure-dashboard --root .
minicodex --model-price-table --root .
```

Run prompt A/B comparison offline with the stub provider:

```bash
minicodex --run-prompt-ab --prompt-ab-profiles auto,local-model --provider stub --root .
```

#### Documentation

- [Usage guide](#usage-guide)
- [Security model](#security-model)
- [Local LLM providers](#local-llm-providers)
- [Evals and prompt A/B](#evals-telemetry-and-prompt-ab)
- [GitHub integration](#github-integration)
- [Architecture](#architecture)
- [Quickstart](#quickstart)
- [Testing and CI](#testing-and-ci)

#### Security note about repo instructions

Repo-local files such as `AGENTS.md`, `.minicodex/instructions.md`, and `.minicodex/AGENTS.md` are useful but untrusted. In v4.4.13, MiniCodex scans repo instructions before building the model context. High/critical prompt-injection or secret-exfiltration findings are blocked from the prompt, and the context pack records the file as `blocked_by_security_scan` instead of inserting the raw malicious text.

#### Release quality gates

The package defines and documents release checks for:

```bash
ruff check .
ruff format --check .
mypy src/minicodex_agent
python scripts/run_coverage_gate.py --group all --fail-under 85 --json
python -m build
twine check dist/*
```

The local environment may not always have these tools installed. The GitHub CI workflow installs `.[dev]` and runs these checks before release.

Useful release helpers:

```bash
minicodex --release-package-manifest --root .
minicodex --release-package-manifest --from-zip path/to/release.zip --root .
minicodex --clean-generated-artifacts --root .
```

When `--from-zip` is used, the manifest derives version, top-level docs, source module counts, test counts, and generated-artifact findings from the zip members only. The reported `root_used_for_metadata: false` field is a guardrail against accidentally mixing working-tree metadata into an artifact report.

Final readiness also validates user-facing documentation coverage and parses documented `minicodex` command examples against the CLI parser so stale flags are reported as readiness failures.

#### Development status

This is a developer-preview local coding-agent framework. It is designed for local experimentation, repository automation, and CI-assisted quality gates. External model/API calls and GitHub write actions remain gated by provider configuration, network policy, and explicit runtime options.

### Quickstart

_Source: `docs/quickstart.md`_

Install in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Run an offline smoke test:

```bash
minicodex "inspect this repository" --provider stub --root . --max-steps 1 --no-diff --non-interactive
```

Run a normal agent task:

```bash
minicodex "fix the smallest failing test" --root . --provider openai --approval ask
```

Use a local model:

```bash
minicodex "review the recent changes" --root . --provider ollama --model qwen3-coder --prompt-profile local-model
```

Run security and readiness reports without a model call:

```bash
minicodex --scan-repo-instructions --root .
minicodex --security-audit --root .
minicodex --final-readiness --root .
```

Inspect telemetry and eval optimization data:

```bash
minicodex --optimization-dashboard --root .
minicodex --failure-dashboard --root .
minicodex --run-prompt-ab --prompt-ab-profiles auto,local-model --provider stub --root .
```

Release cleanup and manifest:

```bash
minicodex --clean-generated-artifacts --root .
minicodex --release-package-manifest --root .
minicodex --release-package-manifest --from-zip path/to/release.zip --root .
```

More details:

- [Usage guide](#usage-guide)
- [Security model](#security-model)
- [Local LLM providers](#local-llm-providers)
- [Evals and prompt A/B](#evals-telemetry-and-prompt-ab)
- [Architecture](#architecture)

### Usage guide

_Source: `docs/usage.md`_

MiniCodex can run as a local coding agent or as a collection of deterministic inspection commands.

#### Basic agent run

```bash
minicodex "fix the failing unit test" --root . --provider stub --max-steps 3
```

Important options:

- `--root .` selects the repository root.
- `--provider stub` runs offline and is useful for smoke tests.
- `--provider openai`, `--provider ollama`, `--provider lmstudio`, or `--provider openai_compatible` selects a real model provider.
- `--approval ask` keeps risky actions behind manual confirmation.
- `--dry-run` prevents writes.
- `--no-log` disables local run logging.
- `--no-context` disables context-pack injection.

#### Context pack

The context pack contains compact metadata for the current step:

- project profile
- relevant file hints
- compacted observations
- skill catalog metadata
- repo-local instruction metadata

Repo-local instructions are not blindly trusted. `AGENTS.md` and `.minicodex` instructions are scanned first. High/critical risks are blocked from prompt inclusion.

#### Tool-oriented commands

MiniCodex exposes many operations without calling a model:

```bash
minicodex --project-health --root .
minicodex --test-matrix-plan --root .
minicodex --final-readiness --root .
minicodex --security-audit --root .
minicodex --scan-repo-instructions --root .
minicodex --optimization-dashboard --root .
```

#### Release helpers

Use a working-tree manifest when checking the current checkout:

```bash
minicodex --release-package-manifest --root .
```

Use a zip manifest when checking an immutable release artifact:

```bash
minicodex --release-package-manifest --from-zip dist/minicodex-agent.zip --root .
```


In `--from-zip` mode, artifact metadata is computed from the zip itself. The manifest includes `metadata_source`, `root_used_for_metadata`, `artifact_root_prefix`, and `normalized_file_count` so CI can verify that a zip report was not contaminated by the local checkout.

Clean local generated artifacts before producing a final manifest:

```bash
minicodex --clean-generated-artifacts --root .
```

Dry run cleanup first:

```bash
minicodex --clean-generated-artifacts --clean-generated-artifacts-dry-run --root .
```

### Local LLM providers

_Source: `docs/local-llm.md`_

MiniCodex supports local and OpenAI-compatible providers. Local providers are useful for offline tests, privacy-sensitive workflows, and deterministic smoke runs.

#### Stub and echo providers

```bash
minicodex "smoke test" --provider stub --root . --max-steps 1
minicodex "inspect prompt" --provider echo --root . --max-steps 1
```

These providers do not require API keys and default to zero token cost.

#### Ollama

```bash
minicodex "fix a small bug" --provider ollama --model qwen3-coder --root .
```

Ollama defaults to local zero-cost pricing in the built-in price catalog. Actual hardware/runtime cost is not estimated.

#### LM Studio / llama.cpp / OpenAI-compatible

```bash
minicodex "run a code review" --provider lmstudio --model qwen3-coder --root .
minicodex "run a code review" --provider openai_compatible --model qwen3-coder --model-base-url http://localhost:1234/v1 --root .
```

Use `--model-action-protocol auto` to let MiniCodex pick native tool calls where supported, or force JSON text with:

```bash
--model-action-protocol json_text
```

#### Price catalog

Print local pricing defaults:

```bash
minicodex --model-price-table --root .
```

Hosted-model prices are editable local defaults, not authoritative billing records. Explicit CLI/config prices override catalog defaults. Local providers, `stub`, and `echo` default to zero cost.

### Architecture

_Source: `docs/architecture.md`_

MiniCodex is organized as a local agent runtime plus deterministic tools.

#### Main layers

```text
CLI
  -> AgentConfig
  -> MiniCodexAgent
      -> prompt_engine
      -> context_manager
      -> model_client
      -> action_schema validation
      -> tool_registry dispatch
      -> telemetry recorder
```

#### Prompt and context

`prompt_engine.py` builds modular profile-aware system prompts. `context_manager.py` builds a bounded context pack containing relevant file hints, compacted observations, skill metadata, and repo-local instruction metadata.

Repo-local instructions are security-gated before prompt inclusion. Risky instruction text is replaced with blocked metadata instead of being inserted raw.

#### Model layer

`model_client.py` abstracts providers and records schema reliability. `model_pricing.py` resolves provider/model default pricing and explicit overrides. Local providers and stub/echo default to zero cost.

#### Tool layer

`action_schema.py` defines strict action schemas. `tool_registry.py` dispatches registered tools. Built-in tool modules live under `src/minicodex_agent/tools/`.

#### Security layer

`security_audit.py`, `secret_scanner.py`, and safety/workspace policy modules provide local security checks, prompt-injection scanning, fixture allowlisting, SAST fallback, plugin permission validation, and workspace trust reports.

#### Eval and optimization layer

`eval_runner.py` runs built-in eval tasks and links them to telemetry traces. `prompt_ab.py` runs deterministic prompt profile comparisons. `telemetry.py` aggregates token usage, cost, latency, failures, and dashboard summaries. `failure_taxonomy.py` classifies failures for optimization decisions.

#### Quality and release layer

`quality_gate.py` provides final readiness, test matrix planning, release manifests, zip-based manifest inspection, and generated artifact cleanup.

Release CI is expected to run:

```bash
ruff check .
ruff format --check .
mypy src/minicodex_agent
python scripts/run_coverage_gate.py --group all --fail-under 85 --json
python -m build
twine check dist/*
```

### Security model

_Source: `docs/security.md`_

MiniCodex assumes local repositories can be untrusted. The security layer is designed to stop common agent-specific risks before a model or tool follows malicious instructions.

#### Repo-local instruction scanning

Files such as these are scanned before they are included in the context pack:

- `AGENTS.md`
- `.minicodex/instructions.md`
- `.minicodex/AGENTS.md`
- repo skill files under `.minicodex/skills/*/SKILL.md`
- local plugin manifests under `.minicodex/plugins/*.json`

High/critical findings such as “ignore previous instructions”, safety bypass requests, environment dumping, network exfiltration, or secret leakage requests cause the raw instruction content to be omitted from the prompt. The context pack records the instruction with `trust_level="blocked_by_security_scan"`.

Run the scan directly:

```bash
minicodex --scan-repo-instructions --root .
```

#### Security audit

```bash
minicodex --security-audit --root .
```

The audit includes:

- secret scanning
- built-in SAST fallback
- repo-instruction scan
- plugin permission validation
- workspace trust report
- dependency audit command planning

External scanners are not run by default. They are planned unless the tool is installed and the user explicitly allows execution/network access.

#### Fixture allowlist

Intentional unsafe examples should live under:

```text
tests/fixtures/unsafe_examples/
```

or include this marker near the top of the file:

```text
# minicodex-security-test-fixture
```

The built-in security audit skips these files so fake `eval`, `shell=True`, fake API keys, or malicious `AGENTS.md` samples do not appear as real product vulnerabilities.

#### Workspace trust

For unknown repositories, prefer:

```bash
minicodex "inspect safely" --root . --untrusted-workspace --approval ask --sandbox-mode docker --sandbox-network none
```

The prompt and tool layer still treat repo content as data, not authority. Runtime tool gates, user goals, and system policy take priority over repository instructions.

### Evals, telemetry, and prompt A/B

_Source: `docs/evals.md`_

MiniCodex includes an offline-friendly eval layer for repeatable agent tasks and provider comparisons.

#### Initialize and list evals

`--list-eval-tasks` remains accepted as a backward-compatible alias, but `--list-evals` is the canonical command.


```bash
minicodex --init-evals --root .
minicodex --list-evals --root .
minicodex --eval-coverage-report --root .
```

#### Run evals

```bash
minicodex --run-eval-suite --provider stub --root .
```

Eval reports are written under `.minicodex/evals/reports/`. Each eval task is linked to a deterministic telemetry run id and, when available, the telemetry trace path, latency summary, pricing source, and failure taxonomy summary.

#### Compare eval runs

```bash
minicodex --compare-eval-baselines baseline candidate --root .
```

Comparisons include score/success deltas and, when telemetry is available, cost, latency, model-call, and failure-taxonomy deltas.

#### Prompt A/B comparison

```bash
minicodex --run-prompt-ab --prompt-ab-profiles auto,local-model --provider stub --root .
```

Prompt A/B comparison is deterministic, not a statistical significance test. The winner is selected by:

1. highest average score
2. lower failure count
3. lower total cost
4. lower p95 latency

Reports are saved as `.minicodex/evals/reports/ab-<run_id>.json`.

#### Optimization telemetry

```bash
minicodex --optimization-dashboard --root .
minicodex --failure-dashboard --root .
```

Telemetry includes:

- provider/model token and cost breakdown
- prompt profile/version/hash metadata
- latency histograms and p50/p95 summaries
- failure taxonomy
- slowest model/tool calls
- most expensive runs
- practical optimization recommendations

### GitHub integration

_Source: `docs/github.md`_

MiniCodex includes GitHub-oriented helpers for CI diagnostics, PR workflows, and GitHub App scaffolding.

#### Workflow detection

```bash
minicodex --detect-github-workflows --root .
```

#### GitHub App manifest and webhook scaffold

```bash
minicodex --generate-github-app-manifest --github-app-name "MiniCodex Agent" --root .
minicodex --init-github-webhook-server --root .
```

Webhook scaffolding is local code generation. Real deployment, secret storage, and GitHub App installation remain manual review steps.

#### CI logs and PR review workflows

The GitHub layer supports CI log fetching and review-comment resolution when GitHub API/network options are explicitly enabled. Write operations such as commit/push or review-comment posting are gated and should remain dry-run/preview-first unless the user intentionally enables GitHub writes.

Useful safety posture. `--no-github-api-writes` explicitly disables write operations and overrides any project config value that enabled them:

```bash
minicodex "inspect failing GitHub CI" --root . --approval ask --no-github-api-writes
```

#### Actions artifact upload helper

```bash
minicodex --prepare-github-artifact-upload --root .
```

This generates upload-artifact workflow guidance without performing a remote write.

### Testing and CI

_Source: `docs/testing.md`_

MiniCodex uses a marker-aware test matrix plus release quality gates.

#### Local targeted tests

```bash
PYTHONPATH=src pytest -q tests/test_context_layer_v30.py
PYTHONPATH=src pytest -q tests/test_security_product_layer_v44.py
PYTHONPATH=src pytest -q tests/test_quality_gate_layer_v45.py
```

#### Marker-aware matrix

```bash
python scripts/run_test_matrix.py --group fast --json
python scripts/run_test_matrix.py --group unit --json
python scripts/run_test_matrix.py --group integration --json
python scripts/run_test_matrix.py --group subprocess --json
python scripts/run_test_matrix.py --group sandbox --json
python scripts/run_test_matrix.py --group slow --json
python scripts/run_test_matrix.py --group all --json
```

`--final-readiness` uses the bounded `fast` group by default to avoid monolithic pytest timeouts in local checks.

#### Release quality commands

The release CI should install `.[dev]` and run bounded, marker-aware gates instead of one monolithic coverage process:

```bash
ruff check .
ruff format --check .
mypy src/minicodex_agent
python scripts/run_test_matrix.py --group fast --json
python scripts/run_test_matrix.py --group integration --json
python scripts/run_test_matrix.py --group subprocess --json
python scripts/run_test_matrix.py --group sandbox --json
python scripts/run_coverage_gate.py --group all --fail-under 85 --json
python -m build
twine check dist/*
```

Coverage must include every marker group because the 85% threshold represents the complete release suite. Per-file timeouts keep slow, subprocess, and sandbox tests bounded.

Do not use a single package-wide coverage process as a required gate for this repository; the bounded coverage script aggregates coverage while keeping each test file under a timeout. These tools may be unavailable in a constrained local environment. In that case, `--final-readiness` reports missing tools as warnings unless `--final-readiness-run-verification-tools` is used and installed tools fail.

#### Final readiness

```bash
minicodex --final-readiness --root .
minicodex --final-readiness --final-readiness-run-verification-tools --root .
```

Full verification runs Python lint, type checking, build, package validation, and file-level
coverage in an isolated temporary project copy. The default per-command timeout is 1200 seconds;
override it with `--final-readiness-verification-timeout` for slower environments.

Readiness includes:

- version alignment
- generated artifact check
- Python syntax check
- tool registry alignment
- documentation presence, including README-linked quickstart/testing docs
- documented MiniCodex CLI example parser validation
- security audit gate
- verification tool availability/results
- bounded test matrix result
- CLI smoke test

#### Security test fixtures

Intentional unsafe examples must be isolated under:

```text
tests/fixtures/unsafe_examples/
```

or marked with:

```text
# minicodex-security-test-fixture
```

This prevents fake `shell=True`, `eval`, fake tokens, and malicious instruction samples from being reported as real vulnerabilities.

#### Cleaning generated artifacts

```bash
minicodex --clean-generated-artifacts --clean-generated-artifacts-dry-run --root .
minicodex --clean-generated-artifacts --root .
```

#### Zip-based release manifest

Use this when local test runs have created caches in the working tree but you want to validate the actual archive:

```bash
minicodex --release-package-manifest --from-zip dist/release.zip --root .
```


The zip manifest is intentionally artifact-sourced. In this mode, version, documentation list, source module counts, test counts, and generated-artifact findings come from zip members only; `root` is only used to resolve a relative zip path.

## Changelog

_Source: `CHANGELOG.md`_

### 4.4.23 - Release artifact and CLI polish hardening

- Aligned zip artifact names with the single top-level artifact root and exposed that invariant in release manifests.
- Added CI/release `ruff format --check .` coverage to match the pre-commit formatting policy.
- Removed the unused `types-python-dateutil` development dependency.
- Standardized public CLI help text in English and added checks to prevent mixed-language help regressions.

### 4.4.22 - Release positioning consistency

- Clarified package positioning so MiniCodex remains an alpha/developer-preview framework with release-readiness and quality-gate checks, not a claimed deployment-grade product.
- Reworded the older v4.4 quality-gate entry from overstated readiness language to “release-readiness / quality-gate baseline.”
- Added final-readiness validation that flags user-facing docs or changelog text that reintroduce deployment-grade claims inconsistent with the alpha classifier.

### 4.4.21 - Changelog structure hardening

- Normalized `CHANGELOG.md` to a single top-level `# Changelog` heading and one canonical entry per release version.
- Converted release headings to the consistent `## x.y.z - Title` format and removed duplicated historical sections that repeated 4.4.6, 4.4.3, 4.4.1, and 2.9.0.
- Added changelog structure validation to final readiness so duplicate versions, repeated `# Changelog` headings, `v`-prefixed headings, and out-of-order release entries are caught before packaging.
- Added regression coverage for changelog normalization and final-readiness reporting.

### 4.4.20 - Typecheck command consistency

- Standardized Python typecheck suggestions with CI and README by making src-layout projects prefer package-scoped `mypy src/<package>` commands instead of broad `mypy .`.
- Added regression coverage to prevent MiniCodex from recommending `mypy .` for its own src-layout package and to keep docs, CI, release, and language-adapter typecheck scope aligned.

### 4.4.19 - Documentation gate coverage

- Expanded documentation presence checks to include `docs/quickstart.md`, `docs/testing.md`, and Markdown files referenced from README documentation links.
- Added a documentation CLI example validator that parses documented `minicodex` commands against the real CLI parser without executing agent actions.
- Added regression coverage so missing user-facing docs or stale documented CLI flags fail the readiness documentation checks instead of silently passing.

### 4.4.18 - Framework detection false-positive fix

- Hardened framework detection to avoid treating detector pattern-table string literals, route catalogs, docs, or tests as application framework evidence.
- Replaced broad repository sample-text framework matching with dependency/config/path evidence and AST import/call evidence for Python web frameworks.
- Added regression coverage proving MiniCodex itself reports pytest tooling only, not false Django/FastAPI/Flask application frameworks, while real FastAPI/Flask imports remain detectable.

### 4.4.17 - Release manifest zip provenance

- Harden release package manifests so `--from-zip` derives version, top-level docs, source module counts, test counts, and generated-artifact findings exclusively from the zip artifact.
- Add explicit manifest provenance fields: `metadata_source`, `root_used_for_metadata`, `artifact_root_prefix`, and `normalized_file_count`.
- Count nested `src/minicodex_agent/**/*.py` modules and nested `tests/**/test_*.py` tests consistently for both zip and working-tree manifests.
- Add regression coverage proving fake working-tree metadata cannot contaminate zip-sourced manifests.

### 4.4.16 - Syntax-only test matrix plan

- Hardened the test matrix plan so the syntax step is explicitly bytecode-free and never aliases to `run_test_matrix.py`.
- Added `scripts/` to the syntax-check scope used by the readiness plan and recommended CI commands.
- Added regression coverage preventing `--max-files 0` from reappearing in the syntax/readiness path.

### 4.4.15 - Matrix coverage gate

- Replaced remaining monolithic CI/release coverage commands with a bounded, marker-aware, file-level coverage gate.
- Added `scripts/run_coverage_gate.py` so coverage collection uses per-file timeouts and the same marker policy as `scripts/run_test_matrix.py`.
- Updated testing documentation, architecture notes, final-readiness recommendations, and verification-tool specs to consistently recommend matrix-first testing plus file-level coverage.
- Added regression coverage to prevent reintroducing `pytest --cov` or plain `pytest -q` as package-level CI gates.

### 4.4.14 - Documented CLI flag compatibility

- Added the documented `--project-health` CLI shortcut for the existing project health report, so `docs/usage.md` commands now execute without falling through to a model run.
- Added backward-compatible `--list-eval-tasks` support while keeping `--list-evals` as the canonical eval listing command.
- Added explicit `--no-github-api-writes` CLI support that overrides project config and keeps GitHub write operations disabled unless `--allow-github-api-writes` is intentionally selected.
- Added regression tests for the documented CLI flags and refreshed docs to identify canonical commands and safe GitHub write posture.
- Replaced misleading test-matrix syntax planning with a bytecode-free AST syntax checker script.
- Hardened zip release manifests so zip-mode version, docs, source-module, and test-file counts are derived from the immutable archive, not the mutable working tree.
- Aligned CI, release, and pre-commit examples with the marker-aware test matrix to reduce monolithic pytest timeout risk.

### 4.4.13 - Security and release documentation hardening

- Hardened repo-local instruction handling: AGENTS.md/.minicodex instructions are scanned before prompt inclusion, high/critical findings are blocked from context, and prompts state that repo instructions are untrusted unless validated.
- Added security audit fixture allowlisting with `tests/fixtures/unsafe_examples/` and `# minicodex-security-test-fixture` so intentional unsafe samples are not reported as real findings.
- Extended release/readiness helpers with `--release-package-manifest --from-zip ...`, `--clean-generated-artifacts`, generated artifact cleanup, and explicit ruff/mypy/build/twine/pytest-cov release quality gates.
- Split the oversized README into focused docs: usage, security, local LLMs, evals, GitHub, and architecture.

### 4.4.12 - GitHub workflow integration

- Upgraded GitHub integration from mostly preview helpers to a fuller GitHub-agent workflow layer.
- Added GitHub App manifest generation, signed webhook server scaffolding, real GitHub Actions CI log fetch support, review comment resolver/planned posting, gated branch/add/commit/push execution, and upload-artifact workflow support.
- Added tools: `generate_github_app_manifest`, `init_github_webhook_server`, `fetch_github_ci_log`, `execute_commit_push_workflow`, `resolve_review_comments`, `prepare_github_artifact_upload`, and `create_github_review_comment`.
- Strengthened security gates: real CI fetch requires network/API enablement, push/review-comment writes require explicit GitHub write enablement and manual approval, and dry-run/preview remains the default path.

### 4.4.11 - AST-aware patch/refactor layer

- Added an AST-aware patch/refactor layer with capability reporting, semantic edit planning, native Python AST validation, grammar-aware TypeScript/Java/Go/Rust token edits, import organization, conservative dead-code detection/cleanup, and formatter-after-edit verification.
- Added tools: `ast_patch_capability_report`, `plan_semantic_edit`, `rename_symbol_semantic`, `organize_imports`, `detect_dead_code`, `cleanup_dead_code`, and `format_and_verify`.
- Extended the code-intelligence plugin, action schema, trust gates, and prompt guidance so semantic refactors prefer AST-aware tools over raw text replacement.

### 4.4.10 - Semantic language layer

- Added a semantic language layer with Python AST symbols, grammar-aware TypeScript/Java/Go/Rust symbol extraction, cross-file symbol reference lookup, framework route inspection, and parser capability reporting.
- Added semantic code intelligence tools: semantic_capability_report, build_semantic_index, find_symbol_references, and inspect_routes.
- Added CLI shortcuts for semantic reports and extended code-intelligence plugin/action schema coverage.

### 4.4.9 - Expanded Codex-claim eval benchmarks

- Expanded built-in eval benchmarks with hard Codex-claim categories: multi-file Python bugfix, TypeScript/React refactor, Java/Maven test fix, security patch, dependency upgrade, CI repair, large diff review, malicious instruction defense, long-horizon, and multi-agent tasks.
- Added `eval_coverage_report` tool and `--eval-coverage-report` CLI.
- Added claim-suite baseline manifests for `gpt-5.3-codex`, `gpt-5.5`, Ollama Qwen coder, and LM Studio local models.
- Baseline command plans now include local model action protocol options where relevant.

### 4.4.8 - Local native tool-calling provider hardening

- Added native Chat Completions `tools/tool_calls` support for OpenAI-compatible/local providers.
- Added `--model-action-protocol auto|json_text|tool_calls`; `auto` now prefers native tool calls for Ollama/LM Studio/llama.cpp/OpenAI-compatible endpoints and falls back to JSON text when unsupported.
- Added real-time stream UI plumbing with `--model-stream-ui`.
- Added provider schema-reliability metrics for native tool calls, JSON-text actions, validation success/failure counts, and repair prompt counts.
- Split local model prompt guidance so native tool-call and JSON-text protocols are not mixed.

### 4.4.7 - Expanded eval benchmarks and baseline manifests

- Expanded the built-in eval suite from smoke/docs tasks into mixed-language benchmark coverage: Python bugfix/security/CI repair, TypeScript, React accessibility, Java, Go, Rust, and malicious repo instruction defense.
- Added provider/model eval baseline manifests for `stub`, OpenAI/Codex-style, Ollama, LM Studio, and full release regression plans.
- Added `init_eval_baselines`, `list_eval_baselines`, `eval_baseline_plan`, and `compare_eval_baselines` tools.
- Added CLI shortcuts: `--init-eval-baselines`, `--list-eval-baselines`, `--eval-baseline-plan`, and `--compare-eval-baselines`.
- Added regression tests to ensure baselines reference real built-in tasks and expose reproducible commands without making API calls.

### 4.4.6 - Marker-aware test matrix and CI split fix

- Added automatic pytest marker assignment for `unit`, `integration`, `subprocess`, `sandbox`, and `slow` tests via `tests/conftest.py`.
- Upgraded `scripts/run_test_matrix.py` with marker groups, group-specific timeouts, JSONL progress streaming, and graceful handling of deselected files.
- Updated final-readiness to use a fast marker-aware bounded test gate by default while still supporting full/integration/subprocess/sandbox/slow groups.
- Added marker-aware test matrix planning and documentation so CI can split fast PR checks from heavier scheduled/full checks.

### 4.4.5 - Run-wide isolated workspace fix

- Added agent-level isolated workspace mode so all file reads/writes/patches can run on a filtered workspace copy instead of the original project tree.
- Added reviewable isolated workspace diff and manifest exports under `.minicodex/agent_workspaces/`.
- Added explicit apply policy: `never`, `ask`, or `auto`, with sensitive paths blocked during sync-back.
- Added CLI flags for run-wide workspace isolation and regression tests for diff/export/apply behavior.

### 4.4.4 - Bytecode-clean final readiness fix

- Prevented final-readiness and bounded test-matrix checks from leaving `__pycache__` / `.pyc` artifacts in the project tree.
- Added structural bytecode cleanup metadata to final readiness reports.
- Updated CLI smoke/test-matrix subprocesses to run with `-B` and `PYTHONDONTWRITEBYTECODE=1`.
- Replaced test-matrix `compileall` bytecode generation with syntax-only in-memory compilation.

### 4.4.3 - Machine-readable JSON report truncation fix

- Fixed final-readiness and release-manifest JSON rendering so reports are never cut mid-token.
- Added structured `truncated`, `omitted_count`, and size metadata when reports exceed requested max chars.
- Updated quality-gate tool output to render bounded valid JSON for test matrix plans.

### 4.4.2 - Final readiness security and verification gates

- Added a release-blocking security gate to final readiness reports.
- Added bounded test-matrix execution results to final readiness.
- Added build/lint/typecheck verification gate with optional execution.
- Added safe PYTHONDONTWRITEBYTECODE handling for readiness subprocesses.
- Added --max-files support to scripts/run_test_matrix.py for bounded readiness checks.

### 4.4.1 - Security audit false-positive hardening

- Fixed built-in SAST false positives from Python string literals and rule-definition fixtures.
- Replaced OpenAI-shaped fake test secret with a non-provider redaction fixture value.
- Added regression tests ensuring scanner rules still detect executable unsafe code.

### 4.4.0 - Final readiness / quality-gate layer

- Added a final readiness layer with deterministic version, syntax, registry, documentation, generated-artifact, and CLI smoke checks.
- Added tools: `final_readiness_report`, `test_matrix_plan`, and `release_package_manifest`.
- Added CLI shortcuts: `--final-readiness`, `--test-matrix-plan`, and `--release-package-manifest`.
- Added `scripts/run_test_matrix.py` to run tests by file with per-file timeouts, avoiding monolithic pytest timeout behavior caused by subprocess-heavy tests.
- Added the `quality-gates` built-in plugin and regression tests in `tests/test_quality_gate_layer_v45.py`.
- Updated package docs and release reports for a v4.4 release-readiness / quality-gate baseline.

### 4.3.0 - Product security layer

- Added product-level security audit helpers: `security_audit_report`, `run_sast_scan`, `run_dependency_audit`, `scan_repo_instructions`, `validate_plugin_permissions`, and `workspace_trust_report`.
- Added built-in lightweight SAST fallback for risky patterns such as `shell=True`, `eval`, `exec`, unsafe YAML loading, Node `child_process.exec`, and committed private keys.
- Added dependency audit command planning for Python, Node, pnpm/yarn, Rust, and Go projects while keeping network-dependent execution opt-in.
- Added repo-local instruction prompt-injection scanning for `AGENTS.md`, `.minicodex/instructions.md`, skills, and plugin manifests.
- Added local plugin permission declarations and validation for filesystem, command, GitHub, memory, telemetry, and security-audit permissions.
- Added untrusted workspace guardrails that block high-impact actions when `--untrusted-workspace` is combined with `--approval auto`.
- Added security CLI shortcuts: `--security-audit`, `--scan-repo-instructions`, `--untrusted-workspace`, and related budget/timeout settings.

### 4.2.0 - Modular prompt layer

- Added a profile-aware modular prompt engine with versioned prompt sections and task profiles.
- Added prompt profiles: `auto`, `general`, `bugfix`, `review`, `refactor`, `test-ci`, `security`, `docs`, `github`, `eval`, `long-horizon`, `local-model`, and `frontend`.
- Added provider/goal-based prompt inference and per-run prompt bundle metadata.
- Added CLI shortcuts: `--prompt-profile`, `--prompt-preview`, `--list-prompt-profiles`, `--prompt-max-chars`, `--no-prompt-action-reference`, and `--prompt-preview-max-chars`.
- Added prompt tools: `list_prompt_profiles`, `render_prompt_bundle`, and `validate_prompt_contract`.
- Updated `ModelClient` so every agent run can use a profile-aware system prompt instead of the old global prompt string.
- Added project-config defaults and a `prompting` built-in plugin.
- Added regression tests in `tests/test_prompt_layer_v43.py`.

### 4.1.0 - Observability / telemetry layer

- Added local telemetry traces with span timing, token/cost ledger aggregation, risk events, prompt versioning, and sanitized JSON/JSONL exports.
- Added observability tools: `list_telemetry_runs`, `read_telemetry_run`, `telemetry_summary`, `compare_telemetry_runs`, and `export_telemetry_bundle`.
- Added CLI shortcuts: `--telemetry-summary`, `--read-telemetry-run`, `--export-telemetry-bundle`, `--telemetry-run-id`, and `--no-telemetry`.
- Added project-config defaults for telemetry and an `observability` built-in plugin.

### 4.0.0 - GitHub workflow layer

- Added GitHub Actions workflow inspection and a conservative MiniCodex workflow template generator.
- Added PR slash-command parsing for `/minicodex ...` comments with safe dry-run defaults.
- Added branch/commit/push planning without executing git side effects.
- Added GitHub Actions CI log summarization and CI fetch previews for `gh run view`/REST endpoints.
- Registered the new GitHub integration tools in action schema, runtime registry, and built-in plugin metadata.

### 3.9.0 - Eval benchmark harness

- Added an eval/benchmark harness for measuring agent quality across model, prompt, context, and tool changes.
- Added deterministic eval task descriptors under `.minicodex/evals/tasks/*.json` with fixture files, expected file assertions, verification commands, and metadata.
- Added disposable eval workspaces under `.minicodex/evals/runs/<run_id>/<task_id>/workspace` and aggregate reports under `.minicodex/evals/reports/*.json`.
- Added tools: `init_eval_suite`, `list_eval_tasks`, `read_eval_task`, `run_eval_task`, `run_eval_suite`, `list_eval_runs`, `read_eval_run`, and `compare_eval_runs`.
- Added scoring for required/forbidden changed files, file contains/not-contains checks, verification command exit codes, agent exit code, model call/token/cost usage, duration, and changed-file metrics.
- Added CLI shortcuts: `--init-evals`, `--list-evals`, `--run-eval`, `--run-eval-suite`, `--eval-run-id`, and eval budget/report controls.
- Added the `evals` built-in plugin and regression tests in `tests/test_eval_layer_v40.py`.

### 3.8.0 - Language/framework intelligence layer

- Added a language/framework intelligence layer for multi-language repositories.
- Added dependency-free adapters for Python, TypeScript/JavaScript, Java/Kotlin, Go, and Rust.
- Added tools: `detect_language_stack`, `inspect_frameworks`, `suggest_verification_commands`, and `language_adapter_report`.
- Extended project profiles with `languages`, `frameworks`, `typecheck_commands`, and `format_commands`.
- Added framework/toolchain detection for FastAPI, Django, Flask, pytest, Next.js, React, Vite, Vue, Angular, NestJS, Express, Spring Boot, JUnit, Gin, Fiber, Go Echo, Axum, Actix Web, Rocket, and Tauri.
- Updated `plan_tests`/`run_targeted_tests` with `include_typecheck` so verification loops can include language-aware typecheck commands.
- Updated prompt guidance, action schema, runtime registry, plugin metadata, and relevant-file key config discovery for language-aware workflows.
- Added regression tests in `tests/test_language_layer_v39.py`.

### 3.7.0 - Developer experience layer

- Added a developer-experience layer for terminal review and IDE-oriented workflows.
- Added tools: `render_tui_panel`, `create_review_bundle`, `list_review_bundles`, `read_review_bundle`, `record_review_decision`, `run_summary`, and `export_ide_bridge`.
- Added JSON review bundles under `.minicodex/review_bundles/*.json` with status, numstat, staged/unstaged diff previews, and approval decisions.
- Added a dependency-free terminal developer panel for status and diff preview without calling a model.
- Added saved-run summaries for `.minicodex/runs` transcripts so agents and humans can inspect prior runs compactly.
- Added `.minicodex/ide/bridge.json` export for future VS Code/IDE integrations.
- Added CLI flags: `--dev-panel`, `--review-after-run`, `--review-bundle-max-diff-chars`, and `--export-ide-bridge`.
- Updated action schema, runtime registry, plugin metadata, project config, and prompt guidance for developer UX workflows.
- Added regression tests in `tests/test_dev_experience_layer_v38.py`.

### 3.6.0 - Long-horizon task layer

- Added a long-horizon task layer for durable multi-session work.
- Added JSON-backed `.minicodex/long_horizon/runs/*.json` state files with goals, acceptance criteria, milestones, and checkpoints.
- Added tools: `create_long_task`, `list_long_tasks`, `read_long_task`, `resume_long_task`, `update_acceptance_criteria`, and `create_checkpoint`.
- Added compact resume packs so future runs can continue from the latest checkpoint without replaying the full transcript.
- Added optional automatic checkpointing with `--long-horizon`, `--long-horizon-run-id`, and `--long-horizon-auto-checkpoint-interval`.
- Updated config defaults, plugin metadata, runtime registry, action schema, CLI help, and prompt guidance for long tasks.
- Added regression tests in `tests/test_long_horizon_layer_v37.py`.

### 3.5.0 - Subagent orchestration

- Added Codex-style subagent thread orchestration on top of bounded role workers.
- Added `AgentThread`, `AgentMailbox`, and `AgentResultMerger` primitives for auditable parent/child coordination.
- Added `plan_subagent_threads`, `run_subagent_threads`, and `read_multi_agent_run` tools.
- Enhanced `run_multi_agent_work` payloads with `threads`, `mailbox`, `thread_model`, and `merged_result`.
- Added mailbox handoffs: each completed role posts a result message to `recipient=all` for later workers.
- Added configurable transcript/result budgets: `multi_agent_thread_max_messages`, `multi_agent_result_max_chars`, and `multi_agent_allow_parallel_writes`.
- Updated action schema, runtime registry, plugin metadata, CLI/config defaults, and prompt rules for subagent threads.
- Added regression tests in `tests/test_multi_agent_layer_v36.py`.

### 3.4.0 - Repo-local skill manager

- Added repo-local skill manager with front-matter parsing, ranking, validation, and safe progressive disclosure.
- Added skill tools: `list_skills`, `read_skill`, `validate_skills`, and `init_skill`.
- Added `skills` built-in plugin and registered skill actions in the strict action schema.
- Extended context pack skill metadata with title, description, triggers, tags, and when-to-use hints.
- Added CLI/project config fields for skill discovery and read budgets.
- Setup wizard now creates `AGENTS.md` plus an example `.minicodex/skills/targeted-testing/SKILL.md`.
- Added regression tests in `tests/test_skill_layer_v35.py`.

### 3.3.0 - Test/CI verification layer

- Added a Test/CI verification layer for Codex-like edit loops.
- Added `plan_tests` and `run_targeted_tests` tools.
- Added targeted test selection from changed files and failure output for Python, Node, Go, Rust, and Maven Java.
- Added `classify_test_failure` with syntax/import/assertion/typecheck/lint/build/timeout/dependency categories.
- Added `summarize_ci_log` for CI job/step/failure extraction.
- Added `detect_flaky_tests` for flaky/rerun/intermittent signals and inconsistent rerun results.
- Added project-config and CLI controls for test-plan size, output compaction, failure context lines, and flaky retry count.
- Updated agent prompt to prefer targeted verification before broad suites.
- Added regression tests in `tests/test_test_ci_layer_v34.py`.

### 3.2.0 - Patch/edit layer hardening

- Added a stronger patch/edit layer for Codex-like edit reliability.
- Added `plan_patch` and `verify_patch` tools to the filesystem plugin and action schema.
- Added machine-readable patch plan summaries with touched files, operation kind, hunk counts, additions/deletions, and risk warnings.
- Added post-apply verification to `apply_patch`; touched files must match the planned post-patch state.
- Added optional Python syntax verification for patched `.py` files.
- Added conservative fuzzy hunk matching controls through tool args/config/CLI.
- Hardened patch path safety so sensitive files such as `.env`, private keys, and credential files cannot be patched through the patch engine.
- Added patch-layer regression tests.

### 3.1.0 - Sandbox layer hardening

- Added a hardened sandbox layer in `src/minicodex_agent/sandbox.py`.
- Added Podman support alongside Docker.
- Container sandbox modes now use a disposable filtered workspace copy by default instead of directly mutating the project root.
- Excluded `.env`, private-key/credential paths, `.minicodex`, caches, binary artifacts, and oversized files from sandbox workspace copies.
- Added configurable network policy, CPU, memory, PID, image, workspace mode, keep-workspace, and max-file-size controls.
- Added CLI/project-config support for the new sandbox controls.
- Added sandbox configuration reporting in command observations and run metadata.
- Added regression tests in `tests/test_sandbox_layer_v32.py`.

### 3.0.0 - Structured tool results

- Added structured `TOOL_RESULT_JSON` observations for the agent loop.
- Added standard tool-result fields: `ok`, `status`, `summary`, `content`, `data`, `files_read`, `files_changed`, `commands_run`, `warnings`, `errors`, and `truncated`.
- Kept low-level tool handlers and `dispatch_tool` backwards-compatible with plain-text returns.
- Added `--no-structured-tool-results` and `--tool-result-content-chars` runtime controls.
- Added targeted navigation/search tools: `list_dir`, `glob_file_search`, `read_file_range`, and `rg_search`.
- Exposed new tools in action schemas, runtime registry, and built-in plugin metadata.
- Added regression tests in `tests/test_structured_tools_v31.py`.

### 2.9.0 - Bounded context layer

- Added a bounded context pack in each model prompt.
- Added automatic repo instruction loading for `AGENTS.md`, `.minicodex/instructions.md`, `.minicodex/AGENTS.md`, `docs/testing.md`, and `CONTRIBUTING.md`.
- Added repo-local skill discovery from `.minicodex/skills/*/SKILL.md` with goal-based ranking.
- Added ranked relevant-file hints using path, symbol, key-file, and content signals while still requiring file reads before edits.
- Added command/test/diff observation compaction that preserves failure lines and trims noisy output.
- Added context config and CLI controls: `--no-context`, `--context-max-chars`, `--context-instruction-max-chars`, `--context-relevant-files`, and `--context-observation-chars-each`.
- Added regression tests in `tests/test_context_layer_v30.py`.

### 2.8.0 - Local provider support

- Added `openai_compatible`, `ollama`, `lmstudio`, and `llama_cpp` providers for local/self-hosted OpenAI-compatible Chat Completions endpoints.
- Added provider-level base URL, API-key-env, reasoning-effort, and streaming controls.
- Kept the official `openai` provider on the Responses API with structured JSON-schema output and safer fallback behavior.
- Added project-config support for `preferred_model`, `model_base_url`, `model_api_key_env`, `model_reasoning_effort`, and `model_stream`.
- Added provider-specific default models when local providers are selected without an explicit `--model`.
- Added regression tests for local provider routing, Chat Completions payloads, config propagation, and fallback behavior.

### 2.7.0 - CLI language selection

- Added `--lang en|tr` for user-visible CLI language control.
- Added `--non-interactive` and `--default-answer` so `ask_user` and approval paths do not block CI unexpectedly.
- Expanded package metadata with author/email, SPDX-style license, classifiers, keywords, and project URLs.
- Kept dev dependencies aligned with release/check commands: pytest, pytest-cov, ruff, mypy, build, twine, and type stubs.
- Added Dependabot, release workflow, and gitleaks-based security workflow.
- Replaced the hand-written prompt tool list with an auto-generated `ACTION_SPECS` reference.
- Added `run_external_secret_scan` for gitleaks/trufflehog integration when installed.
- Improved snapshots with `.minicodex/snapshot_ignore`, file hash/mode/mtime metadata, and pre-restore safety snapshots.
- Improved local code search ranking and added `build_dependency_graph`.

### 2.6.0 - Deterministic CLI exit codes

- Added deterministic CLI exit-code strategy for CI/CD use.
- `MiniCodexAgent.run()` now returns a structured `RunResult`.
- CLI maps user/config, model/action, test, policy, and tool failures to stable process exit codes.
- Added regression tests for success, model/action failure, failed tests, policy blocks, tool failures, max-step exhaustion, and CLI propagation.

### 2.5.0 - Runtime config enforcement

- Applied project config fields consistently at runtime instead of leaving them as documentation-only settings.
- Added runtime config fields for `scan_secrets_before_pr`, `max_agent_batch_size`, `enabled_plugins`, and `policy_file`.
- Wired `enabled_plugins` through the `ToolSpec` dispatch gate while preserving `--no-project-config` behavior.
- Added custom `policy_file` support for policy read/update/check and command/write/patch enforcement.
- Enforced `scan_secrets_before_pr` before PR draft/API workflows, blocking high/critical findings by default.
- Applied `max_agent_batch_size` to legacy task batches and bounded multi-agent role execution.
- Added regression tests for all newly wired runtime config fields.

### 2.4.0 - Bounded multi-agent execution

- Added real bounded local multi-agent execution via `run_multi_agent_work`.
- Added per-role worker state, model client, tool allowlist, step budget, and model-call budget.
- Added read-only parallel execution mode with automatic downgrade to sequential when write-capable roles are selected.
- Added persisted `.minicodex/multi_agent_runs/*.json` summaries and `list_multi_agent_runs`.
- Kept `plan_multi_agent_work` for planning and `run_task_batch` as legacy task-batch bookkeeping.

### 2.3.0 - GitHub REST integration

- Added real GitHub REST API integration tools: `create_github_pr` and `create_github_issue`.
- Kept safe command-draft helpers: `prepare_github_pr` and `prepare_github_issue`.
- Added `--allow-github-api-writes` and `allow_github_api_writes` project config.
- Real GitHub writes now require a GitHub token and manual confirmation even in auto-approval mode.
- Added dry-run API request previews and GitHub integration tests.

### 2.2.0 - Developer-preview metadata wording

#### Changed
- Reworded README and package metadata so MiniCodex is presented as a developer-preview / experimental local coding-agent framework, not a drop-in Codex replacement.
- Updated the project description to use “safety guardrails” instead of stronger product-safety language.
- Clarified that the intended use is controlled local experiments, education, and supervised developer workflows.

### 2.1.0 - README test-count cleanup

#### Fixed
- Removed stale fixed test-count claims from README.
- Replaced count-based marketing language with a stable description of the pytest suite, coverage gate, CLI integration tests, security regressions, and smoke workflows.
- Clarified that users should run the current test/coverage commands to verify the exact suite size in their checkout.

### 2.0.0 - Professional quality and CI layer

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

### 1.9.0 - Default policy cleanup

- Fixed the default project policy contradiction around `.env.example`.
- Added `allow_env_examples=true` so documented env example/template files can be written while real `.env` files remain blocked.
- Kept `.env`, `.env.*`, `.env.local`, and `.env.*.local` blocked by default, with a narrow exception for `.env.example`, `.env.sample`, and `.env.template` style files.
- Updated setup wizard policy generation so creating `.env.example` no longer conflicts with the policy it creates.
- Added regression tests for `.env.example` allowance and real env-file blocking.

### 1.8.0 - Transactional patch engine

- Reworked `apply_patch` into a transactional patch engine.
- Added preflight validation before filesystem mutation.
- Added support for text file creation, modification, deletion, rename/move, and chmod-style mode changes from git diffs.
- Added conservative fuzzy hunk positioning support in the patch engine.
- Improved CRLF preservation for added lines.
- Added best-effort rollback if a multi-file patch fails mid-transaction.
- Switched patch backups to collision-resistant UUID suffixes.
- Binary patch payloads are detected and explicitly rejected instead of partially applying.

### 1.7.0 - Strict action validation

- Added strict action-specific model output validation.
- Rejected unsupported top-level keys and unsupported action arguments.
- Added argument type validation for strings, integers, booleans, arrays, objects, enums, and severity/status fields.
- Added generated JSON Schema for MiniCodex model actions.
- OpenAI provider now requests structured JSON-schema output when supported.
- Added repair retry loop for invalid JSON/action schema responses.
- Added provider timeout, max-output-token, retry/backoff, model call budget, and optional estimated cost budget controls.
- Added CLI flags for model I/O limits and structured output.
- Added regression tests for strict schema validation, structured output call arguments, model budget, and repair behavior.

### 1.6.0 - Runtime action dispatcher refactor

- Refactored runtime action execution from the large `agent.py` if/elif dispatcher into a central `ToolSpec` registry.
- Added `tool_registry.py` with `ToolSpec`, registry loading, runtime dispatch, and generated runtime tool reference.
- Added modular built-in tool handler modules under `src/minicodex_agent/tools/`: filesystem, shell, git, security, project, memory, github, Python diagnostics/refactor, diagnostics, and control.
- Kept plugin enforcement in the registry dispatch path so disabled tools are blocked before handlers run.
- Added `ToolContext` to pass config, state, logger, approval, print, and auto-snapshot dependencies to handlers without importing the agent class.
- Reduced `agent.py` from roughly 1024 lines to roughly 344 lines.
- Added registry coverage tests proving every `ACTION_SPECS` action has an executable `ToolSpec` and schema reference.

### 1.5.0 - Snapshot policy enforcement

- Implemented runtime enforcement for `auto_snapshot_before_edit`.
- Added a one-per-run automatic snapshot gate before the first real `write_file`, `replace_in_file`, `apply_patch`, or non-preview `rename_python_symbol` edit.
- Added `--no-auto-snapshot-before-edit` CLI override and project-config application for the snapshot setting.
- Snapshot failures now require manual confirmation before continuing, even under `approval=auto`.
- Skipped automatic snapshots during dry-run/preview-only operations.
- Added UUID suffixes to snapshot IDs to avoid same-second collisions.
- Added regression tests for automatic snapshot creation, dry-run skip, config disable, and snapshot-failure blocking.

### 1.4.0 - Run logger redaction

- Added default redaction for RunLogger metadata, events, plans, and final JSON outputs.
- Added recursive log sanitization for model arguments, observations, command output, diffs, and file-content-like strings.
- Added per-value log truncation to avoid storing large command outputs or diffs in `.minicodex/runs`.
- Added `--no-log` and `log_enabled` config support to disable run logging completely.
- Added `log_redaction=true` and `max_log_value_chars` project config defaults.
- Added regression tests proving API keys are not written into run logs and disabled logging creates no files.

### 1.3.0 - Secret scanner false-positive reduction

- Reduced secret-scanner false positives by limiting high-entropy checks to assignment/value contexts.
- Added secret finding severity levels: low, medium, high, and critical.
- Added PR/release blocking semantics: only high and critical findings block by default.
- Suppressed common placeholder values in `.env.example` and documentation-style examples.
- Skipped noisy contexts such as TOML section headers, imports, function/class definitions, and normal Python references.
- Added `minimum_severity` filtering to the `scan_secrets` action.
- Updated project health reports to include severity counts and explicit blocking status.
- Added regression tests for placeholders, normal code contexts, assignment-only entropy checks, and severity filtering.

### 1.2.0 - Shell-free command execution

- Replaced shell-based command execution with argv-based `subprocess.run(..., shell=False)`.
- Added shell-control syntax rejection for pipes, redirection, chaining, newlines, and command substitution.
- Made `strict` the default safety profile.
- Added explicit network/install command permission via `allow_network_commands` / `--allow-network-commands`.
- Prevented high-risk and network/install commands from silently running under `approval=auto`.
- Added `sandbox_mode` / `--sandbox-mode restricted|docker`; Docker mode is best-effort and disables container network.
- Added command-sandbox regression tests.

### 1.1.0 - Plugin allowlist enforcement

- Enforced `enabled_plugins` at runtime before every model action.
- Added `check_tool_access` / `is_tool_enabled` plugin access decisions.
- Added execution and diagnostics built-in plugin coverage so every action is mapped or explicitly control-flow.
- Merged enabled plugin `policies` into effective project policy for writes, patches, and commands.
- Added regression tests for tool blocking and plugin policy enforcement.

### 1.0.0 - First-run setup wizard

- Added first-run setup wizard.
- Added demo project generator.
- Added project health report helper.
- Added release checklist and release notes helper.
- Added CLI flags: `--setup`, `--setup-overwrite`, `--create-demo`, `--create-demo-overwrite`.
- Updated package metadata and docs for the first stable release.
- Kept policy-aware file and command operations from v0.9.
- Kept snapshots, rollback checks, task memory, task queue, provider registry, plugin manifest validation, secret scanning, and PR preparation.

### 0.9.0 - Project policy enforcement

- Added project policy enforcement.
- Added plugin manifest validation and enabled-tool listing.
- Added bounded multi-agent task planning and task batch records.

### 0.8.0 - Project config and provider registry

- Added project config, provider registry, change review, terminal sessions, and plugin manifests.

### 0.7.0 - Interactive mode and rollback checks

- Added interactive mode, secret scanning, rollback policy checks, and task queue.

### 0.6.0 - Snapshots and task memory

- Added snapshots, task memory, commit message generation, task decomposition, and code maps.

## Historical Engineering Reports

### MiniCodex Agent v2.7 Güvenlik ve Tutarlılık Düzeltme Raporu

_Source: `FIX_REPORT.md`_

Bu sürümde daha önce tespit edilen güvenlik, dry-run, secret redaction, snapshot, test ve sürüm tutarlılığı problemleri kapatıldı.

#### 1. Hassas dosya koruması

- `.env`, `.env.*`, private key dosyaları, credential/secret/token dosyaları ve `.ssh`, `.aws`, `.gnupg` gibi hassas klasörler varsayılan olarak ajan okumasına kapatıldı.
- `list_files`, `read_file`, `read_many_files`, `search_text`, `index_project`, `snapshot` ve dosya yazma araçları aynı hassas yol politikasını kullanacak şekilde merkezileştirildi.
- `.env.example` gibi örnek dosyalar bilinçli olarak izinli bırakıldı.

#### 2. Snapshot ve index güvenliği

- Snapshot sistemi artık hassas dosyaları kopyalamıyor.
- Snapshot manifest dosyası, atlanan hassas dosyaları sebebiyle birlikte raporluyor.
- Project index kaydı dry-run modunda `.minicodex/index.json` yazmıyor.

#### 3. Secret redaction düzeltmesi

- `redact_secret` çok satırlı çıktı ve loglarda satır satır çalışacak şekilde düzeltildi.
- Ajan observation çıktıları, terminal/log/memory tarafına yazılmadan önce redakte ediliyor.
- Secret scanner, normal ajan okumasına kapalı olan `.env` gibi dosyaları güvenli biçimde taramaya devam ediyor; değerleri maskeleyerek raporluyor.

#### 4. Global dry-run tutarlılığı

Dry-run modunda kalıcı dosya yazımı engellendi veya ilgili araçlara dry-run desteği eklendi:

- setup wizard
- demo project generator
- project config/policy init/update
- project index
- snapshot creation
- task memory
- task queue
- release notes
- terminal session logs
- multi-agent run logs
- change approval logs
- agent run logger

#### 5. Model çağrı bütçesi

- Başarısız provider/API denemeleri artık model call budget değerinden düşülüyor.
- OpenAI fallback davranışı, yalnızca uyumsuz parametreleri kaldıracak şekilde düzeltildi; timeout ve token limitleri mümkün olduğunca korunuyor.

#### 6. Test güncellemeleri

- Yeni güvenlik regresyon testleri eklendi: `tests/test_security_hardening_v28.py`.
- Eski test beklentileri, yeni güvenli dry-run davranışıyla uyumlu hale getirildi.
- `python3 -m compileall -q src tests` başarılıdır.
- Test dosyaları küçük batch'ler halinde çalıştırıldığında başarıyla geçti. Tek parça `pytest -q` bu çalışma ortamında timeout verdi; hata çıktısı üretmedi, fakat bazı testlerin subprocess/plugin davranışı uzun çalışmaya sebep oluyor.

#### 7. Paket temizliği

- Dağıtım zip'inden `.minicodex`, `.pytest_cache`, `__pycache__` ve `*.egg-info` gibi generated/local dosyalar çıkarılmalıdır.

### MiniCodex Agent v2.8 Model Layer Fix Report

_Source: `MODEL_LAYER_FIX_REPORT.md`_

This update addresses the first Codex-performance gap: the model layer was limited to the official OpenAI provider plus stub/echo modes.

#### Implemented

- Added provider registry entries for `openai_compatible`, `ollama`, `lmstudio`, and `llama_cpp`.
- Kept `openai` on the official Responses API path.
- Added OpenAI-compatible Chat Completions routing for local/self-hosted model servers.
- Added provider-specific default base URLs:
  - Ollama: `http://localhost:11434/v1`
  - LM Studio: `http://localhost:1234/v1`
  - llama.cpp server: `http://localhost:8000/v1`
- Added runtime and CLI fields:
  - `--model-base-url`
  - `--model-api-key-env`
  - `--model-reasoning-effort`
  - `--model-stream`
- Added project config fields:
  - `preferred_model`
  - `model_base_url`
  - `model_api_key_env`
  - `model_reasoning_effort`
  - `model_stream`
- Added local-provider default model fallback when no explicit `--model` is provided.
- Added safer fallback behavior when structured output, reasoning, stream, timeout, or token-limit parameters are not supported by a provider.
- Added regression tests in `tests/test_model_providers_v29.py`.

#### Example

```bash
minicodex "Projeyi analiz et, dosya değiştirme" \
  --root . \
  --provider ollama \
  --model qwen3-coder \
  --dry-run \
  --model-call-budget 3
```

#### Remaining Codex-performance gaps

This solves the model-provider layer only. The next major gaps are context management, structured tool observations, sandbox/workspace isolation, targeted test planning, and eval/telemetry.

### MiniCodex Agent v2.9 Context Layer Fix Report

_Source: `CONTEXT_LAYER_FIX_REPORT.md`_

This update addresses the second Codex-performance gap: prompt context was too simple and did not prioritize repo-local instructions, likely relevant files, or compacted observations.

#### What changed

- Added `src/minicodex_agent/context_manager.py`.
- Added `ContextPack` with bounded character budget accounting.
- Added automatic instruction loading for:
  - `AGENTS.md`
  - `.minicodex/instructions.md`
  - `.minicodex/AGENTS.md`
  - `docs/testing.md`
  - `CONTRIBUTING.md`
- Added repo-local skill discovery from `.minicodex/skills/*/SKILL.md`.
- Added ranked relevant-file hints using path terms, symbol names, key-file names, and sampled content.
- Added large command/test output compaction that keeps failure/error lines, head, and tail.
- Added diff compaction for large patch/diff observations.
- Updated `build_prompt()` to include `context_policy`, `context_pack`, and compacted `recent_observations`.
- Added project config and CLI controls for enabling/disabling and sizing the context pack.

#### New CLI flags

```bash
--no-context
--context-max-chars 22000
--context-instruction-max-chars 6000
--context-relevant-files 12
--context-observation-chars-each 1600
```

#### Safety notes

- Relevant-file entries are hints, not full file contents. The model prompt still instructs the agent to read files before editing.
- Sensitive paths such as `.env` remain excluded from context selection.
- `.minicodex/skills/*/SKILL.md` is intentionally allowed as trusted repo-local metadata, but `.minicodex/runs` and snapshots remain excluded from normal file ranking.

#### Verification

- `python3 -m compileall -q src tests` passed.
- New regression tests: `tests/test_context_layer_v30.py` passed.
- Model-provider and security-hardening regression tests passed alongside the new context tests.
- Additional filesystem, patch, shell, project-config, setup, Git/GitHub, and integration-quality test batches passed.

#### Remaining Codex-performance gaps

This fixes the context-management layer only. The next major gaps are structured tool observations, real sandbox/workspace isolation, targeted test planning, eval/telemetry, and IDE/TUI review workflows.

### MiniCodex v3.0 Tool Layer Fix Report

_Source: `TOOL_LAYER_FIX_REPORT.md`_

This release addresses the third Codex-performance gap: weak/loosely structured tool outputs.

#### What changed

- Added `src/minicodex_agent/tool_result.py`.
- Agent observations can now be wrapped in a `TOOL_RESULT_JSON` envelope.
- Tool results expose stable fields: `ok`, `status`, `summary`, `content`, `data`, `files_read`, `files_changed`, `commands_run`, `warnings`, `errors`, and `truncated`.
- Legacy plain-string tool handlers remain backwards-compatible.
- Added `structured_tool_results` and `tool_result_content_chars` runtime/project config fields.
- Added CLI controls:
  - `--no-structured-tool-results`
  - `--tool-result-content-chars`
- Added targeted navigation/search tools:
  - `list_dir`
  - `glob_file_search`
  - `read_file_range`
  - `rg_search`
- Updated action schema, runtime registry, prompt contract, project config defaults, plugin metadata, README, and changelog.
- Added regression tests in `tests/test_structured_tools_v31.py`.

#### Why this matters

Models perform better when tool observations are predictable. Instead of parsing arbitrary text, the agent can now read a stable status and summary first, then inspect content only when necessary. Targeted tools also reduce unnecessary context usage by letting the model inspect one directory, one file range, or one regex query at a time.

#### Verification performed

- `python3 -m compileall -q src tests`
- `PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_structured_tools_v31.py`
- `PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_action_schema.py tests/test_tool_registry_v16.py tests/test_fs_tools.py tests/test_index_tools.py tests/test_quality_coverage_v20.py tests/test_security_hardening_v28.py tests/test_structured_tools_v31.py`

The full monolithic pytest run may still be slow in constrained environments because earlier integration tests include subprocess-heavy scenarios. Batch verification was used for the changed layers.

### MiniCodex v3.1 Sandbox Layer Fix Report

_Source: `SANDBOX_LAYER_FIX_REPORT.md`_

#### Problem addressed

The previous sandbox layer was too weak for Codex-like workflows. `restricted` mode was only a guarded local subprocess, and Docker mode mounted the project root directly. That meant command side effects could still modify the user's project tree, and the sandbox policy had too few controls.

#### What changed

- Added `src/minicodex_agent/sandbox.py`.
- Kept `restricted` as a compatibility mode: local `shell=False` subprocess with existing command-safety checks.
- Added `podman` as a first-class sandbox mode.
- Changed Docker/Podman modes to use `sandbox_workspace_mode=copy` by default. The project is copied into `.minicodex/sandboxes/.../workspace`; commands run inside that copy.
- The sandbox copy excludes secret-bearing files, credential directories, `.minicodex`, caches, binaries, archives, and oversized files.
- Container runs use bounded flags: network policy, CPU limit, memory limit, PID limit, and `no-new-privileges`.
- Added CLI/project-config controls for sandbox image, network, resources, workspace mode, keep-workspace, and max file size.
- Command observations now include sandbox configuration details.

#### New CLI controls

```bash
--sandbox-mode restricted|docker|podman
--sandbox-image python:3.12-slim
--sandbox-network none|default|bridge|host
--sandbox-cpus 1
--sandbox-memory 1g
--sandbox-pids-limit 256
--sandbox-workspace-mode copy|mount
--sandbox-keep-workspace
--sandbox-max-file-bytes 2000000
```

#### Security notes

- `restricted` is still not a true OS sandbox; it is a guarded local subprocess mode.
- `docker`/`podman` provide stronger isolation, but only if the container runtime itself is correctly installed and trusted.
- Network remains effectively disabled unless both `--allow-network-commands` and a non-`none` sandbox network are set.
- `copy` mode is safer than `mount` mode because command side effects stay in the disposable sandbox workspace.

#### Tests added

- `tests/test_sandbox_layer_v32.py`

These tests cover filtered workspace copying, Docker command planning, resource flags, invalid sandbox-mode blocking, and restricted-mode sandbox reporting.

### MiniCodex v3.2 Patch/Edit Layer Fix Report

_Source: `PATCH_LAYER_FIX_REPORT.md`_

#### Goal

Close Codex-performance gap #5: make patch/edit operations safer, more inspectable, and more recoverable.

#### Implemented

- Added structured patch plan dataclasses in `patch_tools.py`.
- Added machine-readable patch summaries via `build_patch_plan_summary()` and `render_patch_plan()`.
- Added `plan_patch` tool for non-writing patch previews.
- Added `verify_patch` tool for patch-state checks.
- Extended `apply_patch` with:
  - post-apply content verification,
  - optional Python syntax verification,
  - optional conservative fuzzy hunk matching,
  - richer plan JSON in outputs.
- Hardened patch path resolution so sensitive paths are rejected before reading or writing.
- Added CLI/config flags:
  - `--no-patch-verify-after-apply`
  - `--patch-verify-python-syntax`
  - `--patch-fuzzy-apply`
- Updated prompts so the model prefers `plan_patch` before broad edits and uses verification/diagnostics after patch problems.
- Updated filesystem plugin metadata, action schema, multi-agent implementer tools, and exit-code classification.
- Added regression tests in `tests/test_patch_layer_v33.py`.

#### Verification

- `python3 -m compileall -q src tests` passes.
- Patch-layer and affected-regression test groups pass under `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.

#### Notes

This layer still intentionally avoids arbitrary AST rewriting for every language. The next step toward Codex-level performance is a TestPlanner/failure-repair loop that chooses targeted tests and iterates patches with feedback.

### MiniCodex v3.3 Test/CI Layer Fix Report

_Source: `TEST_CI_LAYER_FIX_REPORT.md`_

#### Goal

Close Codex-performance gap #6: strengthen the verification loop so the agent can choose the smallest useful tests first, classify failures, summarize CI logs, and recognize flaky-test signals before editing broadly.

#### Added

- `src/minicodex_agent/test_ci.py`
  - `plan_tests(...)`
  - `classify_failure_output(...)`
  - `summarize_ci_log(...)`
  - `detect_flaky_tests(...)`
  - failed-test extraction for pytest/unittest/Jest-style logs
  - targeted command selection for Python, Node, Go, Rust, and Maven Java
- `src/minicodex_agent/tools/testing.py`
  - `plan_tests`
  - `run_targeted_tests`
  - `classify_test_failure`
  - `summarize_ci_log`
  - `detect_flaky_tests`

#### Behavior

The agent now prefers this flow for code changes:

1. Plan targeted tests from changed files and/or failure output.
2. Run exact failing test nodes/files before broad suites.
3. Classify failures into categories such as syntax, import, assertion, timeout, lint, build, dependency, or unknown.
4. Read exact source locations before editing.
5. Detect flaky/intermittent signals and recommend reruns before broad refactors.
6. Escalate to fallback/full test, lint, or build only after targeted verification.

#### New configuration

```json
{
  "test_plan_max_commands": 5,
  "test_output_max_chars": 12000,
  "test_failure_context_lines": 4,
  "flaky_retry_count": 1
}
```

#### New CLI options

```bash
--test-plan-max-commands 5
--test-output-max-chars 12000
--test-failure-context-lines 4
--flaky-retry-count 1
```

#### Verification

- `python3 -m compileall -q src tests` passed.
- New regression tests added in `tests/test_test_ci_layer_v34.py`.
- Relevant test groups were run with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and passed.

### MiniCodex v3.4 Skill Layer Fix Report

_Source: `SKILL_LAYER_FIX_REPORT.md`_

This release addresses the seventh Codex-performance gap: repo-local instructions and skills.

#### Added

- `src/minicodex_agent/skill_manager.py` for safe skill discovery, validation, ranking, and reading.
- `.minicodex/skills/<name>/SKILL.md` progressive-disclosure support.
- New tools: `list_skills`, `read_skill`, `validate_skills`, `init_skill`.
- New built-in plugin: `skills`.
- Config/CLI controls for skill discovery and read budgets.
- Setup wizard generation of `AGENTS.md` and an example targeted-testing skill.

#### Safety model

- Skills are metadata-first in the prompt; the full markdown is only loaded via explicit `read_skill`.
- Skill paths must match `.minicodex/skills/<safe-name>/SKILL.md`.
- Arbitrary skill code is not executed. Skill files are documentation/workflow instructions only.

#### Verification

- Added `tests/test_skill_layer_v35.py`.
- Compile and targeted regression tests passed in this environment.

### Multi-Agent Layer Fix Report — v3.5.0

_Source: `MULTI_AGENT_LAYER_FIX_REPORT.md`_

This release resolves the eighth Codex-performance gap: the previous multi-agent system had bounded role workers, but it did not preserve a Codex-like parent/child thread model, shared mailbox handoffs, saved transcript reading, or deterministic result merging.

#### Added

- `AgentThread`: role-scoped child-agent transcript with `thread_id`, role, objective, allowed tools, status, actions, messages, and result summary.
- `AgentMailbox`: shared parent/subagent message bus for assignment and result handoffs.
- `AgentResultMerger`: deterministic parent-facing consolidation of role summaries, unfinished roles, write-capable roles, mailbox count, and recommended next steps.
- `plan_subagent_threads`: creates a Codex-style thread plan without executing workers.
- `run_subagent_threads`: runs the enhanced coordinator with subagent terminology.
- `read_multi_agent_run`: reads saved multi-agent transcripts by `run_id`, with observations omitted by default.

#### Enhanced

- `run_multi_agent_work` now returns `thread_model`, `threads`, `mailbox`, and `merged_result` in addition to legacy `roles/results/summary`.
- Role workers now receive their own `thread_id`, inbox messages, role policy, step budget, model-call budget, and allowed tool list in the worker prompt.
- Each completed role posts a `result` mailbox message to `recipient=all`, allowing sequential workers to see prior role summaries.
- Parallel mode still downgrades to sequential when write-capable roles are selected unless `multi_agent_allow_parallel_writes=true`.

#### Config / CLI

New config and CLI controls:

- `multi_agent_thread_max_messages`
- `multi_agent_result_max_chars`
- `multi_agent_allow_parallel_writes`

#### Tests

Added `tests/test_multi_agent_layer_v36.py` covering:

- Subagent thread plan payload and communication contract.
- Dry-run thread/mailbox/merge payloads.
- `run_subagent_threads` alias behavior.
- Saved transcript reading without full observations.
- Result merger status and write-role detection.

### Long-Horizon Layer Fix Report — v3.6.0

_Source: `LONG_HORIZON_LAYER_FIX_REPORT.md`_

This release addresses Codex-performance gap #9: long-running task continuity.

#### What changed

- Added `src/minicodex_agent/long_horizon.py` for durable JSON state.
- Added `src/minicodex_agent/tools/long_horizon.py` tool handlers.
- Added strict action-schema entries for:
  - `create_long_task`
  - `list_long_tasks`
  - `read_long_task`
  - `resume_long_task`
  - `update_acceptance_criteria`
  - `create_checkpoint`
- Added a built-in `long-horizon` plugin.
- Added CLI/config controls:
  - `--long-horizon`
  - `--long-horizon-run-id`
  - `--long-horizon-auto-checkpoint-interval`
  - `--long-horizon-resume-max-chars`
  - `--checkpoint-max-observation-chars`
- Added prompt guidance for acceptance criteria, milestones, checkpoints, and resume packs.
- Added optional automatic checkpointing from the main agent loop when a run id is configured.

#### State format

Long-horizon task state is stored at:

```text
.minicodex/long_horizon/runs/<run_id>.json
```

Each record contains:

- goal
- status
- acceptance criteria
- milestones
- checkpoints
- timestamps

#### Safety behavior

- `run_id` values are path-safe and cannot escape the long-horizon directory.
- Dry-run mode simulates task creation/updates without writing files.
- Checkpoint observation summaries are compacted before persistence.
- No secret-specific bypass is introduced; existing RunLogger/secret redaction remains active in agent logs.

#### Verification

Added regression tests:

```text
tests/test_long_horizon_layer_v37.py
```

Validated:

- action schema registration
- tool registry registration
- project config defaults
- plugin availability
- safe run-id validation
- dry-run non-write behavior
- checkpoint creation
- resume pack generation
- acceptance-criteria updates
- compact observation summaries

### MiniCodex v3.7 Developer Experience Layer Fix Report

_Source: `DEV_EXPERIENCE_LAYER_FIX_REPORT.md`_

This update addresses Codex-performance item 10: IDE / developer experience.

#### Added

- `src/minicodex_agent/dev_experience.py`
  - terminal developer panel rendering
  - JSON review-bundle creation/list/read/decision recording
  - saved-run summary rendering
  - IDE bridge descriptor export
- `src/minicodex_agent/tools/ux.py`
  - runtime ToolSpec handlers for developer UX tools

#### New tools

- `render_tui_panel`
- `create_review_bundle`
- `list_review_bundles`
- `read_review_bundle`
- `record_review_decision`
- `run_summary`
- `export_ide_bridge`

#### New CLI switches

- `--dev-panel`
- `--review-after-run`
- `--review-bundle-max-diff-chars`
- `--export-ide-bridge`

#### Design notes

- The terminal panel is dependency-free and does not require `rich` or `textual`.
- Review bundles are JSON files under `.minicodex/review_bundles/*.json`.
- Review decisions are recorded inside the bundle using `approved`, `rejected`, or `needs_changes`.
- The IDE bridge is intentionally small and stable: `.minicodex/ide/bridge.json` lists useful commands and paths for future editor plugins.
- Dry-run mode does not write review bundles or IDE bridge files.
- Git output is redacted before being included in review artifacts.

#### Verification

- Added regression tests in `tests/test_dev_experience_layer_v38.py`.
- Updated action schema, tool registry, plugin metadata, project config defaults, CLI, README, CHANGELOG, and prompt guidance.

### Language / Framework Layer Fix Report — v3.8.0

_Source: `LANGUAGE_LAYER_FIX_REPORT.md`_

#### Scope

This update addresses Codex-performance gap 11: language and framework analysis was too Python-centric.

#### Added

- `src/minicodex_agent/language_adapters.py` with deterministic adapters for Python, TypeScript/JavaScript, Java/Kotlin, Go, and Rust.
- `src/minicodex_agent/tools/languages.py` with tool handlers for language-aware inspection and command suggestions.
- New tool actions:
  - `detect_language_stack`
  - `inspect_frameworks`
  - `suggest_verification_commands`
  - `language_adapter_report`
- Framework detection for common Python, frontend, Java, Go, and Rust stacks.
- ProjectProfile fields for languages, frameworks, typecheck commands, and format commands.
- `include_typecheck` support in `plan_tests` and `run_targeted_tests`.

#### Safety

- The language analyzer uses existing workspace skip rules and sensitive path detection.
- It does not execute package managers or external commands.
- It reads bounded text samples only and treats output as hints, not proof.

#### Verification

- `python -m compileall -q src tests` passed.
- `tests/test_language_layer_v39.py` passed.
- Registry, schema, project inspector, context, Test/CI, developer UX, sandbox, patch, security, skill, long-horizon, and multi-agent regression groups passed in batches.
- Monolithic `pytest -q` still times out in this environment, consistent with previous releases; batch execution completed the relevant coverage.

### Eval Layer Fix Report - v3.9.0

_Source: `EVAL_LAYER_FIX_REPORT.md`_

This release closes Codex-performance gap #12: the lack of an evaluation system.

#### Added

- `src/minicodex_agent/eval_runner.py` for deterministic benchmark tasks, disposable workspaces, verification commands, scoring, aggregate reports, and run comparison.
- `src/minicodex_agent/tools/evals.py` tool handlers.
- Built-in `evals` plugin.
- Action schema entries for `init_eval_suite`, `list_eval_tasks`, `read_eval_task`, `run_eval_task`, `run_eval_suite`, `list_eval_runs`, `read_eval_run`, and `compare_eval_runs`.
- CLI shortcuts for initializing, listing, and running evals.
- Project-config defaults for eval step/call/time/report budgets.
- Regression tests in `tests/test_eval_layer_v40.py`.

#### Safety/UX behavior

- Eval tasks run in disposable workspaces under `.minicodex/evals/runs`.
- Dry-run mode does not create task files or workspaces.
- Verification commands are parsed with the existing command-safety layer and run with `shell=False`.
- Sensitive fixture paths such as `.env`, private keys, and credential files are rejected.
- Running real-provider evals requires manual confirmation unless using `stub` or `echo`.

#### What this enables

- Compare providers and prompts with repeatable task success metrics.
- Track regressions after model, context, tool, sandbox, patch, or prompt changes.
- Record token/call/cost usage alongside functional success.

### GitHub Layer Fix Report

_Source: `GITHUB_LAYER_FIX_REPORT.md`_

Version: 4.0.0

This layer strengthens MiniCodex GitHub integration while preserving safe defaults.

#### Added

- `github_integration.py` for workflow inspection, workflow template creation, PR slash-command parsing, commit/push planning, GitHub CI log summarization, and CI fetch previews.
- New tools: `detect_github_workflows`, `init_github_action`, `parse_pr_comment_command`, `prepare_commit_push_plan`, `summarize_github_ci_log`, `github_ci_fetch_preview`.
- CLI shortcuts: `--detect-github-workflows`, `--init-github-action`, `--github-workflow-name`, `--github-workflow-overwrite`, `--parse-pr-comment`.
- GitHub Actions workflow template with `workflow_dispatch` and PR `issue_comment` support.
- Safe-by-default PR comment parsing that adds `--dry-run` for slash-command triggered runs.

#### Safety

- Generated workflow runs strict safety and dry-run by default for comment-triggered execution.
- Commit/push helper is plan-only and does not execute `git add`, `git commit`, or `git push`.
- CI fetch helper is preview-only; users can paste logs into `summarize_github_ci_log`.
- Existing real GitHub API writes still require explicit enablement and manual approval.

#### Validation

- `python3 -m compileall -q src tests` passed.
- New regression tests in `tests/test_github_layer_v41.py` passed.
- GitHub/action/plugin/schema/test-CI/eval regression batch passed.

### MiniCodex v4.1.0 Observability Layer Fix Report

_Source: `OBSERVABILITY_LAYER_FIX_REPORT.md`_

This release adds a local observability layer for Codex-style agent operation.

#### Added

- `src/minicodex_agent/telemetry.py` for trace/span telemetry, token/cost ledgers, risk events, and prompt versioning.
- `src/minicodex_agent/tools/telemetry.py` for model-accessible observability tools.
- New built-in plugin: `observability`.
- New CLI shortcuts for telemetry summary, trace reading, and bundle export.
- Agent-loop instrumentation for model calls, tool calls, failures, blocked operations, and final run result.

#### Safety

Telemetry is local-only and redacted through the existing secret scanner. Dry-run mode does not write telemetry files.

#### New tools

- `list_telemetry_runs`
- `read_telemetry_run`
- `telemetry_summary`
- `compare_telemetry_runs`
- `export_telemetry_bundle`

### MiniCodex v4.2.0 Prompt Layer Fix Report

_Source: `PROMPT_LAYER_FIX_REPORT.md`_

#### Problem addressed

The previous prompt layer was one large static system prompt. That made it hard to tune MiniCodex for different task types, local models, long-horizon work, GitHub workflows, security reviews, and eval comparisons.

#### What changed

- Added `src/minicodex_agent/prompt_engine.py`.
- Split the system prompt into versioned sections.
- Added task/provider-aware prompt profile inference.
- Added prompt profiles for bugfix, review, refactor, test/CI, security, documentation, GitHub, eval, long-horizon, local-model, and frontend work.
- Added prompt preview and prompt contract validation tools.
- Added CLI and project-config knobs for prompt profile, prompt size, and action-reference inclusion.
- Updated `ModelClient` to accept a per-run system prompt.
- Updated telemetry metadata to include prompt profile/sections.

#### Verification

- `python3 -m compileall -q src tests` passed.
- `tests/test_prompt_layer_v43.py` passed.
- Action schema, tool registry, plugin registry, project settings, observability, and integration-quality regression tests passed in batch.

### Security Layer Fix Report (v4.3.0)

_Source: `SECURITY_LAYER_FIX_REPORT.md`_

This update closes the Codex-performance roadmap item 16: product-level security hardening.

#### Added

- `src/minicodex_agent/security_audit.py`
- New tools:
  - `run_sast_scan`
  - `run_dependency_audit`
  - `scan_repo_instructions`
  - `validate_plugin_permissions`
  - `workspace_trust_report`
  - `security_audit_report`
- New CLI flags:
  - `--security-audit`
  - `--scan-repo-instructions`
  - `--untrusted-workspace`
  - `--require-trusted-workspace-for-writes`
  - `--security-audit-max-files`
  - `--security-audit-report-max-chars`
  - `--external-security-timeout-seconds`

#### Security behavior

- Unknown repositories can be run in `--untrusted-workspace` mode.
- High-impact tools are blocked when `--untrusted-workspace` is combined with `--approval auto`.
- Repo-local instructions are scanned for prompt-injection and secret-exfiltration instructions.
- Local plugin manifests may declare permissions and can be checked against their tool exposure.
- Dependency audits are planned without network execution unless policy and user settings allow it.
- SAST uses Semgrep when available and otherwise falls back to a dependency-free built-in scanner.

#### Validation

- `python3 -m compileall -q src tests` passed.
- New security product layer tests passed.
- Security, action schema, tool registry, plugin registry, project settings, secret scanner, and safety regression tests passed.

### MiniCodex Agent v4.4 Final Completion Report

_Source: `FINAL_COMPLETION_REPORT.md`_

This release closes the remaining Codex-performance roadmap gaps after the model, context, tool, sandbox, patch, test/CI, skill, multi-agent, long-horizon, developer UX, language/framework, eval, GitHub, observability, prompt, and product-security layers.

#### Final additions

- Final readiness checks for version alignment, syntax, runtime registry/schema/plugin consistency, documentation presence, CLI smoke, and generated artifact cleanliness.
- Deterministic file-level test matrix planning and `scripts/run_test_matrix.py` to avoid monolithic pytest timeouts.
- Release package manifest reporting for zip/package hygiene.
- New built-in `quality-gates` plugin.
- New CLI shortcuts: `--final-readiness`, `--test-matrix-plan`, and `--release-package-manifest`.

#### Recommended final verification

```bash
python -m compileall -q src tests
python scripts/run_test_matrix.py --json
python -m minicodex_agent.cli --help
python -m minicodex_agent.cli --final-readiness --root .
python -m minicodex_agent.cli --release-package-manifest --root .
```

#### Status

The project is still a developer-preview/local agent framework, not a hosted Codex replacement. However, the major engineering layers required to approach Codex-style workflows are now present: provider abstraction, context management, structured tool calls, sandboxing, patch verification, targeted test/CI, skills, subagents, long-horizon state, developer review workflows, language adapters, evals, GitHub workflow helpers, telemetry, modular prompts, product security, and final release gates.

### Security False-Positive Fix Report (v4.4.1)

_Source: `SECURITY_FALSE_POSITIVE_FIX_REPORT.md`_

This patch addresses the first remaining release-blocking issue found in the v4.4 audit.

#### Fixed

- Built-in SAST no longer flags Python rule definitions or unsafe-code examples embedded inside string literals.
- The scanner blanks Python string/comment tokens before regex matching while preserving executable tokens and line mapping.
- Test redaction fixture now carries an explicit `minicodex-security-test-fixture` marker, so `scan_secrets` can skip the intentionally fake provider-shaped value while redaction tests still exercise realistic token masking.
- Added regression tests for both ignored fixture strings and still-detected executable `eval(...)`.

#### Expected result

Running `--security-audit` against the source tree should no longer report the previous false-positive blockers from:

- `src/minicodex_agent/security_audit.py` pattern definitions
- `tests/test_security_product_layer_v44.py` string fixtures
- `tests/test_run_logger.py` fake OpenAI-shaped key

### Final Readiness Gate Fix Report

_Source: `FINAL_READINESS_GATE_FIX_REPORT.md`_

Version: 4.4.2

This release closes the second follow-up issue from the post-final audit: the
final readiness command now includes release-blocking security checks, bounded
test-matrix execution results, and build/lint/typecheck verification planning.

#### Changes

- `final_readiness_report` now includes `security_audit_gate` by default.
- `final_readiness_report` now includes `test_matrix_result_gate` by default.
- `scripts/run_test_matrix.py` supports `--max-files` for bounded readiness checks.
- `final_readiness_report` now includes `verification_tools_gate` by default.
- CLI flags were added for skipping security, skipping bounded test execution,
  adjusting test limits/timeouts, and optionally running installed verification tools.
- Readiness subprocesses set `PYTHONDONTWRITEBYTECODE=1` to avoid creating
  `__pycache__` during smoke checks.

#### New CLI examples

```bash
minicodex --final-readiness --root .
minicodex --final-readiness --root . --final-readiness-test-max-files 0
minicodex --final-readiness --root . --final-readiness-run-verification-tools
```

### JSON Report Truncation Fix Report

_Source: `JSON_REPORT_TRUNCATION_FIX_REPORT.md`_

Version: 4.4.3

#### Problem

`final_readiness_report` and related machine-readable reports previously rendered full JSON and then truncated the text. When a report exceeded `max_chars`, the returned payload could end with `...[TRUNCATED]...` and become invalid JSON.

#### Fix

- Added a bounded JSON renderer that always returns `PREFIX\n<valid-json>`.
- Large strings, lists, and dictionaries are compacted structurally instead of cutting the serialized text.
- Compacted reports include explicit metadata such as `truncated`, `original_json_chars`, `max_chars_requested`, and `omitted_count`.
- Applied the renderer to final readiness, release package manifest, and test matrix plan tool output.

#### Validation

Regression tests verify that small `max_chars` values still produce parseable JSON reports.

### Bytecode-Clean Readiness Fix Report

_Source: `BYTECODE_CLEAN_READINESS_FIX_REPORT.md`_

Version: 4.4.4

#### Fixed issue

`--final-readiness` and CLI smoke/test-matrix checks could create Python runtime artifacts (`__pycache__`, `.pyc`, `.pytest_cache`) in the source tree. Those generated artifacts could then make a clean release tree appear dirty.

#### Changes

- Added `cleanup_python_bytecode(root)` to remove bytecode and pytest cache artifacts from the quality-gate layer.
- `final_readiness_report()` now cleans Python bytecode before checks and again before returning.
- Final readiness JSON includes `bytecode_cleanup.before_checks` and `bytecode_cleanup.after_checks` metadata.
- `check_cli_smoke()` now invokes the CLI with `python -B -m ...`.
- `check_test_matrix_result()` now invokes the matrix runner with `python -B`.
- `scripts/run_test_matrix.py` now sets `PYTHONDONTWRITEBYTECODE=1` for children.
- The matrix syntax phase no longer uses `compileall`; it performs in-memory syntax compilation instead.

#### Result

Running `minicodex --final-readiness --root .` no longer leaves `__pycache__` or `.pytest_cache` artifacts in the project tree.

### Agent Workspace Isolation Fix Report

_Source: `AGENT_WORKSPACE_ISOLATION_FIX_REPORT.md`_

Version: 4.4.5

This release closes the run-wide isolation gap. Earlier versions could sandbox command execution, but write/patch tools still operated directly on the project root unless users relied on snapshots. v4.4.5 adds an optional agent-level isolated workspace mode.

#### What changed

- Added `workspace_isolation.py`.
- Added `--agent-workspace-mode direct|isolated`.
- Added `--agent-workspace-apply never|ask|auto`.
- Added `--agent-workspace-keep`, `--agent-workspace-max-file-bytes`, and `--agent-workspace-diff-max-chars`.
- In isolated mode the agent switches its active root to a filtered copy for the duration of the run.
- At finish or max-steps, MiniCodex computes changed files, writes a manifest and diff, optionally applies safe changes back to the original root, and cleans up the temporary workspace unless requested otherwise.

#### Safety behavior

- `.env`, private keys, credentials, `.minicodex`, cache folders, symlinks, and oversized files are excluded from the workspace copy.
- Sync-back refuses sensitive paths even if they somehow appear in the workspace diff.
- `never` mode exports only review artifacts and does not mutate the original root.

#### Example

```bash
minicodex "Fix the failing tests" \
  --root . \
  --agent-workspace-mode isolated \
  --agent-workspace-apply ask
```

### Test Matrix Split Fix Report

_Source: `TEST_MATRIX_SPLIT_FIX_REPORT.md`_

Version: 4.4.6

#### Problem

The suite was broad and subprocess-heavy enough that monolithic `pytest -q` could time out or remain opaque in constrained CI environments. The previous file-level matrix reduced risk but did not clearly separate unit, integration, subprocess, sandbox, and slow checks.

#### Fix

- Added `tests/conftest.py` with automatic marker assignment for `unit`, `integration`, `subprocess`, `sandbox`, and `slow`.
- Registered markers in `pyproject.toml` to avoid unknown-marker warnings.
- Upgraded `scripts/run_test_matrix.py` with `--group`, group-specific default timeouts, `--marker-expr`, `--exclude-slow`, JSONL progress streaming, and graceful handling of files where all tests are deselected.
- Updated final-readiness to run the fast marker-aware bounded group by default and expose `--final-readiness-test-group`.
- Updated `test_matrix_plan` to describe recommended CI split commands.

#### Recommended CI split

```bash
python scripts/run_test_matrix.py --group fast --json
python scripts/run_test_matrix.py --group integration --json
python scripts/run_test_matrix.py --group subprocess --json
python scripts/run_test_matrix.py --group sandbox --json
python scripts/run_test_matrix.py --group slow --json
```

For pull requests, start with `fast`. For scheduled/full validation, add integration, subprocess, sandbox, and slow groups.

#### Validation

- `python3 -m compileall -q src tests scripts`
- `pytest -q tests/test_test_matrix_split_v46.py`
- `scripts/run_test_matrix.py --group fast --max-files 3 --json`
- `minicodex --final-readiness --final-readiness-test-group fast`

### Eval Benchmark Expansion Fix Report

_Source: `EVAL_BENCHMARK_EXPANSION_FIX_REPORT.md`_

Version: 4.4.7

This update closes remaining gap #7: the eval system had a harness but too little benchmark coverage and no reproducible provider/model baseline manifest layer.

#### Added

- Expanded built-in eval tasks covering:
  - no-op smoke harness validation
  - Python arithmetic bugfix
  - Python edge-case bugfix
  - README docs synchronization
  - unsafe `shell=True` security refactor
  - TypeScript return-value bugfix
  - React accessibility improvement
  - Java null-guard bugfix
  - Go error-handling bugfix
  - Rust off-by-one bugfix
  - CI-log-driven pytest repair
  - malicious repository instruction defense

- Added provider/model baseline manifests:
  - `stub-smoke`
  - `openai-codex-core`
  - `ollama-qwen-coder-core`
  - `lmstudio-local-core`
  - `full-regression-reference`

- Added tools and CLI commands for creating, listing, rendering, and comparing baselines without triggering API calls.

#### Verification

- `python3 -m compileall -q src tests scripts` passed.
- New eval benchmark tests passed.
- Eval/action/plugin/quality regression batch passed.
- Security audit produced no release-blocking findings in this environment.

### Model Tool-Calling Layer Fix Report

_Source: `MODEL_TOOL_CALLING_FIX_REPORT.md`_

Version: 4.4.8

This update fixes the remaining local/OpenAI-compatible provider gap by adding native Chat Completions `tools/tool_calls` support while preserving the legacy JSON-text action protocol as a fallback.

#### Fixed

- Native tool call object parsing for Chat Completions responses.
- Streaming tool-call chunk collection for local providers.
- `--model-action-protocol auto|json_text|tool_calls` CLI/config support.
- `auto` protocol now prefers native tool calls for local/OpenAI-compatible providers.
- Automatic fallback from tool calls to JSON text when a local server rejects `tools`/`tool_choice`.
- `--model-stream-ui` to show streaming deltas in real time on stderr.
- Schema reliability counters: native tool calls, JSON-text actions, validation successes/failures, repair prompts, reliability ratio.
- Prompt guidance for local providers now separates native tool-call and JSON-text behavior.

#### Validation

- Added `tests/test_model_tool_calling_v48.py`.
- Relevant model/provider/prompt tests passed in batch.
- `python3 -m compileall -q src tests scripts` passed.

### MiniCodex v4.4.9 — Eval Claim Benchmark Fix Report

_Source: `EVAL_CLAIM_BENCHMARK_FIX_REPORT.md`_

This release closes the remaining evaluation gap for Codex-style performance claims.

#### What changed

- Expanded the built-in benchmark suite from easy/smoke-heavy coverage to a broader claim-oriented suite.
- Added hard/offline fixture tasks for:
  - multi-file Python bugfix
  - TypeScript/React refactor
  - Java/Maven test fix
  - security patch
  - dependency upgrade
  - CI log repair
  - large diff review
  - malicious repo/skill instruction defense
  - long-horizon task
  - multi-agent task
- Added `eval_coverage_report` to make benchmark coverage machine-readable.
- Added claim-suite baselines for:
  - `gpt-5.3-codex`
  - `gpt-5.5`
  - Ollama Qwen coder
  - LM Studio local model
- Baseline plans now include local model action protocol arguments when needed.

#### New CLI

```bash
minicodex --eval-coverage-report --root .
minicodex --eval-baseline-plan openai-codex-claim-suite --root .
minicodex --eval-baseline-plan openai-gpt-5-5-claim-suite --root .
minicodex --eval-baseline-plan ollama-qwen-coder-claim-suite --root .
minicodex --eval-baseline-plan lmstudio-local-claim-suite --root .
```

#### Claim rule

Do not claim Codex-like performance from feature coverage alone. Run the hosted reference baseline and candidate baseline, then compare reports with `compare_eval_baselines`.

### Semantic Language Layer Fix Report — v4.4.10

_Source: `SEMANTIC_LANGUAGE_LAYER_FIX_REPORT.md`_

This release addresses the remaining language-adapter gap: language/framework detection was useful but too heuristic for larger repositories.

#### Added

- `src/minicodex_agent/semantic_index.py`
- Python AST-backed symbol extraction.
- Grammar-aware TypeScript/JavaScript, Java/Kotlin, Go, and Rust symbol extraction.
- Cross-file symbol reference lookup.
- Framework route inspection for FastAPI, Flask, Django, Express, NestJS, Spring, Gin/Fiber/Echo, Axum, Actix, Rocket, and Next.js file routes.
- Parser capability reporting, including optional Tree-sitter availability.

#### New tools

- `semantic_capability_report`
- `build_semantic_index`
- `find_symbol_references`
- `inspect_routes`

#### New CLI shortcuts

```bash
minicodex --semantic-capability-report --root .
minicodex --build-semantic-index --root .
minicodex --find-symbol-references MySymbol --root .
minicodex --inspect-routes --root .
```

#### Notes

Tree-sitter remains optional to keep the package lightweight. When it is not installed, non-Python languages use deterministic grammar-aware extractors and the capability report states this explicitly.

### AST Patch Layer Fix Report

_Source: `AST_PATCH_LAYER_FIX_REPORT.md`_

Version: 4.4.11

This release closes the remaining patch/edit-system gap by adding AST-aware and formatter-aware refactor tools on top of the transactional unified-diff engine.

#### Added tools

- `ast_patch_capability_report`
- `plan_semantic_edit`
- `rename_symbol_semantic`
- `organize_imports`
- `detect_dead_code`
- `cleanup_dead_code`
- `format_and_verify`

#### Safety model

- All mutating tools are preview-first and require normal approval/snapshot gates when `preview_only=false` or formatter execution is requested.
- Sensitive paths and skipped paths are rejected through existing safety gates.
- Python semantic edits are parsed with stdlib `ast` after transformation.
- Non-Python edits use dependency-free grammar-aware token masking to avoid strings/comments; optional heavier parsers remain capability-reported rather than mandatory.

#### Remaining realistic limitation

This is not a full LSP server. For maximum TypeScript/Java precision, projects can still add external formatters/parsers such as `ts-morph`, `javalang`, `libcst`, or Tree-sitter; MiniCodex will report their availability and can use the semantic index/refactor workflow around them.

### GitHub full agent workflow layer fix report

_Source: `GITHUB_FULL_AGENT_LAYER_FIX_REPORT.md`_

Version: 4.4.12

This release closes the remaining GitHub-integration gap where MiniCodex mostly produced previews instead of supporting a Codex-style GitHub workflow.

#### Added

- GitHub App manifest generation: `generate_github_app_manifest`
- Signed webhook listener scaffold: `init_github_webhook_server`
- Real GitHub Actions CI metadata/job/log fetch path: `fetch_github_ci_log`
- Gated branch/add/commit/push execution: `execute_commit_push_workflow`
- Review comment grouping/resolution planning: `resolve_review_comments`
- Pull request review comment creation: `create_github_review_comment`
- GitHub Actions artifact upload step generation: `prepare_github_artifact_upload`
- Default generated MiniCodex workflow now uploads `.minicodex` run/review/diff artifacts with `actions/upload-artifact@v4`.

#### Safety behavior

- Offline preview tools remain available without credentials.
- Real GitHub API reads require `--allow-network-commands` or `--allow-github-api-writes` plus manual approval.
- Real GitHub writes and remote pushes require `--allow-github-api-writes` plus manual approval.
- Dry-run remains the default for PR-comment automation and commit/push execution.
- The webhook scaffold verifies `X-Hub-Signature-256` before parsing events.

#### Validation

- New tests: `tests/test_github_full_agent_layer_v57.py`
- GitHub/action/plugin/schema regression tests passed.
- Security audit produced no blocker findings.

## Source Inventory

- Active source: `README.md`
- Active source: `docs/quickstart.md`
- Active source: `docs/usage.md`
- Active source: `docs/local-llm.md`
- Active source: `docs/architecture.md`
- Active source: `docs/security.md`
- Active source: `docs/evals.md`
- Active source: `docs/github.md`
- Active source: `docs/testing.md`
- Active source: `CHANGELOG.md`
- Archived after consolidation: `FIX_REPORT.md`
- Archived after consolidation: `MODEL_LAYER_FIX_REPORT.md`
- Archived after consolidation: `CONTEXT_LAYER_FIX_REPORT.md`
- Archived after consolidation: `TOOL_LAYER_FIX_REPORT.md`
- Archived after consolidation: `SANDBOX_LAYER_FIX_REPORT.md`
- Archived after consolidation: `PATCH_LAYER_FIX_REPORT.md`
- Archived after consolidation: `TEST_CI_LAYER_FIX_REPORT.md`
- Archived after consolidation: `SKILL_LAYER_FIX_REPORT.md`
- Archived after consolidation: `MULTI_AGENT_LAYER_FIX_REPORT.md`
- Archived after consolidation: `LONG_HORIZON_LAYER_FIX_REPORT.md`
- Archived after consolidation: `DEV_EXPERIENCE_LAYER_FIX_REPORT.md`
- Archived after consolidation: `LANGUAGE_LAYER_FIX_REPORT.md`
- Archived after consolidation: `EVAL_LAYER_FIX_REPORT.md`
- Archived after consolidation: `GITHUB_LAYER_FIX_REPORT.md`
- Archived after consolidation: `OBSERVABILITY_LAYER_FIX_REPORT.md`
- Archived after consolidation: `PROMPT_LAYER_FIX_REPORT.md`
- Archived after consolidation: `SECURITY_LAYER_FIX_REPORT.md`
- Archived after consolidation: `FINAL_COMPLETION_REPORT.md`
- Archived after consolidation: `SECURITY_FALSE_POSITIVE_FIX_REPORT.md`
- Archived after consolidation: `FINAL_READINESS_GATE_FIX_REPORT.md`
- Archived after consolidation: `JSON_REPORT_TRUNCATION_FIX_REPORT.md`
- Archived after consolidation: `BYTECODE_CLEAN_READINESS_FIX_REPORT.md`
- Archived after consolidation: `AGENT_WORKSPACE_ISOLATION_FIX_REPORT.md`
- Archived after consolidation: `TEST_MATRIX_SPLIT_FIX_REPORT.md`
- Archived after consolidation: `EVAL_BENCHMARK_EXPANSION_FIX_REPORT.md`
- Archived after consolidation: `MODEL_TOOL_CALLING_FIX_REPORT.md`
- Archived after consolidation: `EVAL_CLAIM_BENCHMARK_FIX_REPORT.md`
- Archived after consolidation: `SEMANTIC_LANGUAGE_LAYER_FIX_REPORT.md`
- Archived after consolidation: `AST_PATCH_LAYER_FIX_REPORT.md`
- Archived after consolidation: `GITHUB_FULL_AGENT_LAYER_FIX_REPORT.md`
- Excluded test fixture: `tests/fixtures/unsafe_examples/AGENTS.md` (intentional unsafe prompt/security sample)
- Excluded test fixture: `tests/fixtures/unsafe_examples/README.md` (intentional unsafe prompt/security sample)
