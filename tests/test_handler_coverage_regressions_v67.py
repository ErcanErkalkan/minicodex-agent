from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from minicodex_agent import cli
from minicodex_agent.config import AgentConfig
from minicodex_agent.exit_codes import ExitCode, RunResult
from minicodex_agent.github_api import GitHubApiResult, GitHubIntegrationError
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.run_logger import RunLogger
from minicodex_agent.tools import control as control_tools
from minicodex_agent.tools import diagnostics as diagnostic_tools
from minicodex_agent.tools import evals as eval_tools
from minicodex_agent.tools import github as github_tools
from minicodex_agent.tools import languages as language_tools
from minicodex_agent.tools import long_horizon as long_horizon_tools
from minicodex_agent.tools import python_tools
from minicodex_agent.tools import quality as quality_tools
from minicodex_agent.tools import security as security_tools
from minicodex_agent.tools import shell as shell_handlers
from minicodex_agent.tools import skills as skill_tools
from minicodex_agent.tools import telemetry as telemetry_tools
from minicodex_agent.tools import testing as testing_tools
from minicodex_agent.tools import ux as ux_tools
from minicodex_agent.tools.context import ToolContext


def _ctx(
    root: Path,
    *,
    dry_run: bool = True,
    allow_writes: bool = False,
    confirm: bool = True,
    snapshot: tuple[bool, str] = (True, "snapshot"),
) -> ToolContext:
    config = AgentConfig(
        root=root,
        model="stub",
        provider="stub",
        approval="ask",
        log_enabled=False,
        dry_run=dry_run,
        project_policy_enabled=False,
        allow_github_api_writes=allow_writes,
    )
    return ToolContext(
        config=config,
        state=SimpleNamespace(
            goal="coverage",
            last_command_output="",
            plan=[],
            project_profile=detect_project(root),
        ),
        logger=RunLogger(root, enabled=False),
        confirm_fn=lambda question, auto_approve, **kwargs: confirm,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: snapshot,
        mark_auto_snapshot_handled_fn=lambda: None,
    )


@pytest.mark.parametrize(
    ("flags", "target", "result"),
    [
        (["--dev-panel"], "render_tui_panel", "panel"),
        (["--export-ide-bridge"], "export_ide_bridge", "bridge"),
        (["--init-evals"], "init_eval_suite", "evals"),
        (["--init-eval-baselines"], "init_eval_baselines", "baselines"),
        (["--list-evals"], "list_eval_tasks", ["task"]),
        (["--list-eval-baselines"], "list_eval_baselines", ["baseline"]),
        (["--eval-coverage-report"], "eval_coverage_report", {"covered": True}),
        (["--eval-baseline-plan", "base"], "eval_baseline_plan", {"plan": True}),
        (
            ["--compare-eval-baselines", "base", "candidate"],
            "compare_eval_baselines",
            {"comparison": True},
        ),
        (["--detect-github-workflows"], "detect_github_workflows", "workflows"),
        (["--init-github-action"], "init_github_action", "workflow"),
        (["--parse-pr-comment", "/minicodex test"], "parse_pr_comment_command", "command"),
        (
            ["--generate-github-app-manifest"],
            "generate_github_app_manifest",
            "manifest",
        ),
        (["--init-github-webhook-server"], "init_github_webhook_server", "webhook"),
        (
            ["--prepare-github-artifact-upload"],
            "prepare_github_artifact_upload",
            "artifact",
        ),
        (["--security-audit"], "security_audit_report", "security"),
        (["--scan-repo-instructions"], "scan_repo_instructions", "instructions"),
        (["--project-health"], "project_health_report", "health"),
        (["--test-matrix-plan"], "build_test_matrix_plan", {"matrix": True}),
        (["--release-package-manifest"], "release_package_manifest", "release"),
        (
            ["--clean-generated-artifacts", "--clean-generated-artifacts-dry-run"],
            "clean_generated_artifacts",
            {"clean": True},
        ),
        (["--model-price-table"], "list_model_prices", [{"model": "stub"}]),
        (["--telemetry-summary"], "summarize_telemetry", "telemetry"),
        (["--optimization-dashboard"], "render_optimization_dashboard", "optimization"),
        (["--failure-dashboard"], "build_failure_taxonomy_dashboard", {"failures": []}),
        (["--read-telemetry-run", "run-1"], "read_telemetry_run", "trace"),
        (["--export-telemetry-bundle"], "export_telemetry_bundle", "bundle"),
        (["--list-prompt-profiles"], "list_prompt_profiles", ["auto"]),
        (["--prompt-preview"], "render_prompt_preview", "prompt"),
        (["--find-symbol-references", "target"], "find_symbol_references", []),
        (["--inspect-routes"], "inspect_routes", []),
        (["--create-demo", "demo"], "create_demo_project", "demo"),
    ],
)
def test_cli_routes_offline_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    target: str,
    result: Any,
) -> None:
    monkeypatch.setattr(cli, target, lambda *args, **kwargs: result)
    monkeypatch.setattr(
        sys,
        "argv",
        ["minicodex", "--root", str(tmp_path), "--provider", "stub", "--dry-run", *flags],
    )

    cli.main()

    assert capsys.readouterr().out.strip()


