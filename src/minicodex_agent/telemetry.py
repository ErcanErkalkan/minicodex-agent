"""Observability and telemetry primitives for MiniCodex runs.

This module intentionally keeps telemetry local, deterministic, and redacted.
It is not a network exporter.  A run can write a compact trace JSON under
``.minicodex/telemetry/runs`` plus optional JSONL span events.  Dry-run callers
can still build in-memory summaries without creating files.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .failure_taxonomy import classify_failure
from .secret_scanner import redact_secret
from .utils import to_pretty_json, truncate

TELEMETRY_DIR = Path(".minicodex/telemetry")
RUNS_DIR = TELEMETRY_DIR / "runs"
BUNDLES_DIR = TELEMETRY_DIR / "bundles"
PROMPT_VERSION = "prompt-v4.4.8-native-tool-calling"
TRACE_SCHEMA_VERSION = 1
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_id(value: str, *, prefix: str = "run") -> str:
    candidate = str(value or "").strip()
    if candidate and _SAFE_ID_RE.match(candidate) and ".." not in Path(candidate).parts:
        return candidate
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _stable_hash(value: Any) -> str:
    safe = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(safe.encode("utf-8")).hexdigest()[:16]


def sanitize_telemetry(value: Any, *, max_chars: int = 6000, max_items: int = 200) -> Any:
    """Return a redacted, JSON-safe telemetry representation."""

    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return truncate(redact_secret(value), max_chars)
    if isinstance(value, Path):
        return sanitize_telemetry(str(value), max_chars=max_chars, max_items=max_items)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                out["…truncated_items…"] = len(value) - max_items
                break
            out[str(sanitize_telemetry(str(key), max_chars=300, max_items=max_items))] = (
                sanitize_telemetry(
                    item,
                    max_chars=max_chars,
                    max_items=max_items,
                )
            )
        return out
    if isinstance(value, list | tuple | set):
        values = list(value)
        out_list = [
            sanitize_telemetry(item, max_chars=max_chars, max_items=max_items)
            for item in values[:max_items]
        ]
        if len(values) > max_items:
            out_list.append(f"…truncated {len(values) - max_items} additional items…")
        return out_list
    return sanitize_telemetry(str(value), max_chars=max_chars, max_items=max_items)


@dataclass
class TelemetrySpan:
    """One trace span for a model/tool/internal operation."""

    span_id: str
    name: str
    kind: str
    start_ms: int
    end_ms: int | None = None
    duration_ms: int | None = None
    status: str = "running"
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def finish(
        self, *, status: str = "ok", error: str = "", metadata: Mapping[str, Any] | None = None
    ) -> None:
        self.end_ms = _now_ms()
        self.duration_ms = max(0, self.end_ms - self.start_ms)
        self.status = status
        self.error = str(error or "")
        if metadata:
            self.metadata.update(dict(metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TokenLedger:
    """Aggregated model usage/cost metrics."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    by_provider_model: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(
        self,
        *,
        provider: str,
        model: str,
        calls: int,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
    ) -> None:
        key = f"{provider or 'unknown'}/{model or 'unknown'}"
        row = self.by_provider_model.setdefault(
            key,
            {
                "provider": provider or "unknown",
                "model": model or "unknown",
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
            },
        )
        row["calls"] += int(calls)
        row["input_tokens"] += int(input_tokens)
        row["output_tokens"] += int(output_tokens)
        row["estimated_cost_usd"] += float(estimated_cost_usd)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["estimated_cost_usd"] = round(float(self.estimated_cost_usd), 8)
        for row in data.get("by_provider_model", {}).values():
            row["estimated_cost_usd"] = round(float(row.get("estimated_cost_usd", 0.0)), 8)
        return data


