"""Evaluation harness tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.eval_runner import (
    compare_eval_baselines,
    compare_eval_runs,
    eval_baseline_plan,
    eval_coverage_report,
    init_eval_baselines,
    init_eval_suite,
    list_eval_baselines,
    list_eval_runs,
    list_eval_tasks,
    load_eval_task,
    read_eval_run,
    run_eval_suite,
    run_eval_task,
)
from minicodex_agent.prompt_ab import run_prompt_ab_comparison
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.common import as_string_list
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.utils import to_pretty_json, truncate


def handle_init_eval_suite(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    """Create starter eval tasks."""

    result = init_eval_suite(
        ctx.config.root,
        overwrite=bool(args.get("overwrite", False)),
        dry_run=ctx.config.dry_run or bool(args.get("dry_run", False)),
    )
    return to_pretty_json(result)


def handle_init_eval_baselines(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    """Create provider/model baseline manifests."""

    result = init_eval_baselines(
        ctx.config.root,
        overwrite=bool(args.get("overwrite", False)),
        dry_run=ctx.config.dry_run or bool(args.get("dry_run", False)),
    )
    return to_pretty_json(result)


def handle_list_eval_tasks(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    tasks = list_eval_tasks(ctx.config.root)
    category = str(args.get("category") or "").strip()
    tag = str(args.get("tag") or "").strip()
    if category:
        tasks = [task for task in tasks if task.get("category") == category]
    if tag:
        tasks = [task for task in tasks if tag in task.get("tags", [])]
    limit = int(args.get("limit", 50))
    return to_pretty_json({"summary": f"Found {len(tasks)} eval task(s).", "tasks": tasks[:limit]})


def handle_list_eval_baselines(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    baselines = list_eval_baselines(ctx.config.root)
    tag = str(args.get("tag") or "").strip()
    if tag:
        baselines = [baseline for baseline in baselines if tag in baseline.get("tags", [])]
    limit = int(args.get("limit", 50))
    return to_pretty_json(
        {"summary": f"Found {len(baselines)} eval baseline(s).", "baselines": baselines[:limit]}
    )


def handle_eval_baseline_plan(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return to_pretty_json(
        eval_baseline_plan(
            ctx.config.root,
            str(args.get("baseline_id") or ""),
            run_id=str(args.get("run_id") or "") or None,
        )
    )


def handle_eval_coverage_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    del args
    return to_pretty_json(eval_coverage_report(ctx.config.root))


def handle_compare_eval_baselines(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return to_pretty_json(
        compare_eval_baselines(
            ctx.config.root,
            str(args.get("baseline_run_id") or ""),
            str(args.get("candidate_run_id") or ""),
            min_success_delta=float(args.get("min_success_delta", 0.0)),
        )
    )


def handle_read_eval_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    task_id = str(args.get("task_id") or "")
    task = load_eval_task(ctx.config.root, task_id)
    include_files = bool(args.get("include_files", False))
    data = task.to_dict()
    if not include_files:
        data["files"] = {path: f"<{len(content)} chars>" for path, content in task.files.items()}
    return truncate(to_pretty_json(data), int(args.get("max_chars", 16000)))


def handle_run_eval_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    task_id = str(args.get("task_id") or "")
    if not ctx.config.dry_run and not ctx.confirm(
        f"Run eval task {task_id!r}. This creates a disposable workspace and may run the agent plus verification commands.",
        force_manual=ctx.config.provider not in {"stub", "echo"},
    ):
        return f"User rejected eval task run: {task_id}"
    result = run_eval_task(
        ctx.config.root,
        ctx.config,
        task_id,
        run_id=str(args.get("run_id") or "") or None,
        max_steps=int(args.get("max_steps", ctx.config.eval_default_max_steps)),
        model_call_budget=int(args.get("model_call_budget", ctx.config.eval_model_call_budget)),
        timeout=int(args.get("timeout", ctx.config.eval_timeout_seconds)),
        dry_run=ctx.config.dry_run or bool(args.get("dry_run", False)),
    )
    return truncate(
        to_pretty_json(result), int(args.get("max_chars", ctx.config.eval_report_max_chars))
    )


def handle_run_eval_suite(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    task_ids = as_string_list(args, "task_ids") or None
    if not ctx.config.dry_run and not ctx.confirm(
        f"Run eval suite with {len(task_ids) if task_ids else 'all'} task(s). This may run the agent repeatedly.",
        force_manual=ctx.config.provider not in {"stub", "echo"},
    ):
        return "User rejected eval suite run."
    result = run_eval_suite(
        ctx.config.root,
        ctx.config,
        task_ids=task_ids,
        run_id=str(args.get("run_id") or "") or None,
        max_steps=int(args.get("max_steps", ctx.config.eval_default_max_steps)),
        model_call_budget=int(args.get("model_call_budget", ctx.config.eval_model_call_budget)),
        timeout=int(args.get("timeout", ctx.config.eval_timeout_seconds)),
        dry_run=ctx.config.dry_run or bool(args.get("dry_run", False)),
    )
    return truncate(
        to_pretty_json(result), int(args.get("max_chars", ctx.config.eval_report_max_chars))
    )


def handle_list_eval_runs(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    runs = list_eval_runs(ctx.config.root, limit=int(args.get("limit", 20)))
    return to_pretty_json({"summary": f"Found {len(runs)} eval run report(s).", "runs": runs})


def handle_read_eval_run(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_eval_run(
        ctx.config.root,
        str(args.get("run_id") or ""),
        max_chars=int(args.get("max_chars", ctx.config.eval_report_max_chars)),
    )


def handle_run_prompt_ab_comparison(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    task_ids = args.get("task_ids") if isinstance(args.get("task_ids"), list) else []
    profiles = (
        args.get("prompt_profiles")
        if isinstance(args.get("prompt_profiles"), list)
        else ["auto", "local-model"]
    )
    if not ctx.confirm(
        f"Run prompt A/B comparison for {len(profiles)} profile(s) over {len(task_ids) if task_ids else 'default'} task(s).",
    ):
        return "User rejected prompt A/B comparison run."
    result = run_prompt_ab_comparison(
        ctx.config.root,
        ctx.config,
        [str(item) for item in task_ids],
        [str(item) for item in profiles],
        run_id=str(args.get("run_id") or "") or None,
        max_steps=int(args.get("max_steps", ctx.config.eval_default_max_steps)),
        model_call_budget=int(args.get("model_call_budget", ctx.config.eval_model_call_budget)),
        timeout=int(args.get("timeout", ctx.config.eval_timeout_seconds)),
        dry_run=bool(args.get("dry_run", ctx.config.dry_run)),
    )
    return truncate(
        to_pretty_json(result), int(args.get("max_chars", ctx.config.eval_report_max_chars))
    )


def handle_compare_eval_runs(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return to_pretty_json(
        compare_eval_runs(
            ctx.config.root,
            str(args.get("baseline_run_id") or ""),
            str(args.get("candidate_run_id") or ""),
        )
    )


register_tools(
    [
        ToolSpec(
            "init_eval_suite",
            ACTION_SPECS["init_eval_suite"],
            handle_init_eval_suite,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "init_eval_baselines",
            ACTION_SPECS["init_eval_baselines"],
            handle_init_eval_baselines,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "list_eval_tasks",
            ACTION_SPECS["list_eval_tasks"],
            handle_list_eval_tasks,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "list_eval_baselines",
            ACTION_SPECS["list_eval_baselines"],
            handle_list_eval_baselines,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "eval_coverage_report",
            ACTION_SPECS["eval_coverage_report"],
            handle_eval_coverage_report,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "eval_baseline_plan",
            ACTION_SPECS["eval_baseline_plan"],
            handle_eval_baseline_plan,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "compare_eval_baselines",
            ACTION_SPECS["compare_eval_baselines"],
            handle_compare_eval_baselines,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "read_eval_task",
            ACTION_SPECS["read_eval_task"],
            handle_read_eval_task,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "run_eval_task",
            ACTION_SPECS["run_eval_task"],
            handle_run_eval_task,
            plugin="evals",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "run_eval_suite",
            ACTION_SPECS["run_eval_suite"],
            handle_run_eval_suite,
            plugin="evals",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "list_eval_runs",
            ACTION_SPECS["list_eval_runs"],
            handle_list_eval_runs,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "read_eval_run",
            ACTION_SPECS["read_eval_run"],
            handle_read_eval_run,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "compare_eval_runs",
            ACTION_SPECS["compare_eval_runs"],
            handle_compare_eval_runs,
            plugin="evals",
            risk_level="low",
        ),
        ToolSpec(
            "run_prompt_ab_comparison",
            ACTION_SPECS["run_prompt_ab_comparison"],
            handle_run_prompt_ab_comparison,
            plugin="evals",
            requires_approval=True,
            risk_level="high",
        ),
    ]
)
