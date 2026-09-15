"""Pull-request preparation helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .utils import truncate


def _git(root: Path, args: list[str], timeout: int = 30) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return (completed.stdout + completed.stderr).strip()


def _changed_files(root: Path) -> list[str]:
    output = _git(root, ["status", "--short"])
    files: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        files.append(line[3:].strip())
    return files


def prepare_pr_summary(root: Path, goal: str, max_chars: int = 16000) -> str:
    """Generate a local PR summary template from git status and diff stats."""

    if not (root / ".git").exists():
        return "Git repo bulunamadı; PR özeti için önce git repository içinde çalıştırın."

    branch = _git(root, ["branch", "--show-current"]) or "unknown"
    status = _git(root, ["status", "--short"])
    stat = _git(root, ["diff", "--stat"])
    staged_stat = _git(root, ["diff", "--cached", "--stat"])
    files = _changed_files(root)

    summary_bullets = [
        "- Implemented/updated local MiniCodex agent behavior for the requested goal.",
        "- Please review the file-level diff before opening the pull request.",
    ]
    if files:
        summary_bullets.append(f"- Changed files: {len(files)}")

    changed_file_lines = (
        [f"- `{file}`" for file in files] if files else ["- No changed files detected."]
    )
    template = [
        "# Pull Request Draft",
        "",
        f"Branch: `{branch}`",
        f"Goal: {goal}",
        "",
        "## Summary",
        *summary_bullets,
        "",
        "## Changed Files",
        *changed_file_lines,
        "",
        "## Diff Stat",
        "```",
        stat or staged_stat or "No diff stat available.",
        "```",
        "",
        "## Checks",
        "- [ ] Tests pass locally",
        "- [ ] Lint/format check completed",
        "- [ ] No secrets or generated cache files committed",
        "",
        "## Raw Git Status",
        "```",
        status or "Clean working tree.",
        "```",
    ]
    return truncate("\n".join(template), max_chars)
