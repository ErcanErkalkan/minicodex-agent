# MiniCodex P0-6 Pilot Assets

This directory contains reproducible research assets for the TÜBİTAK 1002-A MiniCodex P0-6 pilot.

- `PILOT_TASK_MANIFEST_20260915_v0_1.json`: ten candidate SWE-bench Verified tasks across five repositories.
- `scripts/p0_6_swebench_preflight.py`: host/resource and manifest preflight.
- `scripts/p0_6_make_noop_predictions.py`: harmless non-empty patches for base-oracle smoke checks because SWE-bench skips empty patches.
- `scripts/run_with_hardware_telemetry.py`: system RAM and NVIDIA VRAM/utilization sampling around a command without changing MiniCodex core telemetry.
- `.github/workflows/p0-6-pilot.yml`: manual-only workflow for a labeled self-hosted research runner.

## Freeze rule

The manifest is a **candidate freeze** until every task passes environment/oracle smoke. Base-oracle smoke must remain unresolved with the harmless probe patch; gold evaluation must resolve. Any evaluator-brittle task is removed before the main pilot.

## Runner requirement

The workflow targets a self-hosted Linux x86_64 runner labeled `minicodex-pilot`. The official SWE-bench harness is Docker-based and resource intensive. The preflight blocks execution when Docker, disk, RAM, CPU, the pinned SWE-bench package, or the manifest are not ready.

## Pinned evaluator

The workflow installs SWE-bench from commit `02e7a74ffd0b707aab73d203fe87bdc7c76afc8e`, the upstream head observed on 2026-09-15, so evaluator updates cannot silently alter pilot results.
