"""Control-flow tool handlers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.i18n import tr
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.utils import to_pretty_json


def handle_update_plan(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    steps = args.get("steps", [])
    if not isinstance(steps, list):
        return "Plan güncellenemedi: steps liste olmalı."
    ctx.state.plan = [str(step) for step in steps]
    ctx.logger.write_plan(ctx.state.plan)
    return "Plan güncellendi:\n" + to_pretty_json(ctx.state.plan)


def handle_ask_user(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    question = str(args["question"])
    if ctx.config.non_interactive:
        answer = ctx.config.default_answer
        return f"{tr('default_answer_used', ctx.config.lang)}\nQuestion: {question}\n{tr('user_answer', ctx.config.lang)}: {answer}"
    ctx.print_header(tr("ask_user_title", ctx.config.lang))
    print(question)
    answer = input("\nAnswer: " if ctx.config.lang == "en" else "\nCevabın: ")
    return f"{tr('user_answer', ctx.config.lang)}: {answer}"


def handle_finish(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return json.dumps(dict(args), ensure_ascii=False, indent=2)


register_tools(
    [
        ToolSpec("update_plan", ACTION_SPECS["update_plan"], handle_update_plan, plugin="control"),
        ToolSpec("ask_user", ACTION_SPECS["ask_user"], handle_ask_user, plugin="control"),
        ToolSpec("finish", ACTION_SPECS["finish"], handle_finish, plugin="control"),
    ]
)
