from __future__ import annotations

from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.project_settings import update_project_config


def test_apply_project_config_respects_defaults(tmp_path):
    update_project_config(
        tmp_path,
        {
            "preferred_provider": "stub",
            "default_safety_profile": "strict",
            "default_approval": "auto",
            "default_test_command": "pytest -q",
            "default_max_steps": 7,
        },
    )
    cfg = apply_project_config(AgentConfig(root=tmp_path, model="m"), explicit_options=set())
    assert cfg.provider == "stub"
    assert cfg.safety_profile == "strict"
    assert cfg.approval == "auto"
    assert cfg.test_command == "pytest -q"
    assert cfg.max_steps == 7


def test_apply_project_config_does_not_override_explicit_provider(tmp_path):
    update_project_config(tmp_path, {"preferred_provider": "stub"})
    cfg = apply_project_config(
        AgentConfig(root=tmp_path, model="m", provider="echo"), explicit_options={"provider"}
    )
    assert cfg.provider == "echo"
