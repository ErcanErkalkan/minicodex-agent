from __future__ import annotations

import subprocess
from pathlib import Path

from minicodex_agent.pr_tools import prepare_pr_summary


def test_prepare_pr_summary_without_git(tmp_path: Path):
    result = prepare_pr_summary(tmp_path, "test goal")
    assert "Git repo bulunamadı" in result


def test_prepare_pr_summary_with_git_repo(tmp_path: Path):
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")

    result = prepare_pr_summary(tmp_path, "add readme")

    assert "# Pull Request Draft" in result
    assert "Goal: add readme" in result
    assert "README.md" in result
