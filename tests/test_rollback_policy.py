from __future__ import annotations

import subprocess

from minicodex_agent.rollback_policy import check_rollback_policy
from minicodex_agent.snapshot_tools import create_snapshot


def test_rollback_policy_without_git_recommends_snapshot(tmp_path):
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    create_snapshot(tmp_path, label="before")

    result = check_rollback_policy(tmp_path)

    assert "no git repository" in result
    assert "Recent snapshots" in result


def test_rollback_policy_git_large_change_warns(tmp_path):
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    file_path = tmp_path / "app.py"
    file_path.write_text("print('v1')\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
    )
    file_path.write_text("\n".join(f"print({i})" for i in range(20)), encoding="utf-8")

    result = check_rollback_policy(tmp_path, max_diff_lines=5)

    assert "Rollback caution recommended" in result
    assert "large diff" in result
