"""Persistent local task queue for MiniCodex."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .utils import truncate

QUEUE_PATH = ".minicodex/task_queue.json"
VALID_STATUSES = {"todo", "doing", "done", "blocked", "cancelled"}


def _queue_file(root: Path) -> Path:
    return root.resolve() / QUEUE_PATH


def _read_queue(root: Path) -> list[dict[str, Any]]:
    path = _queue_file(root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _write_queue(root: Path, items: list[dict[str, Any]]) -> None:
    path = _queue_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def enqueue_task(
    root: Path, *, title: str, details: str = "", priority: str = "normal", dry_run: bool = False
) -> str:
    """Add one task to the local queue."""

    if not title.strip():
        return "Task title cannot be empty."
    items = _read_queue(root)
    task_id = uuid.uuid4().hex[:10]
    items.append(
        {
            "id": task_id,
            "title": title.strip(),
            "details": details.strip(),
            "priority": priority.strip() or "normal",
            "status": "todo",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    )
    if dry_run:
        return f"DRY-RUN: task not queued: {task_id}\nTitle: {title.strip()}"
    _write_queue(root, items)
    return f"Task queued: {task_id}\nTitle: {title.strip()}"


def list_task_queue(root: Path, *, status: str = "", limit: int = 20) -> str:
    """List tasks from the local queue."""

    items = _read_queue(root)
    if status:
        items = [item for item in items if str(item.get("status", "")) == status]
    if not items:
        return "Task queue is empty."
    selected = items[-max(1, limit) :]
    rows = [f"Showing {len(selected)} task(s):"]
    for item in selected:
        details = str(item.get("details", "")).replace("\n", " ")
        if len(details) > 80:
            details = details[:77] + "..."
        rows.append(
            f"- {item.get('id')} | {item.get('status')} | {item.get('priority')} | "
            f"{item.get('title')}" + (f" — {details}" if details else "")
        )
    return "\n".join(rows)


def update_task_status(
    root: Path, *, task_id: str, status: str, note: str = "", dry_run: bool = False
) -> str:
    """Update the status of a queued task."""

    if status not in VALID_STATUSES:
        return f"Invalid status: {status}. Valid statuses: {', '.join(sorted(VALID_STATUSES))}"
    items = _read_queue(root)
    for item in items:
        if str(item.get("id")) == task_id:
            item["status"] = status
            item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            if note:
                notes = item.setdefault("notes", [])
                if isinstance(notes, list):
                    notes.append({"at": item["updated_at"], "note": note})
            if dry_run:
                return f"DRY-RUN: task status not updated: {task_id} -> {status}"
            _write_queue(root, items)
            return f"Task updated: {task_id} -> {status}"
    return f"Task not found: {task_id}"


def dequeue_next_task(root: Path, *, dry_run: bool = False) -> str:
    """Mark the next todo task as doing and return it."""

    items = _read_queue(root)
    priority_rank = {"high": 0, "normal": 1, "low": 2}
    candidates = [item for item in items if item.get("status") == "todo"]
    if not candidates:
        return "No todo tasks in queue."
    candidates.sort(key=lambda item: priority_rank.get(str(item.get("priority", "normal")), 1))
    task = candidates[0]
    task["status"] = "doing"
    task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if not dry_run:
        _write_queue(root, items)
    else:
        task = dict(task)
        task["dry_run"] = True
    return truncate(json.dumps(task, ensure_ascii=False, indent=2), 4000)