def test_cli_routes_remaining_complex_offline_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Report:
        def to_dict(self) -> dict[str, bool]:
            return {"ok": True}

    class Index:
        def summary(self, *, max_chars: int) -> str:
            return f"index:{max_chars}"

    routes: list[tuple[list[str], str, Any]] = [
        (["--final-readiness"], "final_readiness_report", "ready"),
        (["--run-prompt-ab"], "run_prompt_ab_comparison", {"ok": True}),
        (["--semantic-capability-report"], "semantic_capability_report", Report()),
        (["--build-semantic-index"], "build_semantic_index", Index()),
        (["--run-eval", "task"], "run_eval_task", {"ok": True}),
        (["--run-eval-suite"], "run_eval_suite", {"ok": True}),
    ]
    for flags, target, result in routes:
        monkeypatch.setattr(cli, target, lambda *args, _result=result, **kwargs: _result)
        monkeypatch.setattr(
            sys,
            "argv",
            ["minicodex", "--root", str(tmp_path), "--provider", "stub", "--dry-run", *flags],
        )
        cli.main()
        assert capsys.readouterr().out.strip()


def test_cli_interactive_and_config_error_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "run_interactive_session", lambda config: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["minicodex", "--root", str(tmp_path), "--provider", "stub", "--interactive"],
    )
    cli.main()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minicodex",
            "--root",
            str(tmp_path),
            "--provider",
            "stub",
            "--interactive",
            "--non-interactive",
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1

    monkeypatch.setattr(cli, "apply_project_config", lambda *args, **kwargs: 1 / 0)
    monkeypatch.setattr(
        sys,
        "argv",
        ["minicodex", "--root", str(tmp_path), "--provider", "stub", "--dev-panel"],
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1
    assert capsys.readouterr().out


def test_cli_api_key_failure_and_post_run_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli, "require_api_key", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("key"))
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["minicodex", "goal", "--root", str(tmp_path), "--provider", "stub"],
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1

    class Agent:
        def __init__(self, config: AgentConfig) -> None:
            self.config = config

        def run(self, goal: str) -> RunResult:
            return RunResult(ExitCode.SUCCESS, "success")

    monkeypatch.setattr(cli, "require_api_key", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "MiniCodexAgent", Agent)
    monkeypatch.setattr(cli, "create_review_bundle", lambda *args, **kwargs: "review")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minicodex",
            "goal",
            "--root",
            str(tmp_path),
            "--provider",
            "stub",
            "--review-after-run",
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 0
    assert "review" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("handler", "dependency", "args"),
    [
        ("handle_search_code", "search_code", {"query": "needle"}),
        ("handle_build_dependency_graph", "build_dependency_graph", {}),
        ("handle_inspect_python_ast", "inspect_python_ast", {"path": "demo.py"}),
        ("handle_find_python_symbol", "find_python_symbol", {"symbol": "demo"}),
        ("handle_ast_patch_capability_report", "ast_patch_capability_report", {}),
        ("handle_plan_semantic_edit", "plan_semantic_edit", {"operation": "rename"}),
        ("handle_detect_dead_code", "detect_dead_code", {}),
    ],
)
def test_python_read_handlers_forward_to_implementations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    handler: str,
    dependency: str,
    args: dict[str, Any],
) -> None:
    monkeypatch.setattr(python_tools, dependency, lambda *call_args, **kwargs: "ok")

    assert getattr(python_tools, handler)(_ctx(tmp_path), args) == "ok"


