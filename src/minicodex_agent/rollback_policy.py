"""Rollback policy diagnostics for MiniCodex."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .snapshot_tools import list_snapshots
from .utils import truncate


def _run_git(root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def check_rollback_policy(
    root: Path,
    *,
    max_changed_files: int = 8,
    max_diff_lines: int = 300,
    max_chars: int = 12000,
) -> str:
    """Assess whether the current workspace should be snapshotted or rolled back."""

    root = root.resolve()
    if not (root / ".git").exists():
        snapshots = list_snapshots(root, limit=5)
        return (
            "Rollback policy check: no git repository detected.\n"
            "Recommendation: create_snapshot before risky edits and use restore_snapshot if needed.\n\n"
            f"Recent snapshots:\n{snapshots}"
        )

    status = _run_git(root, ["status", "--short"])
    diff_stat = _run_git(root, ["diff", "--numstat", "--"])
    changed_files = [line for line in status.splitlines() if line.strip()]
    diff_lines = 0
    for line in diff_stat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            for value in parts[:2]:
                if value.isdigit():
                    diff_lines += int(value)

    warnings: list[str] = []
    if len(changed_files) > max_changed_files:
        warnings.append(f"many changed files: {len(changed_files)} > {max_changed_files}")
    if diff_lines > max_diff_lines:
        warnings.append(f"large diff: {diff_lines} changed lines > {max_diff_lines}")

    recommendation = "Workspace is within rollback policy limits."
    if warnings:
        recommendation = (
            "Rollback caution recommended: create a snapshot, review git_diff, "
            "and avoid further broad edits until tests pass."
        )

    rows = [
        "Rollback policy check:",
        f"Changed files: {len(changed_files)}",
        f"Changed diff lines: {diff_lines}",
        f"Warnings: {', '.join(warnings) if warnings else 'none'}",
        f"Recommendation: {recommendation}",
    ]
    if changed_files:
        rows.append("\nChanged files:")
        rows.extend(f"- {line}" for line in changed_files[:80])
    return truncate("\n".join(rows), max_chars)
