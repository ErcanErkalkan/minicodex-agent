from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.eval_runner import (
    built_in_eval_baselines,
    eval_baseline_plan,
    eval_coverage_report,
    init_eval_baselines,
    init_eval_suite,
    list_eval_tasks,
)
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS
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


def _ctx(root: Path) -> ToolContext:
    config = AgentConfig(
        root=root,
        provider="stub",
        model="stub",
        approval="auto",
        log_enabled=False,
        project_config_enabled=False,
    )
    return ToolContext(
        config=config,
        state=AgentState(goal="eval coverage", project_profile=detect_project(root)),
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_codex_claim_eval_categories_are_covered() -> None:
    report = eval_coverage_report()
    assert report["ok"] is True
    assert report["task_count"] >= 20
    assert report["hard_task_count"] >= 10
    assert report["missing_categories"] == []
    for label in [
        "multi-file Python bugfix",
        "TypeScript/React refactor",
        "Java/Maven test fix",
        "security patch",
        "dependency upgrade",
        "CI log repair",
        "large diff review",
        "malicious repo instruction defense",
        "long-horizon task",
        "multi-agent task",
    ]:
        assert report["required_category_coverage"][label]["covered"] is True
        assert report["required_category_coverage"][label]["task_ids"]


def test_real_model_baseline_plans_cover_required_models() -> None:
    report = eval_coverage_report()
    assert report["missing_baseline_models"] == []
    for label in ["gpt-5.3-codex", "gpt-5.5", "ollama qwen coder", "lmstudio local model"]:
        assert report["baseline_model_coverage"][label]["covered"] is True

    ids = {baseline.id for baseline in built_in_eval_baselines()}
    assert {
        "openai-codex-claim-suite",
        "openai-gpt-5-5-claim-suite",
        "ollama-qwen-coder-claim-suite",
        "lmstudio-local-claim-suite",
    }.issubset(ids)


def test_eval_suite_initializes_harder_benchmark_tasks(tmp_path: Path) -> None:
    result = init_eval_suite(tmp_path)
    assert result["ok"] is True
    tasks = list_eval_tasks(tmp_path)
    ids = {task["id"] for task in tasks}
    assert {
        "python-multifile-user-service-bugfix",
        "typescript-react-prop-refactor",
        "java-maven-validator-test-fix",
        "security-path-traversal-patch",
        "dependency-upgrade-python-requests",
        "large-diff-review-risk-summary",
        "long-horizon-reporting-pipeline",
        "multi-agent-api-storage-contract",
    }.issubset(ids)


def test_claim_baseline_plan_includes_protocol_and_full_task_set(tmp_path: Path) -> None:
    init_eval_suite(tmp_path)
    init_eval_baselines(tmp_path)
    plan = eval_baseline_plan(tmp_path, "ollama-qwen-coder-claim-suite", run_id="local-claim")
    assert plan["ok"] is True
    assert "--model-action-protocol auto" in plan["commands"]["run_suite"]
    assert "--prompt-profile local-model" in plan["commands"]["run_suite"]
    assert "python-multifile-user-service-bugfix" in plan["task_ids"]
    assert "multi-agent-api-storage-contract" in plan["task_ids"]


def test_eval_coverage_tool_is_registered_and_dispatches(tmp_path: Path) -> None:
    registry = get_tool_registry()
    assert "eval_coverage_report" in ACTION_SPECS
    assert "eval_coverage_report" in registry
    validate_action({"thought": "x", "action": "eval_coverage_report", "args": {}})
    plugins = {plugin.name: plugin for plugin in BUILTIN_PLUGINS}
    assert "eval_coverage_report" in plugins["evals"].tools

    data = json.loads(dispatch_tool(_ctx(tmp_path), "eval_coverage_report", {}))
    assert data["ok"] is True
    assert data["missing_categories"] == []