def test_python_write_handlers_cover_preview_and_snapshot_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for dependency in (
        "rename_python_symbol",
        "rename_symbol_semantic",
        "organize_imports",
        "cleanup_dead_code",
        "format_and_verify",
    ):
        monkeypatch.setattr(python_tools, dependency, lambda *args, **kwargs: "changed")

    preview_ctx = _ctx(tmp_path)
    assert (
        python_tools.handle_rename_python_symbol(
            preview_ctx,
            {"old_name": "old", "new_name": "new", "preview_only": True},
        )
        == "changed"
    )
    assert (
        python_tools.handle_rename_symbol_semantic(
            preview_ctx,
            {"old_name": "old", "new_name": "new", "preview_only": True},
        )
        == "changed"
    )
    assert python_tools.handle_organize_imports(preview_ctx, {"preview_only": True}) == "changed"
    assert (
        python_tools.handle_cleanup_dead_code(
            preview_ctx, {"preview_only": True, "names": ["unused"]}
        )
        == "changed"
    )
    assert (
        python_tools.handle_format_and_verify(
            preview_ctx, {"path": "demo.py", "run_formatter": False}
        )
        == "changed"
    )

    write_ctx = _ctx(tmp_path, dry_run=False)
    assert python_tools.handle_rename_python_symbol(
        write_ctx,
        {"old_name": "old", "new_name": "new", "preview_only": False},
    ).startswith("snapshot")
    assert python_tools.handle_rename_symbol_semantic(
        write_ctx,
        {"old_name": "old", "new_name": "new", "preview_only": False},
    ).startswith("snapshot")
    assert python_tools.handle_organize_imports(write_ctx, {"preview_only": False}).startswith(
        "snapshot"
    )
    assert python_tools.handle_cleanup_dead_code(
        write_ctx, {"preview_only": False, "names": ["unused"]}
    ).startswith("snapshot")
    assert python_tools.handle_format_and_verify(
        write_ctx, {"path": "demo.py", "run_formatter": True}
    ).startswith("snapshot")


def test_python_write_handlers_cover_rejection_and_snapshot_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(python_tools, "rename_python_symbol", lambda *args, **kwargs: "unused")
    rejected = python_tools.handle_rename_python_symbol(
        _ctx(tmp_path, dry_run=False, confirm=False),
        {"old_name": "old", "new_name": "new", "preview_only": False},
    )
    assert "reddetti" in rejected

    failed_snapshot = python_tools.handle_rename_python_symbol(
        _ctx(tmp_path, dry_run=False, snapshot=(False, "snapshot failed")),
        {"old_name": "old", "new_name": "new", "preview_only": False},
    )
    assert failed_snapshot == "snapshot failed"


