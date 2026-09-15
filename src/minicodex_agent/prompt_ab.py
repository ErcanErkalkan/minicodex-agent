"""Deterministic prompt-profile A/B comparison for MiniCodex evals."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .eval_runner import REPORT_DIR, init_eval_suite, list_eval_tasks, run_eval_suite
from .utils import to_pretty_json


def _safe_id(value: str) -> str:
    safe = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value).strip().lower()
    )
    safe = "-".join(part for part in safe.split("-") if part)
    return safe or "ab"


def _profile_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    tasks = [item for item in report.get("task_results", []) if isinstance(item, Mapping)]
    total_cost = 0.0
    model_calls = 0
    latency_p50: list[float] = []
    latency_p95: list[float] = []
    failures = 0
    schema_values: list[float] = []
    taxonomy: dict[str, int] = {}
    for task in tasks:
        agent = task.get("agent", {}) if isinstance(task.get("agent"), Mapping) else {}
        usage = agent.get("usage", {}) if isinstance(agent.get("usage"), Mapping) else {}
        total_cost += float(usage.get("estimated_cost_usd", 0.0) or 0.0)
        model_calls += int(usage.get("calls", 0) or 0)
        summary = (
            agent.get("latency_summary", {})
            if isinstance(agent.get("latency_summary"), Mapping)
            else {}
        )
        model_summary = (
            summary.get("model", {}) if isinstance(summary.get("model"), Mapping) else {}
        )
        if model_summary.get("p50_ms") is not None:
            latency_p50.append(float(model_summary.get("p50_ms") or 0.0))
        if model_summary.get("p95_ms") is not None:
            latency_p95.append(float(model_summary.get("p95_ms") or 0.0))
        ft = (
            agent.get("failure_taxonomy_summary", {})
            if isinstance(agent.get("failure_taxonomy_summary"), Mapping)
            else {}
        )
        for key, value in dict(ft.get("by_category", {})).items():
            taxonomy[str(key)] = taxonomy.get(str(key), 0) + int(value or 0)
            failures += int(value or 0)
        reliability = (
            agent.get("schema_reliability", {})
            if isinstance(agent.get("schema_reliability"), Mapping)
            else {}
        )
        if reliability.get("observations"):
            schema_values.append(float(reliability.get("schema_reliability", 0.0) or 0.0))
    return {
        "average_score": float(report.get("average_score", 0.0) or 0.0),
        "success_rate": float(report.get("success_rate", 0.0) or 0.0),
        "total_cost_usd": round(total_cost, 8),
        "average_latency_ms": round(sum(latency_p50) / len(latency_p50), 3) if latency_p50 else 0.0,
        "p95_latency_ms": round(max(latency_p95), 3) if latency_p95 else 0.0,
        "model_calls": model_calls,
        "failure_count": failures,
        "failure_taxonomy": taxonomy,
        "schema_reliability": round(sum(schema_values) / len(schema_values), 4)
        if schema_values
        else 0.0,
    }


def _choose_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"profile": "", "reason": "no profiles were run"}
    winner = sorted(
        rows,
        key=lambda row: (
            -float(row.get("metrics", {}).get("average_score", 0.0)),
            int(row.get("metrics", {}).get("failure_count", 0)),
            float(row.get("metrics", {}).get("total_cost_usd", 0.0)),
            float(row.get("metrics", {}).get("p95_latency_ms", 0.0)),
        ),
    )[0]
    return {
        "profile": winner.get("profile", ""),
        "run_id": winner.get("run_id", ""),
        "reason": "Highest average score, then lower failures, lower cost, lower p95 latency.",
    }


def run_prompt_ab_comparison(
    root: Path,
    config: Any,
    task_ids: list[str] | tuple[str, ...] | None,
    prompt_profiles: list[str] | tuple[str, ...],
    *,
    run_id: str | None = None,
    max_steps: int | None = None,
    model_call_budget: int | None = None,
    timeout: int = 120,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the same eval tasks for multiple prompt profiles and compare outputs."""

    ab_id = _safe_id(run_id or f"{int(time.time())}-{uuid.uuid4().hex[:8]}")
    profiles = [
        _safe_id(profile).replace("_", "-") for profile in prompt_profiles if str(profile).strip()
    ]
    profiles = profiles or ["auto", "local-model"]
    selected = [str(item) for item in (task_ids or []) if str(item).strip()]
    if not selected:
        tasks = list_eval_tasks(root)
        if not tasks:
            init_eval_suite(root, overwrite=False, dry_run=False)
            tasks = list_eval_tasks(root)
        selected = [str(item["id"]) for item in tasks if item.get("valid")][:3]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "run_id": f"ab-{ab_id}",
            "profiles": profiles,
            "task_ids": selected,
        }

    rows: list[dict[str, Any]] = []
    for profile in profiles:
        profile_config = replace(copy.copy(config), prompt_profile=profile)
        eval_run_id = _safe_id(f"ab-{ab_id}-{profile}")
        report = run_eval_suite(
            root,
            profile_config,
            task_ids=selected,
            run_id=eval_run_id,
            max_steps=max_steps,
            model_call_budget=model_call_budget,
            timeout=timeout,
            dry_run=False,
        )
        rows.append(
            {
                "profile": profile,
                "run_id": eval_run_id,
                "metrics": _profile_metrics(report),
                "report_path": str(REPORT_DIR / f"{eval_run_id}.json"),
            }
        )

    result = {
        "ok": True,
        "kind": "deterministic_prompt_ab_comparison",
        "run_id": f"ab-{ab_id}",
        "task_ids": selected,
        "profiles": rows,
        "winner": _choose_winner(rows),
        "notes": "Deterministic A/B comparison over eval tasks; not a statistical significance test.",
    }
    path = root / REPORT_DIR / f"ab-{ab_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(result) + "\n", encoding="utf-8")
    result["path"] = str(path.relative_to(root))
    return result
