# Quickstart

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

- [Usage guide](usage.md)
- [Security model](security.md)
- [Local LLM providers](local-llm.md)
- [Evals and prompt A/B](evals.md)
- [Architecture](architecture.md)
