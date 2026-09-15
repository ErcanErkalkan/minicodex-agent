from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.eval_runner import (
    built_in_eval_baselines,
    built_in_eval_tasks,
    compare_eval_baselines,
    eval_baseline_plan,
    init_eval_baselines,
    init_eval_suite,
    list_eval_baselines,
    list_eval_tasks,
    load_eval_baseline,
)
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS, check_tool_access
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class _Logger:
    def log_event(self, *_args, **_kwargs):
        pass

    def write_metadata(self, *_args, **_kwargs):
        pass

    def write_final(self, *_args, **_kwargs):
        pass


def _ctx(root: Path, *, dry_run: bool = False) -> ToolContext:
    config = AgentConfig(
        root=root,
        model="stub",
        provider="stub",
        approval="auto",
        dry_run=dry_run,
        log_enabled=False,
        project_config_enabled=False,
        model_call_budget=3,
        eval_default_max_steps=1,
        eval_model_call_budget=1,
    )
    state = AgentState(goal="eval", project_profile=detect_project(root))
    return ToolContext(
        config=config,
        state=state,
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_builtin_eval_suite_is_expanded_and_mixed_language(tmp_path: Path) -> None:
    result = init_eval_suite(tmp_path)
    assert result["ok"] is True
    tasks = list_eval_tasks(tmp_path)
    ids = {task["id"] for task in tasks}
    assert len(tasks) >= 10
    assert {
        "eval-harness-smoke-noop",
        "python-security-shell-true",
        "typescript-bugfix-return-value",
        "java-service-null-guard",
        "go-error-handling",
        "rust-off-by-one",
        "malicious-instruction-defense",
    }.issubset(ids)
    categories = {task["category"] for task in tasks}
    assert {"bugfix", "security", "frontend", "ci-repair"}.issubset(categories)


def test_eval_baseline_manifests_are_created_and_listed(tmp_path: Path) -> None:
    result = init_eval_baselines(tmp_path)
    assert result["ok"] is True
    baselines = list_eval_baselines(tmp_path)
    ids = {baseline["id"] for baseline in baselines}
    assert {
        "stub-smoke",
        "openai-codex-core",
        "ollama-qwen-coder-core",
        "full-regression-reference",
    }.issubset(ids)
    loaded = load_eval_baseline(tmp_path, "ollama-qwen-coder-core")
    assert loaded.provider == "ollama"
    assert loaded.extra_args["model_base_url"].startswith("http://localhost")


def test_eval_baseline_plan_renders_reproducible_commands(tmp_path: Path) -> None:
    init_eval_suite(tmp_path)
    init_eval_baselines(tmp_path)
    plan = eval_baseline_plan(tmp_path, "stub-smoke", run_id="smoke-run")
    assert plan["ok"] is True
    assert plan["baseline"]["provider"] == "stub"
    assert "--run-eval-suite" in plan["commands"]["run_suite"]
    assert "--eval-run-id smoke-run" in plan["commands"]["run_suite"]
    assert plan["task_ids"] == ["eval-harness-smoke-noop"]


def test_compare_eval_baselines_marks_regressions(tmp_path: Path) -> None:
    reports = tmp_path / ".minicodex" / "evals" / "reports"
    reports.mkdir(parents=True)
    (reports / "base.json").write_text(
        json.dumps(
            {
                "average_score": 1.0,
                "task_results": [
                    {"task_id": "a", "score": {"score": 1.0, "success": True}},
                    {"task_id": "b", "score": {"score": 0.8, "success": True}},
                ],
            }
        ),
        encoding="utf-8",
    )
    (reports / "cand.json").write_text(
        json.dumps(
            {
                "average_score": 0.8,
                "task_results": [
                    {"task_id": "a", "score": {"score": 0.5, "success": False}},
                    {"task_id": "b", "score": {"score": 1.0, "success": True}},
                ],
            }
        ),
        encoding="utf-8",
    )
    comparison = compare_eval_baselines(tmp_path, "base", "cand")
    assert comparison["passed_threshold"] is False
    assert comparison["regression_count"] == 1
    assert comparison["improvement_count"] == 1


def test_eval_baseline_tools_are_registered_and_dispatch(tmp_path: Path) -> None:
    registry = get_tool_registry()
    for action in [
        "init_eval_baselines",
        "list_eval_baselines",
        "eval_baseline_plan",
        "compare_eval_baselines",
    ]:
        assert action in ACTION_SPECS
        assert action in registry
    validate_action(
        {"thought": "x", "action": "eval_baseline_plan", "args": {"baseline_id": "stub-smoke"}}
    )

    ctx = _ctx(tmp_path)
    data = json.loads(dispatch_tool(ctx, "init_eval_baselines", {}))
    assert data["ok"] is True
    listed = json.loads(dispatch_tool(ctx, "list_eval_baselines", {}))
    assert any(item["id"] == "stub-smoke" for item in listed["baselines"])
    plan = json.loads(dispatch_tool(ctx, "eval_baseline_plan", {"baseline_id": "stub-smoke"}))
    assert plan["baseline"]["id"] == "stub-smoke"


def test_eval_plugin_exposes_baseline_tools(tmp_path: Path) -> None:
    plugins = {plugin.name: plugin for plugin in BUILTIN_PLUGINS}
    assert "evals" in plugins
    for tool in [
        "init_eval_baselines",
        "list_eval_baselines",
        "eval_baseline_plan",
        "compare_eval_baselines",
    ]:
        assert tool in plugins["evals"].tools
        assert check_tool_access(tmp_path, tool, configured_plugins=("evals",)).allowed


def test_builtin_baselines_reference_existing_builtin_tasks() -> None:
    task_ids = {task.id for task in built_in_eval_tasks()}
    assert task_ids
    for baseline in built_in_eval_baselines():
        assert set(baseline.task_ids).issubset(task_ids)
