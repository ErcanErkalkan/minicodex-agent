# Architecture

MiniCodex is organized as a local agent runtime plus deterministic tools.

## Main layers

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

## Prompt and context

`prompt_engine.py` builds modular profile-aware system prompts. `context_manager.py` builds a bounded context pack containing relevant file hints, compacted observations, skill metadata, and repo-local instruction metadata.

Repo-local instructions are security-gated before prompt inclusion. Risky instruction text is replaced with blocked metadata instead of being inserted raw.

## Model layer

`model_client.py` abstracts providers and records schema reliability. `model_pricing.py` resolves provider/model default pricing and explicit overrides. Local providers and stub/echo default to zero cost.

## Tool layer

`action_schema.py` defines strict action schemas. `tool_registry.py` dispatches registered tools. Built-in tool modules live under `src/minicodex_agent/tools/`.

## Security layer

`security_audit.py`, `secret_scanner.py`, and safety/workspace policy modules provide local security checks, prompt-injection scanning, fixture allowlisting, SAST fallback, plugin permission validation, and workspace trust reports.

## Eval and optimization layer

`eval_runner.py` runs built-in eval tasks and links them to telemetry traces. `prompt_ab.py` runs deterministic prompt profile comparisons. `telemetry.py` aggregates token usage, cost, latency, failures, and dashboard summaries. `failure_taxonomy.py` classifies failures for optimization decisions.

## Quality and release layer

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
