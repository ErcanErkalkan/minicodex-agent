"""Project, configuration, plugin, release, and planning tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.code_map import build_code_map
from minicodex_agent.config_tools import validate_config_file
from minicodex_agent.demo_project import create_demo_project
from minicodex_agent.multi_agent import list_agent_batches, make_multi_agent_plan, run_task_batch
from minicodex_agent.plugin_registry import (
    inspect_plugin,
    render_enabled_tools,
    render_plugins,
    render_tool_help,
    validate_plugin_manifests,
)
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_policy import (
    init_project_policy,
    render_policy_check,
    render_project_policy,
    update_project_policy,
)
from minicodex_agent.project_settings import (
    init_project_config,
    render_project_config,
    update_project_config,
)
from minicodex_agent.provider_registry import render_provider_registry
from minicodex_agent.release_tools import (
    build_release_checklist,
    project_health_report,
    write_release_notes,
)
from minicodex_agent.setup_wizard import run_setup_wizard
from minicodex_agent.task_planner import decompose_task
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def handle_run_setup_wizard(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    overwrite = bool(args.get("overwrite", False))
    if (
        overwrite
        and not ctx.config.dry_run
        and not ctx.confirm("MiniCodex setup dosyaları overwrite edilecek.")
    ):
        return "Kullanıcı run_setup_wizard overwrite işlemini reddetti."
    return run_setup_wizard(
        ctx.config.root,
        overwrite=overwrite,
        provider=str(args.get("provider", ctx.config.provider)),
        approval=str(args.get("approval", ctx.config.approval)),
        safety_profile=str(args.get("safety_profile", ctx.config.safety_profile)),
        test_command=str(args.get("test_command", ctx.config.test_command)),
        max_steps=int(args.get("max_steps", ctx.config.max_steps)),
        create_env_example=bool(args.get("create_env_example", True)),
        create_policy=bool(args.get("create_policy", True)),
        create_plugin_example=bool(args.get("create_plugin_example", True)),
        create_agent_instructions=bool(args.get("create_agent_instructions", True)),
        create_skill_example=bool(args.get("create_skill_example", True)),
        dry_run=ctx.config.dry_run,
    )


def handle_create_demo_project(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    target_path = str(args["target_path"])
    overwrite = bool(args.get("overwrite", False))
    if not ctx.config.dry_run and not ctx.confirm(f"Demo proje oluşturulacak: {target_path}"):
        return "Kullanıcı create_demo_project işlemini reddetti."
    return create_demo_project(
        ctx.config.root / target_path, overwrite=overwrite, dry_run=ctx.config.dry_run
    )


def handle_release_checklist(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return build_release_checklist(ctx.config.root, version=str(args.get("version", "")))


def handle_write_release_notes(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    if not ctx.config.dry_run and not ctx.confirm("Release notes dosyası yazılacak/güncellenecek."):
        return "Kullanıcı write_release_notes işlemini reddetti."
    return write_release_notes(
        ctx.config.root,
        version=str(args.get("version", "")),
        output_path=str(args.get("output_path", "RELEASE_NOTES.md")),
        dry_run=ctx.config.dry_run,
    )


def handle_project_health_report(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return project_health_report(
        ctx.config.root, max_chars=int(args.get("max_chars", ctx.config.max_observation_chars))
    )


def handle_init_project_config(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    overwrite = bool(args.get("overwrite", False))
    if (
        overwrite
        and not ctx.config.dry_run
        and not ctx.confirm("MiniCodex proje ayar dosyası overwrite edilecek.")
    ):
        return "Kullanıcı init_project_config overwrite işlemini reddetti."
    return init_project_config(ctx.config.root, overwrite=overwrite, dry_run=ctx.config.dry_run)


def handle_read_project_config(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_project_config(ctx.config.root)


def handle_update_project_config(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    updates = args.get("updates", {})
    if not isinstance(updates, dict):
        return "update_project_config için updates JSON object olmalı."
    if not ctx.config.dry_run and not ctx.confirm("MiniCodex proje ayarları güncellenecek."):
        return "Kullanıcı update_project_config işlemini reddetti."
    return update_project_config(ctx.config.root, updates, dry_run=ctx.config.dry_run)


def handle_init_project_policy(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    overwrite = bool(args.get("overwrite", False))
    if (
        overwrite
        and not ctx.config.dry_run
        and not ctx.confirm("MiniCodex proje policy dosyası overwrite edilecek.")
    ):
        return "Kullanıcı init_project_policy overwrite işlemini reddetti."
    return init_project_policy(
        ctx.config.root,
        overwrite=overwrite,
        policy_file=ctx.config.policy_file,
        dry_run=ctx.config.dry_run,
    )


def handle_read_project_policy(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_project_policy(ctx.config.root, policy_file=ctx.config.policy_file)


def handle_update_project_policy(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    updates = args.get("updates", {})
    if not isinstance(updates, dict):
        return "update_project_policy için updates JSON object olmalı."
    if not ctx.config.dry_run and not ctx.confirm("MiniCodex proje policy ayarları güncellenecek."):
        return "Kullanıcı update_project_policy işlemini reddetti."
    return update_project_policy(
        ctx.config.root, updates, policy_file=ctx.config.policy_file, dry_run=ctx.config.dry_run
    )


def handle_check_project_policy(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_policy_check(
        ctx.config.root,
        kind=str(args["kind"]),
        value=str(args["value"]),
        policy_file=ctx.config.policy_file,
        enabled_plugins=ctx.config.enabled_plugins,
    )


def handle_validate_plugins(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return validate_plugin_manifests(ctx.config.root)


def handle_enabled_tools(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_enabled_tools(ctx.config.root)


def handle_inspect_plugin(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return inspect_plugin(ctx.config.root, str(args["name"]))


def handle_list_providers(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_provider_registry()


def handle_list_plugins(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return render_plugins(ctx.config.root)


def handle_tool_help(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    tool = args.get("tool")
    return render_tool_help(str(tool) if tool else None)


def handle_validate_config(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return validate_config_file(
        ctx.config.root,
        user_path=str(args["path"]),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_build_code_map(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return build_code_map(
        ctx.config.root,
        start_path=str(args.get("path", ".")),
        max_files=int(args.get("max_files", 120)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_decompose_task(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return decompose_task(
        ctx.config.root,
        goal=str(args.get("goal", ctx.state.goal)),
        max_steps=int(args.get("max_steps", 8)),
    )


def handle_plan_multi_agent_work(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return make_multi_agent_plan(
        ctx.config.root,
        goal=str(args.get("goal", ctx.state.goal)),
        max_agents=min(int(args.get("max_agents", 4)), ctx.config.max_agent_batch_size),
    )


def handle_run_task_batch(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    tasks = args.get("tasks", [])
    if not isinstance(tasks, list):
        return "run_task_batch için tasks liste olmalı."
    dry_run = bool(args.get("dry_run", ctx.config.dry_run))
    if not dry_run and not ctx.confirm("Task batch kaydedilecek."):
        return "Kullanıcı run_task_batch işlemini reddetti."
    return run_task_batch(
        ctx.config.root,
        tasks=[str(task) for task in tasks],
        max_tasks=min(
            int(args.get("max_tasks", ctx.config.max_agent_batch_size)),
            ctx.config.max_agent_batch_size,
        ),
        dry_run=dry_run,
    )


def handle_list_agent_batches(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return list_agent_batches(ctx.config.root, limit=int(args.get("limit", 10)))


def handle_inspect_project(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    ctx.state.project_profile = detect_project(ctx.config.root)
    return ctx.state.project_profile.summary()


register_tools(
    [
        ToolSpec(
            "run_setup_wizard",
            ACTION_SPECS["run_setup_wizard"],
            handle_run_setup_wizard,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "create_demo_project",
            ACTION_SPECS["create_demo_project"],
            handle_create_demo_project,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "release_checklist",
            ACTION_SPECS["release_checklist"],
            handle_release_checklist,
            plugin="project",
        ),
        ToolSpec(
            "write_release_notes",
            ACTION_SPECS["write_release_notes"],
            handle_write_release_notes,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "project_health_report",
            ACTION_SPECS["project_health_report"],
            handle_project_health_report,
            plugin="project",
        ),
        ToolSpec(
            "init_project_config",
            ACTION_SPECS["init_project_config"],
            handle_init_project_config,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "read_project_config",
            ACTION_SPECS["read_project_config"],
            handle_read_project_config,
            plugin="project",
        ),
        ToolSpec(
            "update_project_config",
            ACTION_SPECS["update_project_config"],
            handle_update_project_config,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "init_project_policy",
            ACTION_SPECS["init_project_policy"],
            handle_init_project_policy,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "read_project_policy",
            ACTION_SPECS["read_project_policy"],
            handle_read_project_policy,
            plugin="project",
        ),
        ToolSpec(
            "update_project_policy",
            ACTION_SPECS["update_project_policy"],
            handle_update_project_policy,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "check_project_policy",
            ACTION_SPECS["check_project_policy"],
            handle_check_project_policy,
            plugin="project",
        ),
        ToolSpec(
            "validate_plugins",
            ACTION_SPECS["validate_plugins"],
            handle_validate_plugins,
            plugin="project",
        ),
        ToolSpec(
            "enabled_tools", ACTION_SPECS["enabled_tools"], handle_enabled_tools, plugin="project"
        ),
        ToolSpec(
            "inspect_plugin",
            ACTION_SPECS["inspect_plugin"],
            handle_inspect_plugin,
            plugin="project",
        ),
        ToolSpec(
            "list_providers",
            ACTION_SPECS["list_providers"],
            handle_list_providers,
            plugin="project",
        ),
        ToolSpec(
            "list_plugins", ACTION_SPECS["list_plugins"], handle_list_plugins, plugin="project"
        ),
        ToolSpec("tool_help", ACTION_SPECS["tool_help"], handle_tool_help, plugin="project"),
        ToolSpec(
            "validate_config",
            ACTION_SPECS["validate_config"],
            handle_validate_config,
            plugin="project",
        ),
        ToolSpec(
            "build_code_map",
            ACTION_SPECS["build_code_map"],
            handle_build_code_map,
            plugin="project",
        ),
        ToolSpec(
            "decompose_task",
            ACTION_SPECS["decompose_task"],
            handle_decompose_task,
            plugin="project",
        ),
        ToolSpec(
            "plan_multi_agent_work",
            ACTION_SPECS["plan_multi_agent_work"],
            handle_plan_multi_agent_work,
            plugin="project",
        ),
        ToolSpec(
            "run_task_batch",
            ACTION_SPECS["run_task_batch"],
            handle_run_task_batch,
            plugin="project",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "list_agent_batches",
            ACTION_SPECS["list_agent_batches"],
            handle_list_agent_batches,
            plugin="project",
        ),
        ToolSpec(
            "inspect_project",
            ACTION_SPECS["inspect_project"],
            handle_inspect_project,
            plugin="project",
        ),
    ]
)
