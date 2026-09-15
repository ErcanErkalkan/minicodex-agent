# Evals, telemetry, and prompt A/B

MiniCodex includes an offline-friendly eval layer for repeatable agent tasks and provider comparisons.

## Initialize and list evals

`--list-eval-tasks` remains accepted as a backward-compatible alias, but `--list-evals` is the canonical command.


```bash
minicodex --init-evals --root .
minicodex --list-evals --root .
minicodex --eval-coverage-report --root .
```

## Run evals

```bash
minicodex --run-eval-suite --provider stub --root .
```

Eval reports are written under `.minicodex/evals/reports/`. Each eval task is linked to a deterministic telemetry run id and, when available, the telemetry trace path, latency summary, pricing source, and failure taxonomy summary.

## Compare eval runs

```bash
minicodex --compare-eval-baselines baseline candidate --root .
```

Comparisons include score/success deltas and, when telemetry is available, cost, latency, model-call, and failure-taxonomy deltas.

## Prompt A/B comparison

```bash
minicodex --run-prompt-ab --prompt-ab-profiles auto,local-model --provider stub --root .
```

Prompt A/B comparison is deterministic, not a statistical significance test. The winner is selected by:

1. highest average score
2. lower failure count
3. lower total cost
4. lower p95 latency

Reports are saved as `.minicodex/evals/reports/ab-<run_id>.json`.

## Optimization telemetry

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
