"""Tool handlers for MiniCodex modular prompt inspection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.prompt_engine import (
    build_prompt_bundle,
    list_prompt_profiles,
    render_prompt_preview,
    validate_prompt_bundle,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.utils import to_pretty_json


def handle_list_prompt_profiles(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return "Prompt profiles:\n" + to_pretty_json(list_prompt_profiles())


def handle_render_prompt_bundle(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    profile = str(args.get("profile", ctx.config.prompt_profile) or ctx.config.prompt_profile)
    goal = str(args.get("goal", ctx.state.goal) or ctx.state.goal)
    provider = str(args.get("provider", ctx.config.provider) or ctx.config.provider)
    include_action_reference = bool(args.get("include_action_reference", False))
    max_chars = int(
        args.get("max_chars", ctx.config.prompt_preview_max_chars)
        or ctx.config.prompt_preview_max_chars
    )
    return "Prompt bundle preview:\n" + render_prompt_preview(
        profile=profile,
        goal=goal,
        provider=provider,
        include_action_reference=include_action_reference,
        max_chars=max_chars,
    )


def handle_validate_prompt_contract(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    profile = str(args.get("profile", ctx.config.prompt_profile) or ctx.config.prompt_profile)
    goal = str(args.get("goal", ctx.state.goal) or ctx.state.goal)
    provider = str(args.get("provider", ctx.config.provider) or ctx.config.provider)
    include_action_reference = bool(
        args.get("include_action_reference", ctx.config.prompt_include_action_reference)
    )
    max_chars = int(
        args.get("max_chars", ctx.config.prompt_max_chars) or ctx.config.prompt_max_chars
    )
    bundle = build_prompt_bundle(
        profile=profile,
        goal=goal,
        provider=provider,
        include_action_reference=include_action_reference,
        max_chars=max_chars,
    )
    errors = validate_prompt_bundle(bundle)
    payload = {
        "valid": not errors,
        "errors": errors,
        "bundle": bundle.to_dict(include_prompt=False),
    }
    return "Prompt contract validation:\n" + to_pretty_json(payload)


register_tools(
    [
        ToolSpec(
            "list_prompt_profiles",
            ACTION_SPECS["list_prompt_profiles"],
            handle_list_prompt_profiles,
            "prompting",
            description="List built-in modular prompt profiles.",
        ),
        ToolSpec(
            "render_prompt_bundle",
            ACTION_SPECS["render_prompt_bundle"],
            handle_render_prompt_bundle,
            "prompting",
            description="Render a prompt bundle preview for a profile/provider/goal.",
        ),
        ToolSpec(
            "validate_prompt_contract",
            ACTION_SPECS["validate_prompt_contract"],
            handle_validate_prompt_contract,
            "prompting",
            description="Validate that the modular system prompt contains required safety/action-contract markers.",
        ),
    ]
)
