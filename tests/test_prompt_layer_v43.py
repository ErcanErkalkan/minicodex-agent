from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState, MiniCodexAgent, build_prompt
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS, check_tool_access
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_settings import (
    init_project_config,
    read_project_config,
    update_project_config,
)
from minicodex_agent.prompt_engine import (
    build_prompt_bundle,
    infer_prompt_profile,
    list_prompt_profiles,
    render_prompt_preview,
    validate_prompt_bundle,
)
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class _Logger:
    def log_event(self, *_args, **_kwargs):
        pass


def _ctx(root: Path, *, goal: str = "fix failing test") -> ToolContext:
    return ToolContext(
        config=AgentConfig(
            root=root, model="stub", provider="stub", approval="auto", log_enabled=False
        ),
        state=AgentState(goal=goal, project_profile=detect_project(root)),
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_prompt_profile_inference_and_bundle_validation() -> None:
    assert infer_prompt_profile("fix failing pytest traceback", "openai", "auto") == "bugfix"
    assert infer_prompt_profile("review GitHub workflow", "openai", "auto") == "github"
    assert infer_prompt_profile("small smoke task", "ollama", "auto") == "local-model"

    bundle = build_prompt_bundle(
        profile="bugfix",
        goal="fix failing pytest",
        provider="openai",
        include_action_reference=False,
    )

    assert bundle.profile == "bugfix"
    assert "bugfix_profile" in bundle.sections
    assert "Return exactly one valid JSON object" in bundle.system_prompt
    assert validate_prompt_bundle(bundle) == []
    assert "AUTO-GENERATED ACTION REFERENCE" not in bundle.system_prompt


def test_prompt_preview_lists_profiles() -> None:
    profiles = {item["name"] for item in list_prompt_profiles()}
    assert {"auto", "bugfix", "review", "local-model"}.issubset(profiles)
    preview = json.loads(
        render_prompt_preview(
            profile="security", goal="scan secrets", provider="openai", max_chars=4000
        )
    )
    assert preview["profile"] == "security"
    assert "security_profile" in preview["sections"]
    assert "Never expose secrets" in preview["system_prompt"]


def test_build_prompt_includes_prompt_policy(tmp_path: Path) -> None:
    cfg = AgentConfig(root=tmp_path, model="stub", provider="stub", prompt_profile="test-ci")
    state = AgentState(goal="run CI tests", project_profile=detect_project(tmp_path))
    payload = json.loads(build_prompt(state, cfg, 1))

    assert payload["prompt_policy"]["profile"]["profile"] == "test-ci"
    assert "test_ci_profile" in payload["prompt_policy"]["profile"]["sections"]
    assert payload["model_output_contract"]["required_top_level_keys"] == [
        "thought",
        "action",
        "args",
    ]


def test_model_client_receives_profile_aware_system_prompt(tmp_path: Path) -> None:
    cfg = AgentConfig(
        root=tmp_path, model="stub", provider="stub", prompt_profile="security", log_enabled=False
    )
    agent = MiniCodexAgent(cfg)
    agent.run("scan secrets")

    assert agent.system_prompt_bundle.profile == "security"
    assert "Security profile" in agent.model_client.system_prompt


def test_prompt_actions_are_registered_and_dispatchable(tmp_path: Path) -> None:
    registry = get_tool_registry()
    actions = ["list_prompt_profiles", "render_prompt_bundle", "validate_prompt_contract"]
    for action in actions:
        assert action in ACTION_SPECS
        assert action in registry
    validate_action(
        {"thought": "x", "action": "render_prompt_bundle", "args": {"profile": "bugfix"}}
    )
    plugin = next(p for p in BUILTIN_PLUGINS if p.name == "prompting")
    assert all(action in plugin.tools for action in actions)

    ctx = _ctx(tmp_path)
    assert "bugfix" in dispatch_tool(ctx, "list_prompt_profiles", {})
    assert "Prompt bundle preview" in dispatch_tool(
        ctx, "render_prompt_bundle", {"profile": "bugfix", "max_chars": 4000}
    )
    assert '"valid": true' in dispatch_tool(ctx, "validate_prompt_contract", {"profile": "review"})
    assert check_tool_access(
        tmp_path, "render_prompt_bundle", configured_plugins=("prompting",)
    ).allowed


def test_prompt_project_config_fields_apply(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    cfg = read_project_config(tmp_path)
    assert cfg["prompt_profile"] == "auto"
    assert cfg["prompt_include_action_reference"] is True
    update_project_config(
        tmp_path,
        {
            "prompt_profile": "review",
            "prompt_max_chars": 9000,
            "prompt_include_action_reference": False,
            "prompt_preview_max_chars": 3333,
        },
    )
    applied = apply_project_config(
        AgentConfig(root=tmp_path, model="stub", provider="stub"), explicit_options=set()
    )
    assert applied.prompt_profile == "review"
    assert applied.prompt_max_chars == 9000
    assert applied.prompt_include_action_reference is False
    assert applied.prompt_preview_max_chars == 3333
