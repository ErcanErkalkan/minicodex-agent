from __future__ import annotations

import json
import subprocess
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.github_integration import (
    detect_github_workflows,
    github_ci_fetch_preview,
    init_github_action,
    parse_pr_comment_command,
    prepare_commit_push_plan,
    summarize_github_ci_log,
)
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class _Logger:
    def log_event(self, *_args, **_kwargs):
        pass


def _ctx(root: Path, *, dry_run: bool = False) -> ToolContext:
    return ToolContext(
        config=AgentConfig(
            root=root,
            model="stub",
            provider="stub",
            approval="auto",
            dry_run=dry_run,
            log_enabled=False,
        ),
        state=AgentState(goal="github", project_profile=detect_project(root)),
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
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
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")


def test_github_layer_actions_are_registered() -> None:
    registry = get_tool_registry()
    actions = [
        "detect_github_workflows",
        "init_github_action",
        "parse_pr_comment_command",
        "prepare_commit_push_plan",
        "summarize_github_ci_log",
        "github_ci_fetch_preview",
    ]
    for action in actions:
        assert action in ACTION_SPECS
        assert action in registry
    validate_action(
        {
            "thought": "x",
            "action": "parse_pr_comment_command",
            "args": {"comment": "/minicodex review"},
        }
    )
    plugin = next(p for p in BUILTIN_PLUGINS if p.name == "git-and-release")
    assert all(action in plugin.tools for action in actions)


def test_init_github_action_respects_dry_run_and_writes_workflow(tmp_path: Path) -> None:
    dry = init_github_action(tmp_path, dry_run=True)
    assert "DRY-RUN" in dry
    assert not (tmp_path / ".github" / "workflows" / "minicodex-agent.yml").exists()

    result = init_github_action(tmp_path)
    workflow = tmp_path / ".github" / "workflows" / "minicodex-agent.yml"
    assert "GitHub workflow written" in result
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "issue_comment" in text
    assert "--dry-run" in text


def test_detect_github_workflows_extracts_metadata(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\non:\n  pull_request:\n  push:\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    report = detect_github_workflows(tmp_path)
    assert '"count": 1' in report
    assert '"name": "CI"' in report
    assert '"pull_request"' in report
    assert '"test"' in report


def test_parse_pr_comment_command_defaults_to_dry_run_and_filters_flags() -> None:
    report = parse_pr_comment_command('/minicodex fix "failing tests" --max-steps 4 --danger')
    data = json.loads(report.split("\n", 1)[1])
    assert data["ok"] is True
    assert data["command"] == "fix"
    assert data["goal"] == "failing tests"
    assert "--dry-run" in data["recommended_cli"]
    assert data["value_flags"]["--max-steps"] == "4"
    assert any("unsupported flag" in warning.lower() for warning in data["warnings"])


def test_prepare_commit_push_plan_is_preview_only(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\nchanged\n", encoding="utf-8")
    report = prepare_commit_push_plan(tmp_path, branch="feature/fix", commit_message="Fix docs")
    assert "git add -- ." in report
    assert "git push -u origin feature/fix" in report
    assert "does not execute" in report


def test_summarize_github_ci_log_uses_actions_annotations(tmp_path: Path) -> None:
    log = """
Run pytest
::error file=src/app.py,line=3::AssertionError: expected 2
FAILED tests/test_app.py::test_add - AssertionError
Error: Process completed with exit code 1.
"""
    report = summarize_github_ci_log(tmp_path, output=log, workflow_name="CI")
    assert "GitHub CI log summary" in report
    assert "AssertionError" in report
    assert "github_annotations" in report


def test_github_ci_fetch_preview_resolves_remote(tmp_path: Path) -> None:
    _repo(tmp_path)
    report = github_ci_fetch_preview(tmp_path, run_id="123")
    assert "GET /repos/example/demo/actions/runs/123" in report
    assert "gh run view" in report


def test_new_github_tools_dispatch(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, dry_run=True)
    result = dispatch_tool(ctx, "init_github_action", {"workflow_name": "mini.yml"})
    assert "DRY-RUN" in result
    parsed = dispatch_tool(ctx, "parse_pr_comment_command", {"comment": "/minicodex review"})
    assert "recommended_cli" in parsed