@dataclass
class RiskEvent:
    """Security/safety/policy event worth tracking."""

    timestamp_ms: int
    severity: str
    kind: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelemetryRecorder:
    """Collect and optionally persist local MiniCodex telemetry."""

    def __init__(
        self,
        root: Path,
        *,
        enabled: bool = True,
        dry_run: bool = False,
        run_id: str = "",
        prompt_version: str = PROMPT_VERSION,
        max_event_chars: int = 6000,
        write_jsonl: bool = True,
        config_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.root = root
        self.enabled = bool(enabled)
        self.dry_run = bool(dry_run)
        self.run_id = (
            _safe_id(run_id, prefix="trace")
            if run_id
            else f"trace-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        )
        self.prompt_version = prompt_version
        self.max_event_chars = max(1000, int(max_event_chars))
        self.write_jsonl = bool(write_jsonl)
        self.started_ms = _now_ms()
        self.ended_ms: int | None = None
        self.status = "running"
        self.trace_dir = (root / RUNS_DIR / self.run_id).resolve()
        self.trace_path = self.trace_dir / "trace.json"
        self.events_path = self.trace_dir / "events.jsonl"
        self.spans: list[TelemetrySpan] = []
        self.risk_events: list[RiskEvent] = []
        self.failure_events: list[dict[str, Any]] = []
        self.model_events: list[dict[str, Any]] = []
        self.tool_events: list[dict[str, Any]] = []
        self.token_ledger = TokenLedger()
        self.counters: dict[str, int] = {
            "tool_calls": 0,
            "model_calls": 0,
            "failed_tools": 0,
            "blocked_tools": 0,
            "model_errors": 0,
            "approval_events": 0,
        }
        self.metadata = sanitize_telemetry(
            dict(config_metadata or {}), max_chars=self.max_event_chars
        )
        self.prompt_hash = _stable_hash(
            {"prompt_version": prompt_version, "metadata": self.metadata}
        )
        if self.enabled and not self.dry_run:
            self.trace_dir.mkdir(parents=True, exist_ok=True)

    @property
    def active(self) -> bool:
        return self.enabled

    def _write_event(self, event: Mapping[str, Any]) -> None:
        if not self.enabled or self.dry_run or not self.write_jsonl:
            return
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_telemetry(dict(event), max_chars=self.max_event_chars)
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(safe, ensure_ascii=False) + "\n")

    def start_span(
        self, name: str, kind: str, metadata: Mapping[str, Any] | None = None
    ) -> TelemetrySpan:
        span = TelemetrySpan(
            span_id="span-" + uuid.uuid4().hex[:12],
            name=name,
            kind=kind,
            start_ms=_now_ms(),
            metadata=dict(sanitize_telemetry(dict(metadata or {}), max_chars=self.max_event_chars)),
        )
        if self.enabled:
            self.spans.append(span)
            self._write_event({"type": "span_start", **span.to_dict()})
        return span

    def finish_span(
        self,
        span: TelemetrySpan,
        *,
        status: str = "ok",
        error: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        span.finish(
            status=status,
            error=error,
            metadata=dict(sanitize_telemetry(dict(metadata or {}), max_chars=self.max_event_chars)),
        )
        self._write_event({"type": "span_finish", **span.to_dict()})

    def record_tool_call(
        self,
        *,
        action: str,
        args: Mapping[str, Any],
        observation: str,
        outcome_status: str,
        exit_code: int,
        duration_ms: int,
    ) -> None:
        if not self.enabled:
            return
        self.counters["tool_calls"] += 1
        if outcome_status in {"policy_blocked", "blocked"} or "BLOCK" in observation[:160]:
            self.counters["blocked_tools"] += 1
            self.record_risk_event(
                severity="medium",
                kind="tool_blocked",
                summary=f"Tool blocked or policy-limited: {action}",
                details={
                    "action": action,
                    "exit_code": exit_code,
                    "outcome_status": outcome_status,
                },
            )
        elif exit_code != 0 or outcome_status not in {"success", "ok"}:
            self.counters["failed_tools"] += 1
        safe_observation = redact_secret(str(observation or ""))
        safe_observation = re.sub(
            r"(?i)(api[_-]?key\s*[=:]\s*)\S+", r"\1[REDACTED]", safe_observation
        )
        safe_observation = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[REDACTED]", safe_observation)
        event = {
            "type": "tool_call",
            "timestamp_ms": _now_ms(),
            "action": action,
            "args_hash": _stable_hash(args),
            "args_preview": sanitize_telemetry(args, max_chars=1000),
            "observation_preview": truncate(safe_observation, self.max_event_chars),
            "outcome_status": outcome_status,
            "status": outcome_status,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "latency_bucket": latency_bucket(duration_ms),
        }
        self.tool_events.append(dict(event))
        if exit_code != 0 or outcome_status not in {"success", "ok"}:
            classification = classify_failure(event)
            failed = {**event, "classification": classification}
            self.failure_events.append(failed)
            self._write_event({"type": "failure_classified", **failed})
        self._write_event(event)

    def record_model_call(
        self,
        *,
        step: int,
        prompt_chars: int,
        usage_before: Any,
        usage_after: Any,
        status: str = "ok",
        error: str = "",
        duration_ms: int = 0,
        attempts: int = 1,
        provider: str = "",
        model: str = "",
        prompt_profile: str = "",
        prompt_version: str = "",
        prompt_hash: str = "",
        pricing_source: str = "",
        input_price_per_million: float = 0.0,
        output_price_per_million: float = 0.0,
    ) -> None:
        if not self.enabled:
            return
        before = _usage_to_dict(usage_before)
        after = _usage_to_dict(usage_after)
        delta = {
            "calls": max(0, int(after.get("calls", 0)) - int(before.get("calls", 0))),
            "input_tokens": max(
                0, int(after.get("input_tokens", 0)) - int(before.get("input_tokens", 0))
            ),
            "output_tokens": max(
                0, int(after.get("output_tokens", 0)) - int(before.get("output_tokens", 0))
            ),
            "estimated_cost_usd": max(
                0.0,
                float(after.get("estimated_cost_usd", 0.0))
                - float(before.get("estimated_cost_usd", 0.0)),
            ),
        }
        self.counters["model_calls"] += int(delta["calls"] or attempts)
        if status != "ok":
            self.counters["model_errors"] += 1
        provider = provider or str(
            after.get("provider") or self.metadata.get("provider") or "unknown"
        )
        model = model or str(after.get("model") or self.metadata.get("model") or "unknown")
        pricing_source = pricing_source or str(after.get("pricing_source") or "unknown")
        try:
            input_price = float(
                input_price_per_million or after.get("input_price_per_million", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            input_price = 0.0
        try:
            output_price = float(
                output_price_per_million or after.get("output_price_per_million", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            output_price = 0.0
        self.token_ledger.calls += int(delta["calls"])
        self.token_ledger.input_tokens += int(delta["input_tokens"])
        self.token_ledger.output_tokens += int(delta["output_tokens"])
        self.token_ledger.estimated_cost_usd += float(delta["estimated_cost_usd"])
        self.token_ledger.add(
            provider=provider,
            model=model,
            calls=int(delta["calls"]),
            input_tokens=int(delta["input_tokens"]),
            output_tokens=int(delta["output_tokens"]),
            estimated_cost_usd=float(delta["estimated_cost_usd"]),
        )
        event = {
            "type": "model_call",
            "timestamp_ms": _now_ms(),
            "step": step,
            "provider": provider,
            "model": model,
            "prompt_chars": prompt_chars,
            "prompt_profile": prompt_profile or str(self.metadata.get("prompt_profile") or ""),
            "prompt_version": prompt_version or self.prompt_version,
            "prompt_hash": prompt_hash or self.prompt_hash,
            "status": status,
            "error": error,
            "duration_ms": duration_ms,
            "latency_ms": duration_ms,
            "latency_bucket": latency_bucket(duration_ms),
            "attempts": attempts,
            "input_tokens_delta": delta["input_tokens"],
            "output_tokens_delta": delta["output_tokens"],
            "estimated_cost_usd_delta": delta["estimated_cost_usd"],
            "pricing_source": pricing_source,
            "input_price_per_million": input_price,
            "output_price_per_million": output_price,
            "usage_delta": delta,
        }
        self.model_events.append(dict(event))
        if status != "ok" or error:
            classification = classify_failure(event)
            failed = {**event, "classification": classification}
            self.failure_events.append(failed)
            self._write_event({"type": "failure_classified", **failed})
        self._write_event(event)

    def record_risk_event(
        self,
        *,
        severity: str,
        kind: str,
        summary: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        event = RiskEvent(
            timestamp_ms=_now_ms(),
            severity=severity if severity in {"low", "medium", "high", "critical"} else "medium",
            kind=str(kind),
            summary=truncate(redact_secret(str(summary)), 500),
            details=dict(sanitize_telemetry(dict(details or {}), max_chars=self.max_event_chars)),
        )
        self.risk_events.append(event)
        self._write_event({"type": "risk_event", **event.to_dict()})

    def finalize(
        self, *, status: str = "success", result: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        self.ended_ms = _now_ms()
        self.status = str(status)
        payload = self.to_dict(result=result or {})
        if not self.dry_run:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text(to_pretty_json(payload) + "\n", encoding="utf-8")
        return payload

    def to_dict(self, *, result: Mapping[str, Any] | None = None) -> dict[str, Any]:
        ended = self.ended_ms or _now_ms()
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "started_ms": self.started_ms,
            "ended_ms": self.ended_ms,
            "duration_ms": max(0, ended - self.started_ms),
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "metadata": self.metadata,
            "counters": dict(self.counters),
            "token_ledger": self.token_ledger.to_dict(),
            "latency_summary": build_latency_summary(
                self.spans, self.model_events, self.tool_events
            ),
            "failure_taxonomy_summary": summarize_failure_events(self.failure_events),
            "failure_events": sanitize_telemetry(
                self.failure_events, max_chars=self.max_event_chars
            ),
            "model_events": sanitize_telemetry(self.model_events, max_chars=self.max_event_chars),
            "tool_events": sanitize_telemetry(self.tool_events, max_chars=self.max_event_chars),
            "risk_events": [event.to_dict() for event in self.risk_events],
            "spans": [span.to_dict() for span in self.spans],
            "result": sanitize_telemetry(dict(result or {}), max_chars=self.max_event_chars),
            "paths": {
                "trace": str(RUNS_DIR / self.run_id / "trace.json"),
                "events": str(RUNS_DIR / self.run_id / "events.jsonl"),
            },
        }


LATENCY_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0-250ms", 0, 250),
    ("250-500ms", 250, 500),
    ("500ms-1s", 500, 1000),
    ("1-2s", 1000, 2000),
    ("2-5s", 2000, 5000),
    ("5-15s", 5000, 15000),
    (">15s", 15000, float("inf")),
)


def latency_bucket(duration_ms: int | float | None) -> str:
    """Return a stable latency bucket label for milliseconds."""

    try:
        value = max(0.0, float(duration_ms or 0.0))
    except (TypeError, ValueError):
        value = 0.0
    for label, low, high in LATENCY_BUCKETS:
        if low <= value < high:
            return label
    return ">15s"


def percentile(values: list[int | float], p: float) -> float:
    """Nearest-rank percentile with deterministic interpolation."""

    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * max(0.0, min(100.0, float(p))) / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def _duration_from_event(event: Any) -> float | None:
    if isinstance(event, TelemetrySpan):
        if event.duration_ms is None:
            return None
        return float(event.duration_ms)
    if isinstance(event, Mapping):
        value = event.get("duration_ms", event.get("latency_ms"))
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    return None


def build_latency_histogram(events_or_spans: list[Any]) -> dict[str, int]:
    """Build the standard latency histogram from events or spans."""

    histogram = {label: 0 for label, _low, _high in LATENCY_BUCKETS}
    for item in events_or_spans:
        value = _duration_from_event(item)
        if value is None:
            continue
        histogram[latency_bucket(value)] += 1
    return histogram


def _latency_stats(items: list[Any]) -> dict[str, Any]:
    values = [
        value for value in (_duration_from_event(item) for item in items) if value is not None
    ]
    if not values:
        return {
            "count": 0,
            "min_ms": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "max_ms": 0,
            "histogram": build_latency_histogram([]),
        }
    return {
        "count": len(values),
        "min_ms": round(min(values), 3),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "max_ms": round(max(values), 3),
        "histogram": build_latency_histogram(items),
    }


def build_latency_summary(
    spans: list[TelemetrySpan] | None = None,
    model_events: Sequence[Mapping[str, Any]] | None = None,
    tool_events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return model/tool latency summaries with histograms."""

    spans = spans or []
    model_items: list[Any] = list(model_events or []) or [
        span for span in spans if span.kind == "model"
    ]
    tool_items: list[Any] = list(tool_events or []) or [
        span for span in spans if span.kind == "tool"
    ]
    return {"model": _latency_stats(model_items), "tool": _latency_stats(tool_items)}


def summarize_failure_events(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate classified failures for one run."""

    by_category: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    for event in events:
        cls = event.get("classification", {}) if isinstance(event, Mapping) else {}
        if not isinstance(cls, Mapping):
            cls = classify_failure(event)
        by_category[str(cls.get("category", "unknown_failure"))] += 1
        by_severity[str(cls.get("severity", "medium"))] += 1
    return {
        "failure_count": len(events),
        "by_category": dict(by_category),
        "by_severity": dict(by_severity),
    }


def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
    if hasattr(usage, "to_dict"):
        try:
            data = usage.to_dict()
        except Exception:  # noqa: BLE001
            data = {}
    elif hasattr(usage, "__dict__"):
        data = dict(usage.__dict__)
    elif isinstance(usage, Mapping):
        data = dict(usage)
    else:
        data = {}
    return {
        "calls": int(data.get("calls", 0) or 0),
        "input_tokens": int(data.get("input_tokens", 0) or 0),
        "output_tokens": int(data.get("output_tokens", 0) or 0),
        "estimated_cost_usd": float(data.get("estimated_cost_usd", 0.0) or 0.0),
        "provider": str(data.get("provider", "") or ""),
        "model": str(data.get("model", "") or ""),
        "pricing_source": str(data.get("pricing_source", "") or ""),
        "input_price_per_million": float(data.get("input_price_per_million", 0.0) or 0.0),
        "output_price_per_million": float(data.get("output_price_per_million", 0.0) or 0.0),
    }


def list_telemetry_runs(root: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent telemetry run summaries."""

    runs_dir = root / RUNS_DIR
    if not runs_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(
        runs_dir.glob("*/trace.json"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "run_id": data.get("run_id") or path.parent.name,
                "status": data.get("status", "unknown"),
                "duration_ms": data.get("duration_ms", 0),
                "prompt_version": data.get("prompt_version", ""),
                "counters": data.get("counters", {}),
                "token_ledger": data.get("token_ledger", {}),
                "path": str(path.relative_to(root)),
            }
        )
        if len(items) >= max(1, int(limit)):
            break
    return items


def read_telemetry_run(
    root: Path, run_id: str, *, include_spans: bool = True, max_chars: int = 24000
) -> str:
    """Read a telemetry trace by id."""

    safe = _safe_id(run_id, prefix="trace")
    if safe != run_id:
        return f"Invalid telemetry run_id: {run_id}"
    path = root / RUNS_DIR / safe / "trace.json"
    if not path.exists():
        return f"Telemetry run not found: {run_id}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"Could not read telemetry run {run_id}: {exc}"
    if not include_spans:
        data.pop("spans", None)
    return truncate("Telemetry run:\n" + to_pretty_json(data), max_chars)


def summarize_telemetry(root: Path, *, limit: int = 20, max_chars: int = 24000) -> str:
    """Render aggregate telemetry metrics for recent runs."""

    runs = list_telemetry_runs(root, limit=limit)
    totals = {
        "runs": len(runs),
        "model_calls": 0,
        "tool_calls": 0,
        "failed_tools": 0,
        "blocked_tools": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
    }
    for run in runs:
        counters = run.get("counters", {}) if isinstance(run.get("counters"), dict) else {}
        ledger = run.get("token_ledger", {}) if isinstance(run.get("token_ledger"), dict) else {}
        totals["model_calls"] += int(counters.get("model_calls", 0) or ledger.get("calls", 0) or 0)
        totals["tool_calls"] += int(counters.get("tool_calls", 0) or 0)
        totals["failed_tools"] += int(counters.get("failed_tools", 0) or 0)
        totals["blocked_tools"] += int(counters.get("blocked_tools", 0) or 0)
        totals["input_tokens"] += int(ledger.get("input_tokens", 0) or 0)
        totals["output_tokens"] += int(ledger.get("output_tokens", 0) or 0)
        totals["estimated_cost_usd"] += float(ledger.get("estimated_cost_usd", 0.0) or 0.0)
    return truncate(
        "MiniCodex telemetry summary:\n" + to_pretty_json({"totals": totals, "runs": runs}),
        max_chars,
    )


def compare_telemetry_runs(
    root: Path, baseline_run_id: str, candidate_run_id: str, *, max_chars: int = 24000
) -> str:
    """Compare two telemetry traces."""

    def _load(run_id: str) -> dict[str, Any] | None:
        safe = _safe_id(run_id, prefix="trace")
        if safe != run_id:
            return None
        path = root / RUNS_DIR / safe / "trace.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    base = _load(baseline_run_id)
    cand = _load(candidate_run_id)
    if base is None:
        return f"Telemetry run not found: {baseline_run_id}"
    if cand is None:
        return f"Telemetry run not found: {candidate_run_id}"

    def _metrics(data: Mapping[str, Any]) -> dict[str, Any]:
        counters = data.get("counters", {}) if isinstance(data.get("counters"), Mapping) else {}
        ledger = (
            data.get("token_ledger", {}) if isinstance(data.get("token_ledger"), Mapping) else {}
        )
        return {
            "duration_ms": int(data.get("duration_ms", 0) or 0),
            "model_calls": int(counters.get("model_calls", 0) or ledger.get("calls", 0) or 0),
            "tool_calls": int(counters.get("tool_calls", 0) or 0),
            "failed_tools": int(counters.get("failed_tools", 0) or 0),
            "blocked_tools": int(counters.get("blocked_tools", 0) or 0),
            "input_tokens": int(ledger.get("input_tokens", 0) or 0),
            "output_tokens": int(ledger.get("output_tokens", 0) or 0),
            "estimated_cost_usd": float(ledger.get("estimated_cost_usd", 0.0) or 0.0),
        }

    base_m = _metrics(base)
    cand_m = _metrics(cand)
    delta = {
        key: cand_m[key] - base_m[key] for key in base_m if isinstance(base_m[key], int | float)
    }
    return truncate(
        "Telemetry run comparison:\n"
        + to_pretty_json(
            {
                "baseline": {"run_id": baseline_run_id, **base_m},
                "candidate": {"run_id": candidate_run_id, **cand_m},
                "delta_candidate_minus_baseline": delta,
            }
        ),
        max_chars,
    )


def export_telemetry_bundle(
    root: Path, *, run_id: str = "", max_chars: int = 24000, dry_run: bool = False
) -> str:
    """Export a compact telemetry bundle for review/evals."""

    if run_id:
        safe = _safe_id(run_id, prefix="trace")
        if safe != run_id:
            return f"Invalid telemetry run_id: {run_id}"
        path = root / RUNS_DIR / safe / "trace.json"
        if not path.exists():
            return f"Telemetry run not found: {run_id}"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("spans", None)
        bundle_id = f"bundle-{safe}"
    else:
        data = {"summary": list_telemetry_runs(root, limit=50)}
        bundle_id = f"bundle-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    payload = sanitize_telemetry(
        {"bundle_id": bundle_id, "created_ms": _now_ms(), "data": data}, max_chars=max_chars
    )
    if dry_run:
        return "DRY-RUN: would write telemetry bundle:\n" + truncate(
            to_pretty_json(payload), max_chars
        )
    out_dir = root / BUNDLES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{bundle_id}.json"
    out_path.write_text(to_pretty_json(payload) + "\n", encoding="utf-8")
    return truncate(
        f"Telemetry bundle written: {out_path.relative_to(root)}\n" + to_pretty_json(payload),
        max_chars,
    )


def _load_recent_traces(root: Path, limit: int) -> list[dict[str, Any]]:
    runs_dir = root / RUNS_DIR
    traces: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return traces
    for path in sorted(
        runs_dir.glob("*/trace.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )[: max(1, int(limit))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            data["_path"] = str(path.relative_to(root))
            traces.append(data)
    return traces


def _merge_latency_summaries(values: list[Mapping[str, Any]], kind: str) -> dict[str, Any]:
    durations: list[float] = []
    histogram: Counter[str] = Counter({label: 0 for label, _low, _high in LATENCY_BUCKETS})
    for summary in values:
        section = summary.get(kind, {}) if isinstance(summary.get(kind), Mapping) else {}
        hist = section.get("histogram", {}) if isinstance(section.get("histogram"), Mapping) else {}
        for label, count in hist.items():
            histogram[str(label)] += int(count or 0)
        # Use summary percentiles as compact approximations when raw events are unavailable.
        for key in ("min_ms", "p50_ms", "p95_ms", "max_ms"):
            if section.get(key) is not None:
                try:
                    durations.append(float(section.get(key) or 0.0))
                except (TypeError, ValueError):
                    pass
    if not durations:
        return _latency_stats([])
    return {
        "count": sum(histogram.values()),
        "min_ms": round(min(durations), 3),
        "p50_ms": percentile(durations, 50),
        "p95_ms": percentile(durations, 95),
        "max_ms": round(max(durations), 3),
        "histogram": dict(histogram),
    }


def build_optimization_dashboard(root: Path, limit: int = 20) -> dict[str, Any]:
    """Build a local telemetry dashboard for performance/quality decisions."""

    traces = _load_recent_traces(root, limit)
    success = sum(1 for item in traces if str(item.get("status", "")).lower() in {"success", "ok"})
    failure = len(traces) - success
    total_input = 0
    total_output = 0
    total_cost = 0.0
    provider_model: dict[str, dict[str, Any]] = {}
    prompt_breakdown: dict[str, dict[str, Any]] = {}
    failure_category: Counter[str] = Counter()
    failure_severity: Counter[str] = Counter()
    slowest_model: list[dict[str, Any]] = []
    slowest_tool: list[dict[str, Any]] = []
    expensive_runs: list[dict[str, Any]] = []
    schema_reports: list[dict[str, Any]] = []
    latency_summaries: list[Mapping[str, Any]] = []

    for trace in traces:
        ledger = (
            trace.get("token_ledger", {}) if isinstance(trace.get("token_ledger"), Mapping) else {}
        )
        total_input += int(ledger.get("input_tokens", 0) or 0)
        total_output += int(ledger.get("output_tokens", 0) or 0)
        cost = float(ledger.get("estimated_cost_usd", 0.0) or 0.0)
        total_cost += cost
        expensive_runs.append(
            {
                "run_id": trace.get("run_id"),
                "estimated_cost_usd": round(cost, 8),
                "path": trace.get("_path"),
            }
        )
        by_pm = (
            ledger.get("by_provider_model", {})
            if isinstance(ledger.get("by_provider_model"), Mapping)
            else {}
        )
        for key, row in by_pm.items():
            target = provider_model.setdefault(
                str(key),
                {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0},
            )
            target["calls"] += int(row.get("calls", 0) or 0)
            target["input_tokens"] += int(row.get("input_tokens", 0) or 0)
            target["output_tokens"] += int(row.get("output_tokens", 0) or 0)
            target["estimated_cost_usd"] += float(row.get("estimated_cost_usd", 0.0) or 0.0)
        metadata = trace.get("metadata", {}) if isinstance(trace.get("metadata"), Mapping) else {}
        prompt = str(metadata.get("prompt_profile") or trace.get("prompt_profile") or "unknown")
        p = prompt_breakdown.setdefault(
            prompt, {"runs": 0, "successes": 0, "failures": 0, "estimated_cost_usd": 0.0}
        )
        p["runs"] += 1
        p["successes"] += 1 if str(trace.get("status", "")).lower() in {"success", "ok"} else 0
        p["failures"] += 1 if str(trace.get("status", "")).lower() not in {"success", "ok"} else 0
        p["estimated_cost_usd"] += cost
        ft = (
            trace.get("failure_taxonomy_summary", {})
            if isinstance(trace.get("failure_taxonomy_summary"), Mapping)
            else {}
        )
        for key, value in dict(ft.get("by_category", {})).items():
            failure_category[str(key)] += int(value or 0)
        for key, value in dict(ft.get("by_severity", {})).items():
            failure_severity[str(key)] += int(value or 0)
        latency = (
            trace.get("latency_summary", {})
            if isinstance(trace.get("latency_summary"), Mapping)
            else {}
        )
        latency_summaries.append(latency)
        result = trace.get("result", {}) if isinstance(trace.get("result"), Mapping) else {}
        reliability = (
            result.get("model_schema_reliability", {})
            if isinstance(result.get("model_schema_reliability"), Mapping)
            else {}
        )
        if reliability:
            schema_reports.append(dict(reliability))
        for event in (
            trace.get("model_events", []) if isinstance(trace.get("model_events"), list) else []
        ):
            if isinstance(event, Mapping):
                slowest_model.append(
                    {
                        "run_id": trace.get("run_id"),
                        "duration_ms": event.get("duration_ms", 0),
                        "provider": event.get("provider"),
                        "model": event.get("model"),
                        "status": event.get("status"),
                    }
                )
        for event in (
            trace.get("tool_events", []) if isinstance(trace.get("tool_events"), list) else []
        ):
            if isinstance(event, Mapping):
                slowest_tool.append(
                    {
                        "run_id": trace.get("run_id"),
                        "duration_ms": event.get("duration_ms", 0),
                        "action": event.get("action"),
                        "status": event.get("status"),
                    }
                )

    for row in provider_model.values():
        row["estimated_cost_usd"] = round(float(row.get("estimated_cost_usd", 0.0)), 8)
    for row in prompt_breakdown.values():
        row["estimated_cost_usd"] = round(float(row.get("estimated_cost_usd", 0.0)), 8)
    slowest_model = sorted(
        slowest_model, key=lambda row: float(row.get("duration_ms", 0) or 0), reverse=True
    )[:10]
    slowest_tool = sorted(
        slowest_tool, key=lambda row: float(row.get("duration_ms", 0) or 0), reverse=True
    )[:10]
    expensive_runs = sorted(
        expensive_runs, key=lambda row: float(row.get("estimated_cost_usd", 0) or 0), reverse=True
    )[:10]
    recommendations: list[str] = []
    if failure > success and traces:
        recommendations.append(
            "Failure rate is high; inspect failure taxonomy before changing prompts/models."
        )
    if _merge_latency_summaries(latency_summaries, "model").get("p95_ms", 0) > 5000:
        recommendations.append(
            "Model p95 latency is above 5s; compare prompt size and provider/model latency."
        )
    if total_cost > 0:
        recommendations.append(
            "Cost is non-zero; review provider/model breakdown and consider cheaper profiles for low-risk tasks."
        )
    if failure_category:
        top = failure_category.most_common(1)[0][0]
        recommendations.append(
            f"Most common failure category is {top}; prioritize targeted mitigation/tests."
        )
    if not recommendations:
        recommendations.append(
            "No high-risk optimization signal detected in the selected telemetry window."
        )

    return {
        "run_count": len(traces),
        "success_count": success,
        "failure_count": failure,
        "total_cost_usd": round(total_cost, 8),
        "average_cost_usd": round(total_cost / len(traces), 8) if traces else 0.0,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "provider_model_cost_breakdown": provider_model,
        "latency_summary": {
            "model": _merge_latency_summaries(latency_summaries, "model"),
            "tool": _merge_latency_summaries(latency_summaries, "tool"),
        },
        "failure_taxonomy_summary": {
            "by_category": dict(failure_category),
            "by_severity": dict(failure_severity),
        },
        "slowest_model_calls": slowest_model,
        "slowest_tool_calls": slowest_tool,
        "most_expensive_runs": expensive_runs,
        "schema_reliability": schema_reports[-10:],
        "prompt_profile_breakdown": prompt_breakdown,
        "recommendations": recommendations,
    }


def render_optimization_dashboard(root: Path, limit: int = 20, max_chars: int = 24000) -> str:
    """Render the optimization dashboard as concise JSON text."""

    return truncate(
        "MiniCodex optimization dashboard:\n"
        + to_pretty_json(build_optimization_dashboard(root, limit=limit)),
        max_chars,
    )
