from __future__ import annotations

import subprocess
from pathlib import Path

from minicodex_agent.github_tools import prepare_github_issue, prepare_github_pr


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
    )


def test_prepare_github_pr_returns_safe_command(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "init")

    result = prepare_github_pr(tmp_path, title="My PR", body="Body", base="main")

    assert "gh pr create" in result
    assert "--draft" in result
    assert "My PR" in result


def test_prepare_github_issue_returns_safe_command(tmp_path: Path) -> None:
    result = prepare_github_issue(tmp_path, title="Bug", body="Fix it", labels=["bug"])

    assert "gh issue create" in result
    assert "--label bug" in result
