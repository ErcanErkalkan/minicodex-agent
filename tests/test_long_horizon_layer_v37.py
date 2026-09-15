from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import Observation
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.long_horizon import (
    compact_agent_observations,
    create_checkpoint,
    create_long_task,
    list_long_tasks,
    long_task_path,
    read_long_task,
    resume_long_task,
    update_acceptance_criteria,
)
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS, check_tool_access
from minicodex_agent.project_settings import init_project_config, read_project_config
from minicodex_agent.tool_registry import get_tool_registry


def _json(text: str) -> dict:
    return json.loads(text)


def test_long_horizon_actions_are_registered() -> None:
    for name in [
        "create_long_task",
        "list_long_tasks",
        "read_long_task",
        "resume_long_task",
        "update_acceptance_criteria",
        "create_checkpoint",
    ]:
        assert name in ACTION_SPECS
        assert name in get_tool_registry()
        validate_action(
            {
                "thought": "x",
                "action": name,
                "args": {"run_id": "lh-test"}
                if name not in {"create_long_task", "list_long_tasks"}
                else {},
            }
        )


def test_create_checkpoint_and_resume_long_task(tmp_path: Path) -> None:
    created = _json(
        create_long_task(
            tmp_path,
            goal="Finish a multi-step refactor",
            acceptance_criteria=["tests pass", "docs updated"],
            milestones=["patch layer", "verification"],
        )
    )
    run_id = created["task"]["run_id"]
    assert long_task_path(tmp_path, run_id).exists()

    checkpoint = _json(
        create_checkpoint(
            tmp_path,
            run_id,
            label="after-tests",
            summary="Targeted tests passed.",
            completed_milestones=["milestone-1"],
            accepted_criteria=["criterion-1"],
            changed_files=["src/app.py"],
            checks_run=["pytest tests/test_app.py"],
            next_steps=["run full suite"],
        )
    )
    assert checkpoint["task"]["checkpoint_count"] == 1
    assert checkpoint["task"]["criteria_done"] == 1

    resume = _json(resume_long_task(tmp_path, run_id))
    assert resume["task"]["run_id"] == run_id
    assert len(resume["last_checkpoints"]) == 1
    assert resume["unfinished_acceptance_criteria"][0]["id"] == "criterion-2"


def test_update_acceptance_and_list_read(tmp_path: Path) -> None:
    run_id = _json(create_long_task(tmp_path, goal="x", acceptance_criteria=["a", "b"]))["task"][
        "run_id"
    ]
    updated = _json(
        update_acceptance_criteria(tmp_path, run_id, accepted=["criterion-2"], evidence="verified")
    )
    assert updated["task"]["criteria_done"] == 1
    listing = _json(list_long_tasks(tmp_path))
    assert listing["tasks"][0]["run_id"] == run_id
    read = _json(read_long_task(tmp_path, run_id, include_checkpoints=False))
    assert read["task"]["acceptance_criteria"][1]["evidence"] == "verified"


def test_dry_run_create_long_task_does_not_write(tmp_path: Path) -> None:
    created = _json(create_long_task(tmp_path, goal="dry", dry_run=True))
    assert created["dry_run"] is True
    assert not long_task_path(tmp_path, created["task"]["run_id"]).exists()


def test_safe_run_id_blocks_path_traversal(tmp_path: Path) -> None:
    try:
        long_task_path(tmp_path, "../secret")
    except ValueError as exc:
        assert "run_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("path traversal was not blocked")


def test_compact_agent_observations_keeps_failure_lines() -> None:
    text = compact_agent_observations(
        [
            Observation(
                step=1,
                action="run_tests",
                args="{}",
                observation="hello\nFAILED tests/a.py::test_x\nExit code: 1",
            )
        ]
    )
    assert "FAILED tests/a.py::test_x" in text
    assert "Exit code: 1" in text


def test_project_config_and_plugin_include_long_horizon(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    cfg = read_project_config(tmp_path)
    assert "long_horizon_enabled" in cfg
    config = apply_project_config(AgentConfig(root=tmp_path, model="x", provider="stub"))
    assert config.long_horizon_resume_max_chars >= 4000
    plugins = {plugin.name: plugin for plugin in BUILTIN_PLUGINS}
    assert "long-horizon" in plugins
    assert check_tool_access(
        tmp_path, "create_checkpoint", configured_plugins=("long-horizon",)
    ).allowed