@pytest.mark.parametrize(
    ("handler", "dependency", "args"),
    [
        ("handle_prepare_github_issue", "prepare_github_issue", {"title": "t", "body": "b"}),
        ("handle_detect_github_workflows", "detect_github_workflows", {}),
        ("handle_init_github_action", "init_github_action", {}),
        (
            "handle_parse_pr_comment_command",
            "parse_pr_comment_command",
            {"comment": "/minicodex test"},
        ),
        ("handle_prepare_commit_push_plan", "prepare_commit_push_plan", {}),
        ("handle_summarize_github_ci_log", "summarize_github_ci_log", {}),
        ("handle_github_ci_fetch_preview", "github_ci_fetch_preview", {}),
        ("handle_generate_github_app_manifest", "generate_github_app_manifest", {}),
        ("handle_init_github_webhook_server", "init_github_webhook_server", {}),
        ("handle_fetch_github_ci_log", "github_ci_fetch_preview", {"dry_run": True}),
        ("handle_execute_commit_push_workflow", "execute_commit_push_workflow", {}),
        ("handle_resolve_review_comments", "resolve_review_comments", {}),
        (
            "handle_prepare_github_artifact_upload",
            "prepare_github_artifact_upload",
            {"paths": ["dist/pkg.whl"]},
        ),
    ],
)
def test_github_handlers_cover_offline_routes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    handler: str,
    dependency: str,
    args: dict[str, Any],
) -> None:
    monkeypatch.setattr(github_tools, dependency, lambda *call_args, **kwargs: "ok")

    assert getattr(github_tools, handler)(_ctx(tmp_path), args) == "ok"


def test_github_api_handlers_cover_dry_run_blocks_and_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        github_tools, "render_github_api_preview", lambda *args, **kwargs: "preview"
    )
    monkeypatch.setattr(
        github_tools, "_scan_secrets_before_pr_if_enabled", lambda ctx: "SECRET SCAN: passed\n"
    )
    dry_ctx = _ctx(tmp_path)

    assert "DRY RUN" in github_tools.handle_create_github_issue(
        dry_ctx, {"title": "t", "body": "b"}
    )
    assert "DRY RUN" in github_tools.handle_create_github_pr(dry_ctx, {"title": "t", "body": "b"})
    assert "DRY RUN" in github_tools.handle_create_github_review_comment(
        dry_ctx, {"pull_number": 1, "body": "review"}
    )

    blocked_ctx = replace(dry_ctx, config=replace(dry_ctx.config, dry_run=False))
    assert "writes are disabled" in github_tools.handle_create_github_issue(
        blocked_ctx, {"title": "t", "body": "b"}
    )
    assert "writes are disabled" in github_tools.handle_create_github_pr(
        blocked_ctx, {"title": "t", "body": "b"}
    )
    assert "require --allow-github-api-writes" in github_tools.handle_create_github_review_comment(
        blocked_ctx, {"pull_number": 1, "body": "review"}
    )

    result = GitHubApiResult(
        ok=True,
        status=201,
        data={"html_url": "https://example.test/item/1"},
        message="created",
    )
    monkeypatch.setattr(github_tools, "create_github_issue_api", lambda *args, **kwargs: result)
    monkeypatch.setattr(github_tools, "create_github_pr_api", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        github_tools, "create_github_review_comment_api", lambda *args, **kwargs: result
    )
    write_ctx = _ctx(tmp_path, dry_run=False, allow_writes=True)

    assert "created successfully" in github_tools.handle_create_github_issue(
        write_ctx, {"title": "t", "body": "b"}
    )
    assert "created successfully" in github_tools.handle_create_github_pr(
        write_ctx, {"title": "t", "body": "b"}
    )
    assert "created successfully" in github_tools.handle_create_github_review_comment(
        write_ctx, {"pull_number": 1, "body": "review"}
    )


def test_github_api_handlers_render_integration_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_preview(*args: Any, **kwargs: Any) -> str:
        raise GitHubIntegrationError("bad repository")

    monkeypatch.setattr(github_tools, "render_github_api_preview", fail_preview)
    assert github_tools.handle_create_github_issue(
        _ctx(tmp_path), {"title": "t", "body": "b"}
    ).startswith("GITHUB API BLOCK:")
    assert github_tools.handle_create_github_pr(
        _ctx(tmp_path), {"title": "t", "body": "b"}
    ).startswith("GITHUB API BLOCK:")


