"""Persistent task memory for MiniCodex runs.

This module stores small, non-secret run summaries under ``.minicodex`` so
future runs can inspect what the agent previously attempted. It is deliberately
local-only and plain JSONL; no external service is contacted.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import truncate


@dataclass(frozen=True)
class MemoryEntry:
    """One saved task-memory entry."""

    timestamp: str
    goal: str
    summary: str
    changed_files: list[str]
    checks_run: list[str]
    success: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "timestamp": self.timestamp,
            "goal": self.goal,
            "summary": self.summary,
            "changed_files": self.changed_files,
            "checks_run": self.checks_run,
            "success": self.success,
        }


def memory_path(root: Path) -> Path:
    """Return the local memory file path."""

    return root / ".minicodex" / "memory.jsonl"


def save_task_memory(
    root: Path,
    *,
    goal: str,
    summary: str,
    changed_files: list[str] | None = None,
    checks_run: list[str] | None = None,
    success: bool = True,
    dry_run: bool = False,
) -> str:
    """Append a task-memory entry to the local memory file."""

    path = memory_path(root)
    entry = MemoryEntry(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        goal=truncate(goal, 2000),
        summary=truncate(summary, 4000),
        changed_files=changed_files or [],
        checks_run=checks_run or [],
        success=success,
    )
    if dry_run:
        return "DRY-RUN: task memory not saved: " + str(path.relative_to(root))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    return f"Task memory saved: {path.relative_to(root)}"


def read_task_memory(root: Path, limit: int = 10, query: str = "") -> str:
    """Read recent task-memory entries, optionally filtering by query."""

    path = memory_path(root)
    if not path.exists():
        return "No MiniCodex task memory found."

    entries: list[dict[str, Any]] = []
    query_lower = query.lower().strip()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        haystack = json.dumps(entry, ensure_ascii=False).lower()
        if query_lower and query_lower not in haystack:
            continue
        entries.append(entry)

    if not entries:
        return f"No task-memory entries matched query: {query}"

    selected = entries[-max(1, limit) :]
    lines = [f"Showing {len(selected)} task-memory entr{'y' if len(selected) == 1 else 'ies'}:"]
    for index, entry in enumerate(selected, start=1):
        changed = ", ".join(entry.get("changed_files", [])) or "-"
        checks = ", ".join(entry.get("checks_run", [])) or "-"
        lines.append(
            "\n".join(
                [
                    f"{index}. {entry.get('timestamp', '-')}",
                    f"Goal: {entry.get('goal', '-')}",
                    f"Success: {entry.get('success', '-')}",
                    f"Summary: {entry.get('summary', '-')}",
                    f"Changed files: {changed}",
                    f"Checks run: {checks}",
                ]
            )
        )
    return truncate("\n\n".join(lines), 12000)
