"""Commit-message helper tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .shell_tools import git_diff
from .utils import truncate


def _git_stdout(root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def generate_commit_message(root: Path, *, goal: str = "", max_chars: int = 12000) -> str:
    """Generate a deterministic commit-message draft from git status and diff."""

    status = _git_stdout(root, ["status", "--short"])
    diff = git_diff(root, max_chars=max_chars, profile="balanced")

    changed_files: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        candidate = line[3:].strip() if len(line) > 3 else line.strip()
        if candidate:
            changed_files.append(candidate)

    if not changed_files:
        return "No git changes detected; commit message not generated."

    title_base = goal.strip().rstrip(".") or "Update project with MiniCodex changes"
    title_words = title_base.split()
    title = " ".join(title_words[:12])
    if len(title_words) > 12:
        title += "..."

    body_lines = [
        title,
        "",
        "Summary:",
        f"- Updated {len(changed_files)} file(s).",
    ]
    for path in changed_files[:8]:
        body_lines.append(f"- {path}")
    if len(changed_files) > 8:
        body_lines.append(f"- ... and {len(changed_files) - 8} more")

    body_lines.extend(
        [
            "",
            "Validation:",
            "- Review git diff and run the relevant tests before committing.",
            "",
            "Suggested command:",
            "git add . && git commit -m " + repr(title),
            "",
            "Context:",
            truncate(diff, 2500),
        ]
    )
    return truncate("\n".join(body_lines), max_chars)