def test_eval_handlers_cover_listing_reading_and_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Task:
        files = {"app.py": "print('x')"}

        def to_dict(self) -> dict[str, Any]:
            return {"files": dict(self.files)}

    monkeypatch.setattr(
        eval_tools,
        "list_eval_tasks",
        lambda root: [{"category": "core", "tags": ["fast"]}, {"category": "other", "tags": []}],
    )
    monkeypatch.setattr(
        eval_tools,
        "list_eval_baselines",
        lambda root: [{"tags": ["fast"]}, {"tags": []}],
    )
    monkeypatch.setattr(eval_tools, "load_eval_task", lambda root, task_id: Task())
    monkeypatch.setattr(eval_tools, "list_eval_runs", lambda root, limit: [{"id": "run"}])
    monkeypatch.setattr(eval_tools, "read_eval_run", lambda *args, **kwargs: "run")
    monkeypatch.setattr(eval_tools, "run_eval_task", lambda *args, **kwargs: {"task": True})
    monkeypatch.setattr(eval_tools, "run_eval_suite", lambda *args, **kwargs: {"suite": True})
    monkeypatch.setattr(
        eval_tools, "run_prompt_ab_comparison", lambda *args, **kwargs: {"comparison": True}
    )
    monkeypatch.setattr(eval_tools, "compare_eval_runs", lambda *args, **kwargs: {"delta": 1})

    ctx = _ctx(tmp_path)
    assert "Found 1 eval task" in eval_tools.handle_list_eval_tasks(
        ctx, {"category": "core", "tag": "fast"}
    )
    assert "Found 1 eval baseline" in eval_tools.handle_list_eval_baselines(ctx, {"tag": "fast"})
    assert "chars" in eval_tools.handle_read_eval_task(
        ctx, {"task_id": "task", "include_files": False}
    )
    assert "print" in eval_tools.handle_read_eval_task(
        ctx, {"task_id": "task", "include_files": True}
    )
    assert "task" in eval_tools.handle_run_eval_task(ctx, {"task_id": "task"})
    assert "suite" in eval_tools.handle_run_eval_suite(ctx, {"task_ids": ["task"]})
    assert "Found 1 eval run" in eval_tools.handle_list_eval_runs(ctx, {})
    assert eval_tools.handle_read_eval_run(ctx, {"run_id": "run"}) == "run"
    assert "comparison" in eval_tools.handle_run_prompt_ab_comparison(
        ctx, {"task_ids": ["task"], "prompt_profiles": ["auto"]}
    )
    assert "delta" in eval_tools.handle_compare_eval_runs(
        ctx, {"baseline_run_id": "a", "candidate_run_id": "b"}
    )

    reject_ctx = _ctx(tmp_path, dry_run=False, confirm=False)
    assert "rejected" in eval_tools.handle_run_eval_task(reject_ctx, {"task_id": "task"})
    assert "rejected" in eval_tools.handle_run_eval_suite(reject_ctx, {})
    assert "rejected" in eval_tools.handle_run_prompt_ab_comparison(reject_ctx, {})


def test_language_handlers_cover_semantic_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Report:
        def to_dict(self) -> dict[str, Any]:
            return {"frameworks": ["pytest"]}

        def summary(self) -> str:
            return "language summary"

    class SemanticReport:
        def to_dict(self) -> dict[str, bool]:
            return {"available": True}

    class Index:
        def to_dict(self) -> dict[str, bool]:
            return {"built": True}

    monkeypatch.setattr(language_tools, "analyze_language_stack", lambda *args, **kwargs: Report())
    monkeypatch.setattr(
        language_tools, "suggest_verification_commands", lambda *args, **kwargs: {"commands": []}
    )
    monkeypatch.setattr(language_tools, "semantic_capability_report", lambda: SemanticReport())
    monkeypatch.setattr(language_tools, "build_semantic_index", lambda *args, **kwargs: Index())
    monkeypatch.setattr(
        language_tools, "find_symbol_references", lambda *args, **kwargs: {"matches": []}
    )
    monkeypatch.setattr(language_tools, "inspect_routes", lambda *args, **kwargs: {"routes": []})

    ctx = _ctx(tmp_path)
    assert "Language/framework" in language_tools.handle_detect_language_stack(ctx, {})
    assert "framework" in language_tools.handle_inspect_frameworks(ctx, {})
    assert "commands" in language_tools.handle_suggest_verification_commands(ctx, {})
    assert "language summary" in language_tools.handle_language_adapter_report(ctx, {})
    assert "available" in language_tools.handle_semantic_capability_report(ctx, {})
    assert "built" in language_tools.handle_build_semantic_index(ctx, {"include_routes": "invalid"})
    assert "matches" in language_tools.handle_find_symbol_references(ctx, {"symbol": "target"})
    assert "routes" in language_tools.handle_inspect_routes(ctx, {})


