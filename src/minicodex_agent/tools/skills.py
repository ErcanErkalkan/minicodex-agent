"""Repo-local skill tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.skill_manager import (
    init_skill,
    read_skill,
    render_skill_catalog,
    validate_skills,
)
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def handle_list_skills(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    goal = str(args.get("goal", ctx.state.goal))
    max_skills = int(args.get("max_skills", ctx.config.skills_max_selected))
    return render_skill_catalog(
        ctx.config.root,
        goal=goal,
        max_skills=max_skills,
        max_summary_chars=ctx.config.skills_max_summary_chars,
    )


def handle_read_skill(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return read_skill(
        ctx.config.root,
        str(args["name"]),
        max_chars=int(args.get("max_chars", ctx.config.skills_read_max_chars)),
    )


def handle_validate_skills(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return validate_skills(ctx.config.root, max_skills=int(args.get("max_skills", 200)))


def handle_init_skill(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    name = str(args["name"])
    overwrite = bool(args.get("overwrite", False))
    if not ctx.config.dry_run and not ctx.confirm(
        f"Repo-local skill oluşturulacak/güncellenecek: {name}"
    ):
        return "Kullanıcı init_skill işlemini reddetti."
    return init_skill(
        ctx.config.root,
        name=name,
        description=str(args.get("description", "Project-local workflow guidance.")),
        overwrite=overwrite,
        dry_run=ctx.config.dry_run,
    )


register_tools(
    [
        ToolSpec("list_skills", ACTION_SPECS["list_skills"], handle_list_skills, plugin="skills"),
        ToolSpec("read_skill", ACTION_SPECS["read_skill"], handle_read_skill, plugin="skills"),
        ToolSpec(
            "validate_skills",
            ACTION_SPECS["validate_skills"],
            handle_validate_skills,
            plugin="skills",
        ),
        ToolSpec(
            "init_skill",
            ACTION_SPECS["init_skill"],
            handle_init_skill,
            plugin="skills",
            requires_approval=True,
            risk_level="medium",
        ),
    ]
)
