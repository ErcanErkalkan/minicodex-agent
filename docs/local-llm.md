# Local LLM providers

MiniCodex supports local and OpenAI-compatible providers. Local providers are useful for offline tests, privacy-sensitive workflows, and deterministic smoke runs.

## Stub and echo providers

```bash
minicodex "smoke test" --provider stub --root . --max-steps 1
minicodex "inspect prompt" --provider echo --root . --max-steps 1
```

These providers do not require API keys and default to zero token cost.

## Ollama

```bash
minicodex "fix a small bug" --provider ollama --model qwen3-coder --root .
```

Ollama defaults to local zero-cost pricing in the built-in price catalog. Actual hardware/runtime cost is not estimated.

## LM Studio / llama.cpp / OpenAI-compatible

```bash
minicodex "run a code review" --provider lmstudio --model qwen3-coder --root .
minicodex "run a code review" --provider openai_compatible --model qwen3-coder --model-base-url http://localhost:1234/v1 --root .
```

Use `--model-action-protocol auto` to let MiniCodex pick native tool calls where supported, or force JSON text with:

```bash
--model-action-protocol json_text
```

## Price catalog

Print local pricing defaults:

```bash
minicodex --model-price-table --root .
```

Hosted-model prices are editable local defaults, not authoritative billing records. Explicit CLI/config prices override catalog defaults. Local providers, `stub`, and `echo` default to zero cost.