def test_shell_testing_and_ux_handlers_cover_boundary_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shell_handlers, "run_checked_command", lambda *args, **kwargs: "checked")
    monkeypatch.setattr(shell_handlers, "run_terminal_session", lambda *args, **kwargs: "session")
    monkeypatch.setattr(
        shell_handlers, "list_terminal_sessions", lambda *args, **kwargs: "sessions"
    )
    ctx = _ctx(tmp_path)
    assert shell_handlers.handle_run_command(ctx, {"command": "python -V"}) == "checked"
    assert shell_handlers.handle_run_tests(ctx, {"command": "pytest -q"}) == "checked"
    assert shell_handlers.handle_run_terminal_session(ctx, {"commands": ["pytest -q"]}) == "session"
    assert "liste" in shell_handlers.handle_run_terminal_session(ctx, {"commands": "bad"})
    assert shell_handlers.handle_list_terminal_sessions(ctx, {}) == "sessions"

    class Classification:
        summary = "failure"

        def to_dict(self) -> dict[str, bool]:
            return {"failed": True}

    monkeypatch.setattr(
        testing_tools, "classify_failure_output", lambda *args, **kwargs: Classification()
    )
    monkeypatch.setattr(testing_tools, "summarize_ci_log", lambda *args, **kwargs: {"ci": True})
    monkeypatch.setattr(
        testing_tools, "detect_flaky_tests", lambda *args, **kwargs: {"flaky": True}
    )
    assert "failure" in testing_tools.handle_classify_test_failure(ctx, {"output": "failed"})
    assert "ci" in testing_tools.handle_summarize_ci_log(ctx, {"output": "failed"})
    assert "flaky" in testing_tools.handle_detect_flaky_tests(
        ctx, {"output": "failed", "prior_outputs": "invalid"}
    )

    for dependency in (
        "render_tui_panel",
        "create_review_bundle",
        "list_review_bundles",
        "read_review_bundle",
        "record_review_decision",
        "render_run_summary",
        "export_ide_bridge",
    ):
        monkeypatch.setattr(ux_tools, dependency, lambda *args, **kwargs: "ok")
    assert ux_tools.handle_render_tui_panel(ctx, {}) == "ok"
    assert ux_tools.handle_create_review_bundle(ctx, {}) == "ok"
    assert ux_tools.handle_list_review_bundles(ctx, {}) == "ok"
    assert ux_tools.handle_read_review_bundle(ctx, {}) == "ok"
    assert (
        ux_tools.handle_record_review_decision(ctx, {"bundle_id": "b", "decision": "approve"})
        == "ok"
    )
    assert ux_tools.handle_run_summary(ctx, {}) == "ok"
    assert ux_tools.handle_export_ide_bridge(ctx, {}) == "ok"

    rejected = _ctx(tmp_path, dry_run=False, confirm=False)
    assert "reddetti" in ux_tools.handle_create_review_bundle(rejected, {})
    assert "reddetti" in ux_tools.handle_export_ide_bridge(rejected, {})


