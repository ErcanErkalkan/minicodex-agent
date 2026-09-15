"""Developer-experience helpers for review bundles, run summaries, and IDE bridges."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .secret_scanner import redact_secret
from .utils import to_pretty_json, truncate

REVIEW_BUNDLE_DIR = Path(".minicodex/review_bundles")
IDE_BRIDGE_PATH = Path(".minicodex/ide/bridge.json")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_id(value: str, *, label: str = "id") -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", value):
        raise ValueError(f"Invalid {label}: use only letters, digits, dot, underscore, or dash")
    if ".." in value or value.startswith(("/", "\\")):
        raise ValueError(f"Invalid {label}: path traversal is not allowed")
    return value


def _run_git(root: Path, args: list[str], max_chars: int) -> str:
    if not (root / ".git").exists():
        return ""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git {' '.join(args)} failed: {type(exc).__name__}: {exc}"
    return truncate(redact_secret((completed.stdout or "") + (completed.stderr or "")), max_chars)


def _latest_child(path: Path) -> Path | None:
    if not path.exists():
        return None
    children = sorted(path.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
    return children[0] if children else None


def review_bundle_path(root: Path, bundle_id: str) -> Path:
    """Return the safe review-bundle JSON path."""

    safe = _safe_id(bundle_id, label="bundle_id")
    return (root / REVIEW_BUNDLE_DIR / f"{safe}.json").resolve()


def _bundle_id() -> str:
    return "rb-" + time.strftime("%Y%m%d-%H%M%S")


def build_change_review_payload(
    root: Path,
    *,
    bundle_id: str = "",
    title: str = "",
    goal: str = "",
    max_diff_chars: int = 16000,
) -> dict[str, Any]:
    """Build a JSON-safe snapshot of the current reviewable change set."""

    max_diff_chars = max(1000, int(max_diff_chars))
    has_git = (root / ".git").exists()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "bundle_id": bundle_id or _bundle_id(),
        "created_at": _now(),
        "title": title or "MiniCodex change review",
        "goal": goal,
        "root": str(root),
        "has_git": has_git,
        "status_short": _run_git(root, ["status", "--short"], 8000)
        if has_git
        else "No .git directory found.",
        "unstaged_numstat": _run_git(root, ["diff", "--numstat"], 8000) if has_git else "",
        "staged_numstat": _run_git(root, ["diff", "--cached", "--numstat"], 8000)
        if has_git
        else "",
        "unstaged_diff": _run_git(root, ["diff", "--", "."], max_diff_chars) if has_git else "",
        "staged_diff": _run_git(root, ["diff", "--cached", "--", "."], max_diff_chars)
        if has_git
        else "",
        "review_state": "pending",
        "decisions": [],
        "instructions": [
            "Inspect status_short and numstat first.",
            "Review staged_diff and unstaged_diff before approving.",
            "Run scan_secrets before PR/commit readiness.",
            "Use record_review_decision with approved/rejected/needs_changes after review.",
        ],
    }
    return payload


def render_tui_panel(root: Path, *, goal: str = "", max_diff_chars: int = 8000) -> str:
    """Render a dependency-free terminal dashboard panel."""

    payload = build_change_review_payload(root, goal=goal, max_diff_chars=max_diff_chars)
    status = payload.get("status_short") or "No changed files."
    unstaged = payload.get("unstaged_numstat") or "No unstaged line changes."
    staged = payload.get("staged_numstat") or "No staged line changes."
    diff = payload.get("unstaged_diff") or payload.get("staged_diff") or "No diff preview."
    lines = [
        "┌─ MiniCodex Developer Panel ─────────────────────────────",
        f"│ Root: {root}",
        f"│ Goal: {goal or '<none>'}",
        f"│ Git: {'available' if payload.get('has_git') else 'not available'}",
        "├─ Status ────────────────────────────────────────────────",
        str(status).rstrip(),
        "├─ Line Summary ───────────────────────────────────────────",
        "Unstaged:",
        str(unstaged).rstrip(),
        "Staged:",
        str(staged).rstrip(),
        "├─ Diff Preview ───────────────────────────────────────────",
        truncate(str(diff).rstrip(), max_diff_chars),
        "└──────────────────────────────────────────────────────────",
    ]
    return "\n".join(lines)


def create_review_bundle(
    root: Path,
    *,
    title: str = "",
    goal: str = "",
    max_diff_chars: int = 16000,
    dry_run: bool = False,
) -> str:
    """Create a persisted review bundle for a human/IDE diff approval flow."""

    payload = build_change_review_payload(
        root, title=title, goal=goal, max_diff_chars=max_diff_chars
    )
    path = review_bundle_path(root, str(payload["bundle_id"]))
    if dry_run:
        payload["dry_run"] = True
        return "DRY-RUN REVIEW_BUNDLE_JSON\n" + to_pretty_json(
            {"path": str(path.relative_to(root)), "bundle": payload}
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(payload) + "\n", encoding="utf-8")
    return "REVIEW_BUNDLE_JSON\n" + to_pretty_json(
        {"path": str(path.relative_to(root)), "bundle": payload}
    )


def list_review_bundles(root: Path, *, limit: int = 20) -> str:
    """List recent review bundles."""

    base = root / REVIEW_BUNDLE_DIR
    bundles: list[dict[str, Any]] = []
    if base.exists():
        for path in sorted(
            base.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        )[: max(1, limit)]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"bundle_id": path.stem, "error": "invalid JSON"}
            bundles.append(
                {
                    "bundle_id": payload.get("bundle_id", path.stem),
                    "created_at": payload.get("created_at", ""),
                    "title": payload.get("title", ""),
                    "goal": payload.get("goal", ""),
                    "review_state": payload.get("review_state", "unknown"),
                    "path": str(path.relative_to(root)),
                }
            )
    return "REVIEW_BUNDLES_JSON\n" + to_pretty_json({"bundles": bundles})


def read_review_bundle(root: Path, *, bundle_id: str = "", max_chars: int = 20000) -> str:
    """Read a review bundle, defaulting to the latest one."""

    if bundle_id:
        path = review_bundle_path(root, bundle_id)
    else:
        latest = _latest_child(root / REVIEW_BUNDLE_DIR)
        if latest is None:
            return "No review bundles found."
        path = latest
    if not path.exists():
        return f"Review bundle not found: {path.relative_to(root)}"
    text = path.read_text(encoding="utf-8")
    return "REVIEW_BUNDLE_JSON\n" + truncate(redact_secret(text), max(1000, int(max_chars)))


def record_review_decision(
    root: Path,
    *,
    bundle_id: str,
    decision: str,
    note: str = "",
    dry_run: bool = False,
) -> str:
    """Record an approve/reject/needs_changes decision inside a review bundle."""

    normalized = decision.strip().lower()
    if normalized not in {"approved", "rejected", "needs_changes"}:
        return "Invalid decision. Use approved, rejected, or needs_changes."
    path = review_bundle_path(root, bundle_id)
    if not path.exists():
        return f"Review bundle not found: {path.relative_to(root)}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    decision_payload = {"created_at": _now(), "decision": normalized, "note": note}
    payload.setdefault("decisions", []).append(decision_payload)
    payload["review_state"] = normalized
    if dry_run:
        return "DRY-RUN REVIEW_DECISION_JSON\n" + to_pretty_json(
            {"path": str(path.relative_to(root)), "decision": decision_payload}
        )
    path.write_text(to_pretty_json(payload) + "\n", encoding="utf-8")
    return "REVIEW_DECISION_JSON\n" + to_pretty_json(
        {"path": str(path.relative_to(root)), "decision": decision_payload}
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def render_run_summary(
    root: Path, *, run_id: str = "", limit: int = 30, max_chars: int = 16000
) -> str:
    """Render a compact summary of a saved .minicodex/runs transcript."""

    runs_dir = root / ".minicodex" / "runs"
    if run_id:
        path = runs_dir / _safe_id(run_id, label="run_id")
    else:
        path = _latest_child(runs_dir) or Path("")
    if not path or not path.exists():
        return "No saved run logs found."
    metadata = _read_json_file(path / "metadata.json")
    final = _read_json_file(path / "final.json")
    events: list[dict[str, Any]] = []
    events_path = path / "events.jsonl"
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "step":
                events.append(event)
    steps = [
        {
            "step": event.get("step"),
            "action": event.get("action"),
            "outcome_status": event.get("outcome_status"),
            "exit_code": event.get("exit_code"),
        }
        for event in events[-max(1, int(limit)) :]
    ]
    payload = {
        "run_id": path.name,
        "path": str(path.relative_to(root)),
        "goal": metadata.get("goal", ""),
        "provider": metadata.get("provider", ""),
        "model": metadata.get("model", ""),
        "step_count": len(events),
        "recent_steps": steps,
        "final_summary": final.get("summary", "") if isinstance(final, dict) else "",
        "changed_files": final.get("changed_files", []) if isinstance(final, dict) else [],
        "checks_run": final.get("checks_run", []) if isinstance(final, dict) else [],
    }
    return "RUN_SUMMARY_JSON\n" + truncate(to_pretty_json(payload), max(1000, int(max_chars)))


def build_ide_bridge_payload(root: Path) -> dict[str, Any]:
    """Return a small JSON document IDE extensions can use for command discovery."""

    latest_run = _latest_child(root / ".minicodex" / "runs")
    latest_bundle = _latest_child(root / REVIEW_BUNDLE_DIR)
    return {
        "schema_version": 1,
        "generated_at": _now(),
        "root": str(root),
        "commands": {
            "start_agent": "minicodex <goal> --root .",
            "safe_analysis": "minicodex <goal> --root . --dry-run --safety-profile strict",
            "review_bundle": "minicodex <goal> --root . --review-after-run",
            "developer_panel": "minicodex --dev-panel --root .",
        },
        "paths": {
            "runs_dir": ".minicodex/runs",
            "review_bundles_dir": str(REVIEW_BUNDLE_DIR),
            "latest_run": str(latest_run.relative_to(root)) if latest_run else "",
            "latest_review_bundle": str(latest_bundle.relative_to(root)) if latest_bundle else "",
        },
        "review_decisions": ["approved", "rejected", "needs_changes"],
    }


def export_ide_bridge(
    root: Path, *, output_path: str = str(IDE_BRIDGE_PATH), dry_run: bool = False
) -> str:
    """Write an IDE bridge descriptor under .minicodex/ide by default."""

    payload = build_ide_bridge_payload(root)
    target = (root / output_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return "IDE bridge output_path must stay inside the project root."
    if dry_run:
        return "DRY-RUN IDE_BRIDGE_JSON\n" + to_pretty_json(
            {"path": str(target.relative_to(root)), "bridge": payload}
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_pretty_json(payload) + "\n", encoding="utf-8")
    return "IDE_BRIDGE_JSON\n" + to_pretty_json(
        {"path": str(target.relative_to(root)), "bridge": payload}
    )
