"""Small git helpers."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .utils import truncate


def is_git_repo(root: Path) -> bool:
    """Return whether root appears to be a git repository."""

    return (root / ".git").exists()


def _git(root: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run git with shell=False."""

    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        shell=False,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def git_status(root: Path, max_chars: int = 12000) -> str:
    """Return short git status."""

    if not is_git_repo(root):
        return "Bu klasörde .git bulunamadı."
    completed = _git(root, ["status", "--short", "--branch"])
    return truncate(
        f"Exit code: {completed.returncode}\n\nSTDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}",
        max_chars,
    )


def create_work_branch(root: Path, prefix: str = "minicodex") -> str:
    """Create and checkout a timestamped git branch."""

    if not is_git_repo(root):
        return "Branch oluşturulmadı: bu klasörde .git yok."
    branch = f"{prefix}/{time.strftime('%Y%m%d-%H%M%S')}"
    completed = _git(root, ["checkout", "-b", branch])
    return (
        f"Branch: {branch}\nExit code: {completed.returncode}\n\n"
        f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
    )