def test_shell_handlers_cover_command_discovery_and_project_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(shell_handlers, "choose_test_command", lambda *args: "")
    assert "otomatik" in shell_handlers.handle_run_tests(ctx, {})

    monkeypatch.setattr(shell_handlers, "choose_test_command", lambda *args: "pytest -q")
    monkeypatch.setattr(shell_handlers, "run_checked_command", lambda *args, **kwargs: "checked")
    assert shell_handlers.handle_run_tests(ctx, {}) == "checked"

    allowed = SimpleNamespace(
        allowed=True,
        requires_manual_approval=False,
        requires_extra_approval=True,
        render=lambda: "extra approval",
    )
    monkeypatch.setattr(shell_handlers, "assess_command_safety", lambda *args, **kwargs: allowed)
    monkeypatch.setattr(shell_handlers, "read_effective_project_policy", lambda *args: object())
    monkeypatch.setattr(shell_handlers, "evaluate_command", lambda *args: allowed)
    monkeypatch.setattr(shell_handlers, "run_terminal_session", lambda *args, **kwargs: "session")
    policy_ctx = replace(ctx, config=replace(ctx.config, project_policy_enabled=True))
    assert (
        shell_handlers.handle_run_terminal_session(policy_ctx, {"commands": ["pytest -q"]})
        == "session"
    )

    blocked = SimpleNamespace(
        allowed=False,
        requires_manual_approval=False,
        requires_extra_approval=False,
        render=lambda: "blocked",
    )
    monkeypatch.setattr(shell_handlers, "evaluate_command", lambda *args: blocked)
    assert shell_handlers.handle_run_terminal_session(
        policy_ctx, {"commands": ["pytest -q"]}
    ).startswith("POLICY BLOCK:")


def test_security_external_scanner_boundary_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert "Invalid minimum_severity" in security_tools.handle_scan_secrets(
        _ctx(tmp_path), {"minimum_severity": "invalid"}
    )
    monkeypatch.setattr(security_tools, "scan_secrets", lambda *args, **kwargs: "scan")
    assert security_tools.handle_scan_secrets(_ctx(tmp_path), {}) == "scan"
    assert security_tools._external_secret_command("trufflehog", ".")[0] == "trufflehog"
    with pytest.raises(ValueError):
        security_tools._external_secret_command("unknown", ".")

    monkeypatch.setattr(security_tools.shutil, "which", lambda tool: None)
    assert "not available" in security_tools.handle_run_external_secret_scan(_ctx(tmp_path), {})

    monkeypatch.setattr(security_tools.shutil, "which", lambda tool: tool)
    assert "DRY-RUN" in security_tools.handle_run_external_secret_scan(
        _ctx(tmp_path), {"tool": "gitleaks"}
    )

    live_ctx = _ctx(tmp_path, dry_run=False)
    timeout = subprocess.TimeoutExpired(
        ["gitleaks"],
        2,
        output=b"partial stdout",
        stderr=b"partial stderr",
    )
    monkeypatch.setattr(
        security_tools.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(timeout),
    )
    timed_out = security_tools.handle_run_external_secret_scan(
        live_ctx, {"tool": "gitleaks", "timeout": 2}
    )
    assert "timed out" in timed_out
    assert "partial stdout" in timed_out

    monkeypatch.setattr(
        security_tools.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing executable")),
    )
    assert "failed to start" in security_tools.handle_run_external_secret_scan(
        live_ctx, {"tool": "gitleaks"}
    )

    monkeypatch.setattr(
        security_tools.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="findings", stderr="warning"
        ),
    )
    output = security_tools.handle_run_external_secret_scan(live_ctx, {"tool": "gitleaks"})
    assert "Exit code: 1" in output
    assert "findings" in output

    assert "Invalid scanner" in security_tools.handle_run_sast_scan(
        live_ctx, {"scanner": "invalid"}
    )
    assert "Invalid minimum_severity" in security_tools.handle_run_sast_scan(
        live_ctx, {"scanner": "builtin", "minimum_severity": "invalid"}
    )


