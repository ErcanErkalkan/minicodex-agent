from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.eval_runner import (
    compare_eval_runs,
    init_eval_suite,
    list_eval_tasks,
    load_eval_task,
    run_eval_task,
    score_eval_result,
)
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS, check_tool_access
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_settings import (
    init_project_config,
    read_project_config,
    update_project_config,
)
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


def test_eval_actions_are_registered() -> None:
    registry = get_tool_registry()
    for action in [
        "init_eval_suite",
        "list_eval_tasks",
        "read_eval_task",
        "run_eval_task",
        "run_eval_suite",
        "list_eval_runs",
        "read_eval_run",
        "compare_eval_runs",
    ]:
        assert action in ACTION_SPECS
        assert action in registry
    validate_action({"thought": "x", "action": "run_eval_task", "args": {"task_id": "demo"}})


def test_init_and_list_builtin_eval_tasks(tmp_path: Path) -> None:
    result = init_eval_suite(tmp_path)
    assert result["ok"] is True
    tasks = list_eval_tasks(tmp_path)
    ids = {task["id"] for task in tasks}
    assert {"python-bugfix-arithmetic", "docs-sync-readme"}.issubset(ids)
    loaded = load_eval_task(tmp_path, "python-bugfix-arithmetic")
    assert "pytest" in loaded.tags
    assert "src/calc.py" in loaded.files


def test_score_eval_result_checks_files_and_commands(tmp_path: Path) -> None:
    init_eval_suite(tmp_path)
    task = load_eval_task(tmp_path, "python-bugfix-arithmetic")
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    original = {"src/calc.py": "def add(a, b):\n    return a - b\n"}
    score = score_eval_result(
        task=task,
        workspace=workspace,
        original_files=original,
        verification_results=[],
        agent_exit_code=0,
    )
    assert score.success is True
    assert score.score == 1.0


def test_run_eval_task_with_stub_writes_report(tmp_path: Path) -> None:
    task_dir = tmp_path / ".minicodex" / "evals" / "tasks"
    task_dir.mkdir(parents=True)
    (task_dir / "smoke.json").write_text(
        json.dumps(
            {
                "id": "smoke",
                "title": "Smoke eval",
                "goal": "Finish immediately.",
                "files": {"README.md": "# Demo\n"},
                "expected": {},
                "verification_commands": [],
            }
        ),
        encoding="utf-8",
    )
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        log_enabled=False,
        max_steps=1,
    )
    report = run_eval_task(tmp_path, config, "smoke", run_id="r1", max_steps=1, model_call_budget=1)
    assert report["ok"] is True
    assert report["score"]["success"] is True
    assert (tmp_path / ".minicodex" / "evals" / "runs" / "r1" / "smoke" / "report.json").exists()
    assert report["agent"]["usage"]["calls"] == 0


def test_eval_tools_dispatch_and_dry_run(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, dry_run=True)
    out = dispatch_tool(ctx, "init_eval_suite", {})
    data = json.loads(out)
    assert data["dry_run"] is True
    assert not (tmp_path / ".minicodex" / "evals").exists()

    ctx = _ctx(tmp_path)
    dispatch_tool(ctx, "init_eval_suite", {})
    listed = json.loads(dispatch_tool(ctx, "list_eval_tasks", {}))
    assert listed["tasks"]
    read = dispatch_tool(ctx, "read_eval_task", {"task_id": "docs-sync-readme"})
    assert "docs-sync-readme" in read


def test_compare_eval_runs_reports_score_delta(tmp_path: Path) -> None:
    reports = tmp_path / ".minicodex" / "evals" / "reports"
    reports.mkdir(parents=True)
    (reports / "base.json").write_text(
        json.dumps(
            {
                "average_score": 0.5,
                "task_results": [{"task_id": "a", "score": {"score": 0.5, "success": False}}],
            }
        ),
        encoding="utf-8",
    )
    (reports / "cand.json").write_text(
        json.dumps(
            {
                "average_score": 1.0,
                "task_results": [{"task_id": "a", "score": {"score": 1.0, "success": True}}],
            }
        ),
        encoding="utf-8",
    )
    comparison = compare_eval_runs(tmp_path, "base", "cand")
    assert comparison["average_score_delta"] == 0.5
    assert comparison["task_deltas"][0]["delta"] == 0.5


def test_eval_plugin_and_project_config(tmp_path: Path) -> None:
    plugins = {plugin.name: plugin for plugin in BUILTIN_PLUGINS}
    assert "evals" in plugins
    assert check_tool_access(tmp_path, "list_eval_tasks", configured_plugins=("evals",)).allowed

    init_project_config(tmp_path)
    cfg = read_project_config(tmp_path)
    assert cfg["eval_default_max_steps"] == 8
    update_project_config(tmp_path, {"eval_default_max_steps": 0, "eval_report_max_chars": 999})
    applied = apply_project_config(
        AgentConfig(root=tmp_path, model="stub", provider="stub"), explicit_options=set()
    )
    assert applied.eval_default_max_steps == 1
    assert applied.eval_report_max_chars == 2000
