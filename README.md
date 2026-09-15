# MiniCodex Agent

MiniCodex Agent is a local, tool-based coding-agent framework for repository analysis, safe edits, tests, evals, telemetry, prompt optimization, GitHub workflows, and release readiness.

Current package version: **4.4.23**.

## What is included

- Local coding-agent loop with strict action schema validation.
- Provider abstraction for OpenAI/OpenAI-compatible, Ollama, LM Studio, llama.cpp, stub, and echo providers.
- Context pack with relevant files, compacted observations, skill metadata, and security-gated repo-local instructions.
- Tool registry for filesystem, shell, testing, code search, patching, security, telemetry, evals, GitHub, and quality gates.
- Local security layer: secret scan, SAST fallback, repo-instruction prompt-injection scan, plugin permission validation, and workspace trust reports.
- Eval layer with built-in tasks, provider baselines, telemetry-linked eval reports, and deterministic prompt A/B comparison.
- Optimization telemetry: token/cost breakdown, latency histograms, failure taxonomy, optimization dashboard, and model price catalog.
- Release gates: marker-aware test matrix, final readiness report, documentation CLI example validation, release package manifest, generated artifact cleanup, CI quality-tool checks.

## Install

```bash
python -m pip install -e ".[dev]"
```

For a minimal runtime install:

```bash
python -m pip install -e .
```

## Quick start

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

## Documentation

- [Usage guide](docs/usage.md)
- [Security model](docs/security.md)
- [Local LLM providers](docs/local-llm.md)
- [Evals and prompt A/B](docs/evals.md)
- [GitHub integration](docs/github.md)
- [Architecture](docs/architecture.md)
- [Quickstart](docs/quickstart.md)
- [Testing and CI](docs/testing.md)

## Security note about repo instructions

Repo-local files such as `AGENTS.md`, `.minicodex/instructions.md`, and `.minicodex/AGENTS.md` are useful but untrusted. In v4.4.13, MiniCodex scans repo instructions before building the model context. High/critical prompt-injection or secret-exfiltration findings are blocked from the prompt, and the context pack records the file as `blocked_by_security_scan` instead of inserting the raw malicious text.

## Release quality gates

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

## Development status

This is a developer-preview local coding-agent framework. It is designed for local experimentation, repository automation, and CI-assisted quality gates. External model/API calls and GitHub write actions remain gated by provider configuration, network policy, and explicit runtime options.
