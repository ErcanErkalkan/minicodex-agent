"""Change-set review helpers for safer approval before commits or PRs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .utils import truncate


def _run_git(root: Path, args: list[str], max_chars: int) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return truncate((completed.stdout or "") + (completed.stderr or ""), max_chars)


def review_change_set(root: Path, max_diff_chars: int = 16000) -> str:
    """Summarize the current git change set for a human approval screen."""

    if not (root / ".git").exists():
        return "No .git directory found; change-set review requires a git repository."
    status = _run_git(root, ["status", "--short"], 4000).strip() or "No changed files."
    numstat = _run_git(root, ["diff", "--numstat"], 8000).strip() or "No unstaged line changes."
    staged_numstat = (
        _run_git(root, ["diff", "--cached", "--numstat"], 8000).strip() or "No staged line changes."
    )
    diff = _run_git(root, ["diff", "--", "."], max_diff_chars).strip() or "No unstaged diff."
    return (
        "Change-set review\n"
        "=================\n"
        f"Status:\n{status}\n\n"
        f"Unstaged line summary:\n{numstat}\n\n"
        f"Staged line summary:\n{staged_numstat}\n\n"
        f"Unstaged diff preview:\n{diff}"
    )


def record_change_approval(
    root: Path, decision: str, note: str = "", *, dry_run: bool = False
) -> str:
    """Record a human change-set approval/rejection note locally."""

    normalized = decision.strip().lower()
    if normalized not in {"approved", "rejected", "needs_changes"}:
        return "Invalid decision. Use approved, rejected, or needs_changes."
    import json
    import time

    approvals_dir = root / ".minicodex"
    path = approvals_dir / "change_approvals.jsonl"
    payload = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "decision": normalized,
        "note": note,
    }
    if dry_run:
        return f"DRY-RUN: change approval not recorded in {path.relative_to(root)}: {normalized}"
    approvals_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return f"Change approval recorded in {path.relative_to(root)}: {normalized}"
