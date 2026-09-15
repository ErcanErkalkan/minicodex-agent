"""Test/CI planning and diagnostics tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.test_ci import (
    classify_failure_output,
    detect_flaky_tests,
    plan_tests,
    render_json,
    summarize_ci_log,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.common import as_string_list, run_checked_command
from minicodex_agent.tools.context import ToolContext


def _changed_files(args: Mapping[str, Any]) -> list[str]:
    value = as_string_list(args, "changed_files")
    return value or []


def handle_plan_tests(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    """Plan targeted tests from changed files and/or failure output."""

    plan = plan_tests(
        ctx.config.root,
        ctx.state.project_profile,
        changed_files=_changed_files(args),
        failure_output=str(args.get("failure_output") or ctx.state.last_command_output or ""),
        command_override=str(args.get("command") or ctx.config.test_command),
        include_lint=bool(args.get("include_lint", False)),
        include_build=bool(args.get("include_build", False)),
        include_typecheck=bool(args.get("include_typecheck", False)),
        max_commands=int(args.get("max_commands", ctx.config.test_plan_max_commands)),
    )
    return render_json(
        {
            "summary": f"Planned {len(plan.commands)} verification command(s).",
            "plan": plan.to_dict(),
        }
    )


def handle_run_targeted_tests(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    """Run a bounded targeted test plan sequentially."""

    plan = plan_tests(
        ctx.config.root,
        ctx.state.project_profile,
        changed_files=_changed_files(args),
        failure_output=str(args.get("failure_output") or ctx.state.last_command_output or ""),
        command_override=str(args.get("command") or ctx.config.test_command),
        include_lint=bool(args.get("include_lint", False)),
        include_build=bool(args.get("include_build", False)),
        include_typecheck=bool(args.get("include_typecheck", False)),
        max_commands=int(args.get("max_commands", ctx.config.test_plan_max_commands)),
    )
    if not plan.commands:
        return render_json(
            {
                "ok": False,
                "summary": "No targeted test command could be planned.",
                "plan": plan.to_dict(),
            }
        )

    timeout = int(args.get("timeout", 120))
    results: list[dict[str, object]] = []
    for item in plan.commands:
        output = run_checked_command(
            ctx,
            item.command,
            timeout=timeout,
            dry_run_label="targeted test command not executed",
            reject_label="targeted test command",
        )
        failed = "Exit code: 0" not in output and not output.startswith("DRY-RUN:")
        classification = (
            classify_failure_output(ctx.config.root, output).to_dict() if failed else {}
        )
        results.append(
            {
                "command": item.command,
                "reason": item.reason,
                "scope": item.scope,
                "ok": not failed,
                "classification": classification,
                "output": output,
            }
        )
        if failed and bool(args.get("stop_on_failure", True)):
            break
    overall_ok = all(bool(item["ok"]) for item in results)
    return render_json(
        {
            "ok": overall_ok,
            "summary": "Targeted test run completed.",
            "plan": plan.to_dict(),
            "results": results,
        }
    )


def handle_classify_test_failure(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    output = str(args.get("output") or ctx.state.last_command_output or "")
    classification = classify_failure_output(
        ctx.config.root,
        output,
        max_excerpt_chars=int(args.get("max_excerpt_chars", ctx.config.test_output_max_chars)),
    )
    return render_json(
        {"summary": classification.summary, "classification": classification.to_dict()}
    )


def handle_summarize_ci_log(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    output = str(args.get("output") or ctx.state.last_command_output or "")
    return render_json(
        summarize_ci_log(
            ctx.config.root,
            output,
            max_chars=int(args.get("max_chars", ctx.config.test_output_max_chars)),
        )
    )


def handle_detect_flaky_tests(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    prior = args.get("prior_outputs", [])
    if not isinstance(prior, list):
        prior = []
    output = str(args.get("output") or ctx.state.last_command_output or "")
    return render_json(detect_flaky_tests(output, prior_outputs=[str(item) for item in prior]))


register_tools(
    [
        ToolSpec(
            "plan_tests",
            ACTION_SPECS["plan_tests"],
            handle_plan_tests,
            plugin="execution",
            risk_level="low",
        ),
        ToolSpec(
            "run_targeted_tests",
            ACTION_SPECS["run_targeted_tests"],
            handle_run_targeted_tests,
            plugin="execution",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "classify_test_failure",
            ACTION_SPECS["classify_test_failure"],
            handle_classify_test_failure,
            plugin="diagnostics",
            risk_level="low",
        ),
        ToolSpec(
            "summarize_ci_log",
            ACTION_SPECS["summarize_ci_log"],
            handle_summarize_ci_log,
            plugin="diagnostics",
            risk_level="low",
        ),
        ToolSpec(
            "detect_flaky_tests",
            ACTION_SPECS["detect_flaky_tests"],
            handle_detect_flaky_tests,
            plugin="diagnostics",
            risk_level="low",
        ),
    ]
)
