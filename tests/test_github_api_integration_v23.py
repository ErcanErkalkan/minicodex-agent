from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from minicodex_agent.config import AgentConfig
from minicodex_agent.github_api import (
    GitHubApiResult,
    parse_github_remote_url,
    render_github_api_preview,
)
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class LoggerStub:
    def write_plan(self, plan: list[str]) -> None:  # pragma: no cover - interface stub
        pass


def _ctx(
    tmp_path: Path, *, allow_api: bool = False, dry_run: bool = False, confirm: bool = True
) -> ToolContext:
    config = AgentConfig(
        root=tmp_path,
        model="gpt-5.5",
        provider="stub",
        approval="auto",
        log_enabled=False,
        allow_github_api_writes=allow_api,
        dry_run=dry_run,
    )
    return ToolContext(
        config=config,
        state=type("State", (), {"goal": "github", "project_profile": detect_project(tmp_path)})(),
        logger=LoggerStub(),
        confirm_fn=lambda question, auto_approve, **kwargs: confirm,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "remote", "add", "origin", "https://github.com/example/demo.git")
    _git(root, "checkout", "-b", "feature/demo")


def test_parse_github_remote_url_supports_common_forms() -> None:
    assert (
        parse_github_remote_url("https://github.com/acme/project.git").full_name == "acme/project"
    )  # type: ignore[union-attr]
    assert parse_github_remote_url("git@github.com:acme/project.git").full_name == "acme/project"  # type: ignore[union-attr]
    assert (
        parse_github_remote_url("ssh://git@github.com/acme/project.git").full_name == "acme/project"
    )  # type: ignore[union-attr]
    assert parse_github_remote_url("https://gitlab.com/acme/project.git") is None


def test_create_github_actions_are_registered() -> None:
    registry = get_tool_registry()
    assert "create_github_pr" in registry
    assert "create_github_issue" in registry
    assert registry["create_github_pr"].requires_approval is True
    assert registry["create_github_issue"].risk_level == "high"


def test_github_api_preview_resolves_repo_and_branch(tmp_path: Path) -> None:
    _repo(tmp_path)
    preview = render_github_api_preview(
        tmp_path,
        kind="pull_request",
        title="PR",
        body="Body",
        base="main",
        draft=True,
    )
    assert '"repository": "example/demo"' in preview
    assert '"head": "feature/demo"' in preview
    assert '"endpoint": "POST /repos/example/demo/pulls"' in preview


def test_create_github_issue_dry_run_does_not_need_api_enabled(tmp_path: Path) -> None:
    _repo(tmp_path)
    result = dispatch_tool(
        _ctx(tmp_path, allow_api=False, dry_run=True),
        "create_github_issue",
        {"title": "Bug", "body": "Details", "labels": ["bug"]},
    )
    assert "GITHUB API DRY RUN" in result
    assert "POST /repos/example/demo/issues" in result


def test_create_github_issue_blocks_without_explicit_enablement(tmp_path: Path) -> None:
    _repo(tmp_path)
    result = dispatch_tool(
        _ctx(tmp_path, allow_api=False),
        "create_github_issue",
        {"title": "Bug", "body": "Details"},
    )
    assert result.startswith("GITHUB API BLOCK")
    assert "--allow-github-api-writes" in result


def test_create_github_pr_requires_manual_confirmation_even_with_auto_approval(
    tmp_path: Path,
) -> None:
    _repo(tmp_path)
    result = dispatch_tool(
        _ctx(tmp_path, allow_api=True, confirm=False),
        "create_github_pr",
        {"title": "PR", "body": "Body", "base": "main", "head": "feature/demo", "draft": True},
    )
    assert "rejected by user" in result


def test_create_github_issue_calls_api_when_enabled_and_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_create(root: Path, **kwargs: Any) -> GitHubApiResult:
        calls.append(kwargs)
        return GitHubApiResult(
            True, 201, {"html_url": "https://github.com/example/demo/issues/1"}, "ok"
        )

    monkeypatch.setattr("minicodex_agent.tools.github.create_github_issue_api", fake_create)
    result = dispatch_tool(
        _ctx(tmp_path, allow_api=True, confirm=True),
        "create_github_issue",
        {"title": "Bug", "body": "Details", "labels": ["bug"]},
    )
    assert "created successfully" in result
    assert calls and calls[0]["title"] == "Bug"
    assert calls[0]["labels"] == ["bug"]


def test_create_github_pr_dry_run_with_explicit_owner_repo_without_git(tmp_path: Path) -> None:
    result = dispatch_tool(
        _ctx(tmp_path, dry_run=True),
        "create_github_pr",
        {
            "title": "PR",
            "body": "Body",
            "base": "main",
            "head": "feature/demo",
            "owner": "octo",
            "repo": "hello",
            "draft": True,
        },
    )
    assert "GITHUB API DRY RUN" in result
    assert "POST /repos/octo/hello/pulls" in result
