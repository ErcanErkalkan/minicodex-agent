"""Deterministic task decomposition helpers."""

from __future__ import annotations

from pathlib import Path

from .project_inspector import choose_test_command, detect_project


def decompose_task(root: Path, goal: str, max_steps: int = 8) -> str:
    """Return a practical task breakdown for the current project and goal."""

    profile = detect_project(root)
    test_command = choose_test_command(profile, "auto") or "manual test command needed"
    steps = [
        "Inspect the project profile and existing git status.",
        "Create a local snapshot before making edits if the task may change files.",
        "Index/search the project to identify the smallest relevant file set.",
        "Read the relevant files before editing.",
        "Make minimal changes with preview/patch tools.",
        f"Run validation: {test_command}.",
        "Analyze failures and iterate only on directly related files.",
        "Prepare a commit/PR summary and save task memory.",
    ][: max(1, max_steps)]

    lines = [
        "Task decomposition:",
        f"Goal: {goal}",
        "",
        "Detected project:",
        profile.summary(),
        "",
        "Recommended steps:",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    return "\n".join(lines)