def test_small_tool_modules_cover_all_handler_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path)

    for dependency in ("render_skill_catalog", "read_skill", "validate_skills", "init_skill"):
        monkeypatch.setattr(skill_tools, dependency, lambda *args, **kwargs: "ok")
    assert skill_tools.handle_list_skills(ctx, {}) == "ok"
    assert skill_tools.handle_read_skill(ctx, {"name": "demo"}) == "ok"
    assert skill_tools.handle_validate_skills(ctx, {}) == "ok"
    assert skill_tools.handle_init_skill(ctx, {"name": "demo"}) == "ok"
    assert "reddetti" in skill_tools.handle_init_skill(
        _ctx(tmp_path, dry_run=False, confirm=False), {"name": "demo"}
    )

    for dependency in (
        "create_long_task",
        "list_long_tasks",
        "read_long_task",
        "resume_long_task",
        "update_acceptance_criteria",
        "create_checkpoint",
    ):
        monkeypatch.setattr(long_horizon_tools, dependency, lambda *args, **kwargs: "ok")
    assert long_horizon_tools.handle_create_long_task(ctx, {}) == "ok"
    assert long_horizon_tools.handle_list_long_tasks(ctx, {}) == "ok"
    assert long_horizon_tools.handle_read_long_task(ctx, {"run_id": "run"}) == "ok"
    assert long_horizon_tools.handle_resume_long_task(ctx, {"run_id": "run"}) == "ok"
    assert long_horizon_tools.handle_update_acceptance_criteria(ctx, {"run_id": "run"}) == "ok"
    assert long_horizon_tools.handle_create_checkpoint(ctx, {"run_id": "run"}) == "ok"

    telemetry_results = {
        "list_telemetry_runs": [],
        "read_telemetry_run": "read",
        "summarize_telemetry": "summary",
        "compare_telemetry_runs": "compare",
        "export_telemetry_bundle": "bundle",
        "list_model_prices": [],
        "render_optimization_dashboard": "dashboard",
        "build_failure_taxonomy_dashboard": {"failures": []},
    }
    for dependency, result in telemetry_results.items():
        monkeypatch.setattr(
            telemetry_tools,
            dependency,
            lambda *args, _result=result, **kwargs: _result,
        )
    assert "Telemetry runs" in telemetry_tools.handle_list_telemetry_runs(ctx, {})
    assert telemetry_tools.handle_read_telemetry_run(ctx, {"run_id": "run"}) == "read"
    assert telemetry_tools.handle_telemetry_summary(ctx, {}) == "summary"
    assert telemetry_tools.handle_compare_telemetry_runs(ctx, {}) == "compare"
    assert telemetry_tools.handle_export_telemetry_bundle(ctx, {}) == "bundle"
    assert "prices" in telemetry_tools.handle_list_model_prices(ctx, {})
    assert telemetry_tools.handle_optimization_dashboard(ctx, {}) == "dashboard"
    assert "failures" in telemetry_tools.handle_failure_dashboard(ctx, {})

    assert "liste" in control_tools.handle_update_plan(ctx, {"steps": "invalid"})
    assert "Plan" in control_tools.handle_update_plan(ctx, {"steps": ["inspect", "test"]})
    non_interactive = replace(
        ctx,
        config=replace(ctx.config, non_interactive=True, default_answer="continue"),
    )
    assert "continue" in control_tools.handle_ask_user(non_interactive, {"question": "Proceed?"})
    assert '"status": "done"' in control_tools.handle_finish(ctx, {"status": "done"})

    monkeypatch.setattr(
        diagnostic_tools, "analyze_failure_output", lambda *args, **kwargs: "analysis"
    )
    monkeypatch.setattr(
        diagnostic_tools, "diagnose_patch_failure", lambda *args, **kwargs: "diagnosis"
    )
    assert diagnostic_tools.handle_analyze_failure(ctx, {"output": "failed"}) == "analysis"
    assert diagnostic_tools.handle_diagnose_patch_failure(ctx, {}) == "diagnosis"

    quality_results = {
        "final_readiness_report": "ready",
        "build_test_matrix_plan": {"plan": True},
        "release_package_manifest": "manifest",
        "clean_generated_artifacts": {"clean": True},
    }
    for dependency, result in quality_results.items():
        monkeypatch.setattr(
            quality_tools,
            dependency,
            lambda *args, _result=result, **kwargs: _result,
        )
    assert quality_tools.handle_final_readiness_report(ctx, {}) == "ready"
    assert "TEST_MATRIX_PLAN_JSON" in quality_tools.handle_test_matrix_plan(ctx, {})
    assert quality_tools.handle_release_package_manifest(ctx, {}) == "manifest"
    assert "clean" in quality_tools.handle_clean_generated_artifacts(ctx, {})
