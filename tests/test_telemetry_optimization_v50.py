from __future__ import annotations

from pathlib import Path

from minicodex_agent.failure_taxonomy import build_failure_taxonomy_dashboard, classify_failure
from minicodex_agent.telemetry import (
    TelemetryRecorder,
    build_latency_histogram,
    build_optimization_dashboard,
    latency_bucket,
    percentile,
    render_optimization_dashboard,
)


def test_latency_bucket_histogram_and_percentiles() -> None:
    assert latency_bucket(100) == "0-250ms"
    assert latency_bucket(16000) == ">15s"
    histogram = build_latency_histogram(
        [{"duration_ms": 100}, {"duration_ms": 750}, {"duration_ms": 6000}]
    )
    assert histogram["0-250ms"] == 1
    assert histogram["500ms-1s"] == 1
    assert histogram["5-15s"] == 1
    assert percentile([1, 2, 3], 50) == 2


def test_optimization_dashboard_aggregates_cost_latency_and_failures(tmp_path: Path) -> None:
    rec = TelemetryRecorder(
        tmp_path,
        run_id="trace-opt",
        enabled=True,
        dry_run=False,
        config_metadata={"provider": "stub", "model": "stub", "prompt_profile": "auto"},
    )
    rec.record_model_call(
        step=1,
        prompt_chars=100,
        usage_before={"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0},
        usage_after={
            "calls": 1,
            "input_tokens": 100,
            "output_tokens": 20,
            "estimated_cost_usd": 0.002,
        },
        duration_ms=750,
        provider="stub",
        model="stub",
        pricing_source="catalog",
    )
    rec.record_tool_call(
        action="run_command",
        args={},
        observation="boom",
        outcome_status="error",
        exit_code=1,
        duration_ms=6000,
    )
    rec.finalize(
        status="failed",
        result={"model_schema_reliability": {"schema_reliability": 1.0, "observations": 1}},
    )

    dash = build_optimization_dashboard(tmp_path, limit=5)
    assert dash["run_count"] == 1
    assert dash["total_input_tokens"] == 100
    assert dash["latency_summary"]["model"]["histogram"]["500ms-1s"] >= 1
    assert dash["failure_taxonomy_summary"]["by_category"]
    assert "MiniCodex optimization dashboard" in render_optimization_dashboard(tmp_path)

    failure_dash = build_failure_taxonomy_dashboard(tmp_path, limit=5)
    assert failure_dash["trace_count"] == 1
    assert failure_dash["by_category"]


def test_failure_classifier_categories() -> None:
    classified = classify_failure(
        {"type": "model_call", "status": "error", "error": "Model call budget exceeded"}
    )
    assert classified["category"] == "model_budget_exceeded"
    blocked = classify_failure(
        {"type": "tool_call", "outcome_status": "policy_blocked", "exit_code": 20}
    )
    assert blocked["category"] == "tool_policy_blocked"
