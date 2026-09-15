from __future__ import annotations

import json
import subprocess
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.github_integration import (
    execute_commit_push_workflow,
    fetch_github_ci_log,
    generate_github_app_manifest,
    init_github_action,
    init_github_webhook_server,
    prepare_github_artifact_upload,
    resolve_review_comments,
)
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class _Logger:
    def log_event(self, *_args, **_kwargs):
        pass


def _ctx(
    root: Path, *, dry_run: bool = False, allow_github: bool = False, allow_network: bool = False
) -> ToolContext:
    return ToolContext(
        config=AgentConfig(
            root=root,
            model="stub",
            provider="stub",
            approval="auto",
            dry_run=dry_run,
            log_enabled=False,
            allow_github_api_writes=allow_github,
            allow_network_commands=allow_network,
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
    _git(root, "config", "user.email", "mini@example.com")
    _git(root, "config", "user.name", "MiniCodex")
    _git(root, "remote", "add", "origin", "https://github.com/example/demo.git")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "initial")


def test_github_full_agent_actions_are_registered() -> None:
    registry = get_tool_registry()
    actions = [
        "generate_github_app_manifest",
        "init_github_webhook_server",
        "fetch_github_ci_log",
        "execute_commit_push_workflow",
        "resolve_review_comments",
        "prepare_github_artifact_upload",
        "create_github_review_comment",
    ]
    for action in actions:
        assert action in ACTION_SPECS
        assert action in registry
    plugin = next(p for p in BUILTIN_PLUGINS if p.name == "git-and-release")
    assert all(action in plugin.tools for action in actions)
    validate_action(
        {
            "thought": "x",
            "action": "fetch_github_ci_log",
            "args": {"run_id": "123", "dry_run": True},
        }
    )


def test_github_app_manifest_and_webhook_scaffold_are_safe(tmp_path: Path) -> None:
    dry = generate_github_app_manifest(
        tmp_path, dry_run=True, webhook_url="https://example.test/hook"
    )
    assert "GitHub App manifest dry-run" in dry
    assert not (tmp_path / ".github" / "minicodex-app-manifest.json").exists()
    result = generate_github_app_manifest(tmp_path, webhook_url="https://example.test/hook")
    assert "GitHub App manifest written" in result
    manifest = json.loads(
        (tmp_path / ".github" / "minicodex-app-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["default_permissions"]["pull_requests"] == "write"
    assert "issue_comment" in manifest["default_events"]

    dry_server = init_github_webhook_server(tmp_path, dry_run=True)
    assert "verify_signature" in dry_server
    assert not (tmp_path / "scripts" / "minicodex_github_webhook.py").exists()
    written = init_github_webhook_server(tmp_path)
    script = tmp_path / "scripts" / "minicodex_github_webhook.py"
    assert "GitHub webhook server written" in written
    assert "X-Hub-Signature-256" in script.read_text(encoding="utf-8")


def test_minicodex_workflow_includes_artifact_upload(tmp_path: Path) -> None:
    result = init_github_action(tmp_path)
    assert "GitHub workflow written" in result
    text = (tmp_path / ".github" / "workflows" / "minicodex-agent.yml").read_text(encoding="utf-8")
    assert "actions/upload-artifact@v4" in text
    assert ".minicodex/agent_workspaces/*/changes.diff" in text
    step = prepare_github_artifact_upload(tmp_path, paths=[".minicodex/runs"])
    assert "Upload MiniCodex artifacts" in step
    assert ".minicodex/runs" in step


def test_real_ci_fetch_is_blocked_without_token_and_network(tmp_path: Path) -> None:
    _repo(tmp_path)
    direct = fetch_github_ci_log(tmp_path, run_id="123")
    assert "GITHUB_TOKEN" in direct
    ctx = _ctx(tmp_path)
    blocked = dispatch_tool(ctx, "fetch_github_ci_log", {"run_id": "123"})
    assert "GITHUB CI FETCH BLOCK" in blocked
    preview = dispatch_tool(_ctx(tmp_path, dry_run=True), "fetch_github_ci_log", {"run_id": "123"})
    assert "GitHub CI fetch preview" in preview


def test_execute_commit_push_workflow_is_dry_run_by_default(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\nchanged\n", encoding="utf-8")
    dry = execute_commit_push_workflow(
        tmp_path, branch="feature/minicodex", commit_message="Update docs"
    )
    assert "GitHub branch/commit/push plan" in dry
    assert "git commit -m 'Update docs'" in dry
    ctx = _ctx(tmp_path, dry_run=True)
    out = dispatch_tool(
        ctx,
        "execute_commit_push_workflow",
        {"branch": "feature/minicodex", "commit_message": "Update docs"},
    )
    assert "git add -- ." in out


def test_resolve_review_comments_groups_by_path(tmp_path: Path) -> None:
    comments = [
        {"path": "src/app.py", "body": "Please handle None."},
        {"path": "src/app.py", "body": "Add a regression test."},
        {"path": "README.md", "body": "Docs need update."},
    ]
    report = resolve_review_comments(tmp_path, comments=comments)
    assert "GitHub review comment resolver" in report
    assert '"resolution_count": 2' in report
    assert "Please handle None" in report


def test_create_github_review_comment_dry_run(tmp_path: Path) -> None:
    _repo(tmp_path)
    ctx = _ctx(tmp_path, dry_run=True)
    result = dispatch_tool(
        ctx, "create_github_review_comment", {"pull_number": 5, "body": "Reviewed by MiniCodex."}
    )
    assert "GITHUB API DRY RUN" in result
    assert "pulls/5/reviews" in result
