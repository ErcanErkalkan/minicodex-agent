"""Long-horizon task state, checkpoint, and resume helpers for MiniCodex.

This module stores lightweight, JSON-only task state under
`.minicodex/long_horizon/runs/`. It is deliberately independent from model
providers and tool execution so it can be used by the main agent loop, tools,
and tests without creating cycles.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .utils import to_pretty_json, truncate

LONG_HORIZON_DIR = Path(".minicodex/long_horizon/runs")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _runs_dir(root: Path) -> Path:
    return (root / LONG_HORIZON_DIR).resolve()


def _safe_run_id(run_id: str) -> str:
    run_id = str(run_id).strip()
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be 1-80 chars containing only letters, numbers, _, ., or -")
    return run_id


def long_task_path(root: Path, run_id: str) -> Path:
    """Return the safe JSON path for one long-horizon task."""

    safe_id = _safe_run_id(run_id)
    base = _runs_dir(root)
    path = (base / f"{safe_id}.json").resolve()
    if base not in path.parents and path != base:
        raise ValueError("run_id resolves outside the long-horizon runs directory")
    return path


def _normalize_items(items: Iterable[object], *, kind: str) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, Mapping):
            text = str(
                item.get("description") or item.get("title") or item.get("text") or ""
            ).strip()
            status = str(item.get("status", "pending")).strip() or "pending"
            item_id = str(item.get("id", f"{kind}-{index}")).strip() or f"{kind}-{index}"
        else:
            text = str(item).strip()
            status = "pending"
            item_id = f"{kind}-{index}"
        if not text:
            continue
        if kind == "criterion":
            normalized.append(
                {"id": item_id, "description": text, "status": status, "evidence": ""}
            )
        else:
            normalized.append({"id": item_id, "title": text, "status": status, "details": ""})
    return normalized


def _load_state(root: Path, run_id: str) -> dict[str, Any]:
    path = long_task_path(root, run_id)
    if not path.exists():
        raise FileNotFoundError(f"Long-horizon task not found: {run_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid long-horizon task JSON: {path}")
    return data


def _save_state(root: Path, state: Mapping[str, Any], *, dry_run: bool) -> None:
    run_id = _safe_run_id(str(state.get("run_id", "")))
    path = long_task_path(root, run_id)
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(dict(state)) + "\n", encoding="utf-8")


def _summarize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    criteria = state.get("acceptance_criteria", [])
    milestones = state.get("milestones", [])
    checkpoints = state.get("checkpoints", [])
    if not isinstance(criteria, list):
        criteria = []
    if not isinstance(milestones, list):
        milestones = []
    if not isinstance(checkpoints, list):
        checkpoints = []
    return {
        "run_id": state.get("run_id", ""),
        "title": state.get("title", ""),
        "goal": state.get("goal", ""),
        "status": state.get("status", "active"),
        "created_at": state.get("created_at", ""),
        "updated_at": state.get("updated_at", ""),
        "criteria_total": len(criteria),
        "criteria_done": sum(
            1
            for item in criteria
            if isinstance(item, Mapping) and item.get("status") in {"done", "accepted"}
        ),
        "milestones_total": len(milestones),
        "milestones_done": sum(
            1 for item in milestones if isinstance(item, Mapping) and item.get("status") == "done"
        ),
        "checkpoint_count": len(checkpoints),
        "last_checkpoint": checkpoints[-1] if checkpoints else None,
    }


def create_long_task(
    root: Path,
    *,
    goal: str,
    title: str = "",
    acceptance_criteria: Iterable[object] = (),
    milestones: Iterable[object] = (),
    dry_run: bool = False,
) -> str:
    """Create a durable long-horizon task record and return a JSON report."""

    run_id = _new_id("lh")
    now = _now()
    state: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "title": title.strip() or truncate(goal.strip(), 80),
        "goal": goal.strip(),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "acceptance_criteria": _normalize_items(acceptance_criteria, kind="criterion"),
        "milestones": _normalize_items(milestones, kind="milestone"),
        "checkpoints": [],
        "notes": [],
    }
    _save_state(root, state, dry_run=dry_run)
    return to_pretty_json(
        {
            "ok": True,
            "dry_run": dry_run,
            "summary": (
                "DRY-RUN: would create long-horizon task."
                if dry_run
                else "Long-horizon task created."
            ),
            "task": _summarize_state(state),
            "path": str(long_task_path(root, run_id).relative_to(root)),
        }
    )


def list_long_tasks(root: Path, *, limit: int = 20, include_completed: bool = True) -> str:
    """List saved long-horizon tasks."""

    base = _runs_dir(root)
    rows: list[dict[str, Any]] = []
    if base.exists():
        for path in sorted(
            base.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - corrupt files are reported but do not break listing
                rows.append(
                    {"run_id": path.stem, "status": "invalid", "path": str(path.relative_to(root))}
                )
                continue
            if not isinstance(data, dict):
                continue
            if not include_completed and data.get("status") in {"done", "completed", "cancelled"}:
                continue
            rows.append(_summarize_state(data))
            if len(rows) >= max(1, limit):
                break
    return to_pretty_json({"summary": f"Found {len(rows)} long-horizon task(s).", "tasks": rows})


def read_long_task(
    root: Path, run_id: str, *, include_checkpoints: bool = True, max_chars: int = 40000
) -> str:
    """Read one long-horizon task record."""

    state = _load_state(root, run_id)
    if not include_checkpoints:
        state = dict(state)
        checkpoints = state.get("checkpoints", [])
        state["checkpoints"] = (
            checkpoints[-1:] if isinstance(checkpoints, list) and checkpoints else []
        )
    return truncate(
        to_pretty_json({"summary": "Long-horizon task loaded.", "task": state}), max_chars
    )


def _mark_items(items: list[Any], ids: set[str], *, status: str, evidence: str = "") -> list[Any]:
    result: list[Any] = []
    for item in items:
        if isinstance(item, dict) and str(item.get("id")) in ids:
            item = dict(item)
            item["status"] = status
            if evidence and "evidence" in item:
                item["evidence"] = evidence
        result.append(item)
    return result


def update_acceptance_criteria(
    root: Path,
    run_id: str,
    *,
    accepted: Iterable[str] = (),
    blocked: Iterable[str] = (),
    pending: Iterable[str] = (),
    evidence: str = "",
    dry_run: bool = False,
) -> str:
    """Update acceptance-criterion status for one task."""

    state = _load_state(root, run_id)
    criteria = state.get("acceptance_criteria", [])
    if not isinstance(criteria, list):
        criteria = []
    criteria = _mark_items(
        criteria, {str(item) for item in accepted}, status="accepted", evidence=evidence
    )
    criteria = _mark_items(
        criteria, {str(item) for item in blocked}, status="blocked", evidence=evidence
    )
    criteria = _mark_items(criteria, {str(item) for item in pending}, status="pending")
    state["acceptance_criteria"] = criteria
    state["updated_at"] = _now()
    _save_state(root, state, dry_run=dry_run)
    return to_pretty_json(
        {
            "ok": True,
            "dry_run": dry_run,
            "summary": (
                "DRY-RUN: would update acceptance criteria."
                if dry_run
                else "Acceptance criteria updated."
            ),
            "task": _summarize_state(state),
        }
    )


def create_checkpoint(
    root: Path,
    run_id: str,
    *,
    label: str = "checkpoint",
    summary: str = "",
    completed_milestones: Iterable[str] = (),
    accepted_criteria: Iterable[str] = (),
    changed_files: Iterable[str] = (),
    checks_run: Iterable[str] = (),
    next_steps: Iterable[str] = (),
    observations_summary: str = "",
    status: str = "active",
    dry_run: bool = False,
) -> str:
    """Append a checkpoint to an existing long-horizon task."""

    state = _load_state(root, run_id)
    now = _now()
    checkpoint = {
        "checkpoint_id": _new_id("cp"),
        "created_at": now,
        "label": label.strip() or "checkpoint",
        "summary": summary.strip(),
        "completed_milestones": [str(item) for item in completed_milestones],
        "accepted_criteria": [str(item) for item in accepted_criteria],
        "changed_files": [str(item) for item in changed_files],
        "checks_run": [str(item) for item in checks_run],
        "next_steps": [str(item) for item in next_steps],
        "observations_summary": truncate(observations_summary.strip(), 12000),
    }
    milestones = state.get("milestones", [])
    if isinstance(milestones, list):
        state["milestones"] = _mark_items(
            milestones, set(checkpoint["completed_milestones"]), status="done"
        )
    criteria = state.get("acceptance_criteria", [])
    if isinstance(criteria, list):
        state["acceptance_criteria"] = _mark_items(
            criteria, set(checkpoint["accepted_criteria"]), status="accepted", evidence=summary
        )
    checkpoints = state.get("checkpoints", [])
    if not isinstance(checkpoints, list):
        checkpoints = []
    checkpoints.append(checkpoint)
    state["checkpoints"] = checkpoints
    if status in {"active", "paused", "blocked", "done", "completed", "cancelled"}:
        state["status"] = status
    state["updated_at"] = now
    _save_state(root, state, dry_run=dry_run)
    return to_pretty_json(
        {
            "ok": True,
            "dry_run": dry_run,
            "summary": ("DRY-RUN: would create checkpoint." if dry_run else "Checkpoint created."),
            "checkpoint": checkpoint,
            "task": _summarize_state(state),
        }
    )


def resume_long_task(root: Path, run_id: str, *, max_chars: int = 20000) -> str:
    """Render a compact resume pack for a long-horizon task."""

    state = _load_state(root, run_id)
    criteria = state.get("acceptance_criteria", [])
    milestones = state.get("milestones", [])
    checkpoints = state.get("checkpoints", [])
    if not isinstance(criteria, list):
        criteria = []
    if not isinstance(milestones, list):
        milestones = []
    if not isinstance(checkpoints, list):
        checkpoints = []
    unfinished_criteria = [
        item
        for item in criteria
        if isinstance(item, Mapping) and item.get("status") not in {"done", "accepted"}
    ]
    unfinished_milestones = [
        item for item in milestones if isinstance(item, Mapping) and item.get("status") != "done"
    ]
    payload = {
        "summary": "Resume pack prepared. Continue from last checkpoint and verify unfinished criteria.",
        "task": _summarize_state(state),
        "goal": state.get("goal", ""),
        "unfinished_acceptance_criteria": unfinished_criteria,
        "unfinished_milestones": unfinished_milestones,
        "last_checkpoints": checkpoints[-3:],
        "recommended_next_actions": [
            "Read the files referenced by the last checkpoint before editing.",
            "Plan targeted tests before making additional changes.",
            "Create a new checkpoint after each milestone or before stopping.",
        ],
    }
    return truncate(to_pretty_json(payload), max_chars)


def compact_agent_observations(observations: Iterable[Any], *, max_chars: int = 12000) -> str:
    """Compact an agent observation list into a checkpoint-friendly summary."""

    lines: list[str] = []
    for obs in observations:
        step = getattr(obs, "step", "?")
        action = getattr(obs, "action", "")
        text = str(getattr(obs, "observation", ""))
        summary = text.replace("\r\n", "\n").strip()
        important = []
        for line in summary.splitlines():
            if any(
                token in line
                for token in (
                    "FAILED",
                    "ERROR",
                    "Traceback",
                    "Exit code",
                    "PATCH",
                    "DRY-RUN",
                    "TOOL BLOCK",
                )
            ):
                important.append(line[:300])
        if important:
            summary = "\n".join(important[:8])
        else:
            summary = truncate(summary, 800)
        lines.append(f"Step {step} / {action}:\n{summary}")
    return truncate("\n\n".join(lines), max_chars)
