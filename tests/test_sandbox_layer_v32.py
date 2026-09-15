from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from minicodex_agent.sandbox import (
    SandboxOptions,
    build_sandbox_plan,
    cleanup_workspace,
    create_workspace_copy,
)
from minicodex_agent.shell_tools import run_command


def test_sandbox_copy_excludes_minicodex_and_secrets(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")
    (tmp_path / ".minicodex").mkdir()
    (tmp_path / ".minicodex" / "memory.jsonl").write_text("local memory\n", encoding="utf-8")
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (tmp_path / "outside-link.txt").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Creating symlinks requires Windows developer mode or elevation")
        raise

    workspace = create_workspace_copy(tmp_path)
    try:
        assert (workspace / "app.py").exists()
        assert not (workspace / ".env").exists()
        assert not (workspace / ".minicodex").exists()
        assert not (workspace / "outside-link.txt").exists()
    finally:
        cleanup_workspace(workspace)
    assert not workspace.exists()


def test_docker_plan_uses_filtered_copy_and_resource_flags(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    plan = build_sandbox_plan(
        tmp_path,
        ["python", "app.py"],
        options=SandboxOptions(
            mode="docker", keep_workspace=True, cpus="2", memory="512m", pids_limit=64
        ),
        allow_network=False,
    )
    try:
        assert not plan.blocked
        assert plan.argv[:3] == ["docker", "run", "--rm"]
        assert "--network=none" in plan.argv
        assert "--cpus" in plan.argv and "2" in plan.argv
        assert "--memory" in plan.argv and "512m" in plan.argv
        assert "--pids-limit" in plan.argv and "64" in plan.argv
        assert plan.workspace is not None
        assert plan.workspace != tmp_path
        assert (plan.workspace / "app.py").exists()
        assert "isolated filtered copy" in plan.note
    finally:
        cleanup_workspace(plan.workspace)


def test_sandbox_invalid_modes_are_blocked(tmp_path: Path) -> None:
    result = run_command(
        tmp_path,
        "python -m pytest -q",
        timeout=1,
        max_chars=1000,
        profile="balanced",
        sandbox_mode="not-a-mode",
    )
    assert result.startswith("SANDBOX BLOCK:")
    assert "restricted, docker, or podman" in result


def test_restricted_run_reports_sandbox_config(tmp_path: Path) -> None:
    result = run_command(
        tmp_path,
        "python -c 'print(123)'",
        timeout=30,
        max_chars=4000,
        profile="balanced",
    )
    assert "Execution: restricted local subprocess" in result
    assert "Sandbox: mode=restricted" in result
    assert "Exit code: 0" in result
