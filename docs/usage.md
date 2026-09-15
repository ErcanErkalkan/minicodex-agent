# Usage guide

MiniCodex can run as a local coding agent or as a collection of deterministic inspection commands.

## Basic agent run

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

## Context pack

The context pack contains compact metadata for the current step:

- project profile
- relevant file hints
- compacted observations
- skill catalog metadata
- repo-local instruction metadata

Repo-local instructions are not blindly trusted. `AGENTS.md` and `.minicodex` instructions are scanned first. High/critical risks are blocked from prompt inclusion.

## Tool-oriented commands

MiniCodex exposes many operations without calling a model:

```bash
minicodex --project-health --root .
minicodex --test-matrix-plan --root .
minicodex --final-readiness --root .
minicodex --security-audit --root .
minicodex --scan-repo-instructions --root .
minicodex --optimization-dashboard --root .
```

## Release helpers

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
