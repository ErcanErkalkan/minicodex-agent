from __future__ import annotations

from minicodex_agent.task_queue import (
    dequeue_next_task,
    enqueue_task,
    list_task_queue,
    update_task_status,
)


def test_task_queue_lifecycle(tmp_path):
    queued = enqueue_task(tmp_path, title="Fix tests", details="Run pytest", priority="high")
    task_id = queued.split("Task queued: ")[1].splitlines()[0]

    listed = list_task_queue(tmp_path)
    assert task_id in listed
    assert "Fix tests" in listed

    next_task = dequeue_next_task(tmp_path)
    assert task_id in next_task
    assert '"status": "doing"' in next_task

    updated = update_task_status(tmp_path, task_id=task_id, status="done", note="passed")
    assert "-> done" in updated
    assert task_id in list_task_queue(tmp_path, status="done")


def test_task_queue_rejects_invalid_status(tmp_path):
    queued = enqueue_task(tmp_path, title="One")
    task_id = queued.split("Task queued: ")[1].splitlines()[0]

    result = update_task_status(tmp_path, task_id=task_id, status="unknown")

    assert "Invalid status" in result
