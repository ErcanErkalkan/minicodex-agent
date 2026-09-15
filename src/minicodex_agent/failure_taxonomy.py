"""Deterministic failure taxonomy for local MiniCodex telemetry."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .utils import truncate

_FAILURE_CATEGORIES = {
    "model_call_error",
    "model_budget_exceeded",
    "model_action_schema_error",
    "tool_policy_blocked",
    "tool_exit_nonzero",
    "tool_timeout",
    "verification_failed",
    "eval_score_failed",
    "safety_block",
    "cost_budget_exceeded",
    "unknown_failure",
}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def classify_failure(event_or_report: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Classify a telemetry/eval/tool object into a stable failure category."""

    event = (
        dict(event_or_report)
        if isinstance(event_or_report, Mapping)
        else {"value": event_or_report}
    )
    raw = _text(event).lower()
    event_type = str(event.get("type", "")).lower()
    status = str(event.get("status", event.get("outcome_status", ""))).lower()
    exit_code = event.get("exit_code")
    category = "unknown_failure"
    severity = "medium"
    reason = "Failure did not match a more specific taxonomy rule."

    if "cost budget" in raw or "estimated model cost budget exceeded" in raw:
        category, severity, reason = (
            "cost_budget_exceeded",
            "high",
            "Configured model cost budget was exceeded.",
        )
    elif "budget exceeded" in raw or "model call budget" in raw:
        category, severity, reason = (
            "model_budget_exceeded",
            "high",
            "Configured model call/token budget was exceeded.",
        )
    elif (
        "schema" in raw
        or "validation" in raw
        or "model_action_error" in raw
        or "could not parse" in raw
    ):
        category, severity, reason = (
            "model_action_schema_error",
            "medium",
            "Model output failed action/schema parsing or validation.",
        )
    elif "safety" in raw or "unsafe" in raw or "secret" in raw:
        category, severity, reason = (
            "safety_block",
            "critical",
            "Safety or secret-protection policy blocked the operation.",
        )
    elif status in {"policy_blocked", "blocked"} or "policy_blocked" in raw or "block" in status:
        category, severity, reason = (
            "tool_policy_blocked",
            "high",
            "Tool execution was blocked by policy.",
        )
    elif "timeout" in raw or event.get("timed_out") is True:
        category, severity, reason = (
            "tool_timeout",
            "medium",
            "Tool or verification command timed out.",
        )
    elif event_type == "model_call" and (status not in {"", "ok", "success"} or event.get("error")):
        category, severity, reason = (
            "model_call_error",
            "high",
            "Model provider call returned an error.",
        )
    elif event_type == "tool_call" and (
        exit_code not in {None, 0, "0"} or status not in {"", "ok", "success"}
    ):
        category, severity, reason = (
            "tool_exit_nonzero",
            "medium",
            "Tool returned non-zero exit/status.",
        )
    elif "verification" in raw and ("failed" in raw or exit_code not in {None, 0, "0"}):
        category, severity, reason = "verification_failed", "medium", "Verification command failed."
    elif "score" in raw and (event.get("success") is False or event.get("ok") is False):
        category, severity, reason = (
            "eval_score_failed",
            "medium",
            "Eval scoring failed or did not meet success criteria.",
        )

    return {
        "category": category if category in _FAILURE_CATEGORIES else "unknown_failure",
        "severity": severity,
        "reason": reason,
        "evidence": truncate(_text(event), 1000),
    }


def _load_trace(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def build_failure_taxonomy_dashboard(root: Path, limit: int = 20) -> dict[str, Any]:
    """Aggregate failure categories from recent telemetry traces."""

    from .telemetry import RUNS_DIR  # local import avoids a circular dependency

    runs_dir = root / RUNS_DIR
    by_category: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    by_provider: Counter[str] = Counter()
    by_model: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    trace_count = 0
    if runs_dir.exists():
        for path in sorted(
            runs_dir.glob("*/trace.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )[: max(1, int(limit))]:
            data = _load_trace(path)
            if not data:
                continue
            trace_count += 1
            summary = data.get("failure_taxonomy_summary", {})
            if isinstance(summary, Mapping):
                for key, value in dict(summary.get("by_category", {})).items():
                    by_category[str(key)] += int(value or 0)
                for key, value in dict(summary.get("by_severity", {})).items():
                    by_severity[str(key)] += int(value or 0)
            for event in (
                data.get("failure_events", [])
                if isinstance(data.get("failure_events"), list)
                else []
            ):
                if not isinstance(event, Mapping):
                    continue
                cls = (
                    event.get("classification", {})
                    if isinstance(event.get("classification"), Mapping)
                    else classify_failure(event)
                )
                by_category[str(cls.get("category", "unknown_failure"))] += 0 if summary else 1
                by_severity[str(cls.get("severity", "medium"))] += 0 if summary else 1
                provider = str(
                    event.get("provider") or event.get("metadata", {}).get("provider") or "unknown"
                )
                model = str(
                    event.get("model") or event.get("metadata", {}).get("model") or "unknown"
                )
                action = str(event.get("action") or event.get("name") or "unknown")
                by_provider[provider] += 1
                by_model[model] += 1
                by_action[action] += 1
                if len(examples) < 20:
                    examples.append(
                        {
                            "run_id": data.get("run_id"),
                            "category": cls.get("category"),
                            "severity": cls.get("severity"),
                            "evidence": truncate(str(cls.get("evidence", "")), 400),
                        }
                    )
    return {
        "trace_count": trace_count,
        "failure_count": sum(by_category.values()),
        "by_category": dict(by_category),
        "by_severity": dict(by_severity),
        "by_provider": dict(by_provider),
        "by_model": dict(by_model),
        "by_action": dict(by_action),
        "recent_examples": examples,
    }
