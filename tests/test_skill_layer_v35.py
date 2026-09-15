from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.agent import AgentState, build_prompt
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_settings import update_project_config
from minicodex_agent.setup_wizard import run_setup_wizard
from minicodex_agent.skill_manager import discover_skills, init_skill, read_skill, validate_skills
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class logger_stub:
    def write_plan(self, plan):
        pass


def make_ctx(tmp_path: Path) -> ToolContext:
    config = AgentConfig(
        root=tmp_path, model="stub", provider="stub", approval="auto", log_enabled=False
    )
    state = AgentState(goal="fix failing pytest tests", project_profile=detect_project(tmp_path))
    return ToolContext(
        config=config,
        state=state,
        logger=logger_stub(),
        confirm_fn=lambda question, auto_approve, **kwargs: True,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_discover_skills_parses_front_matter_and_ranks_by_goal(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".minicodex" / "skills" / "pytest-fix"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
description: Fix failing pytest tests with targeted reruns.
triggers: [pytest, failing, tests]
tags: [testing]
---

# Pytest Fix

## When to use
- Use when pytest fails.

## Workflow
1. Run targeted tests.
""",
        encoding="utf-8",
    )

    skills = discover_skills(tmp_path, goal="fix failing pytest tests", max_skills=5)

    assert skills[0].name == "pytest-fix"
    assert skills[0].description.startswith("Fix failing pytest")
    assert "pytest" in skills[0].triggers
    assert skills[0].relevance > 0


def test_read_skill_returns_full_skill_with_metadata(tmp_path: Path) -> None:
    init_skill(
        tmp_path, name="release-review", description="Review release readiness", dry_run=False
    )

    rendered = read_skill(tmp_path, "release-review", max_chars=2000)
    data = json.loads(rendered.split("\n", 1)[1])

    assert rendered.startswith("SKILL_JSON")
    assert data["skill"]["name"] == "release-review"
    assert "# Release Review" in data["content"]


def test_skill_paths_are_restricted_to_expected_layout(tmp_path: Path) -> None:
    bad = tmp_path / ".minicodex" / "skills" / "bad" / "nested" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text("# Bad", encoding="utf-8")

    validation = validate_skills(tmp_path)

    assert "SKILL_VALIDATION_JSON" in validation
    assert "bad/nested" not in validation


def test_context_pack_and_prompt_include_skill_metadata_not_full_content(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".minicodex" / "skills" / "ci-debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
description: Debug CI failures.
triggers: [ci, failure, tests]
---

# CI Debug

## Workflow
1. summarize_ci_log first.
2. SECRET_FULL_DETAIL_SHOULD_REQUIRE_READ_SKILL
""",
        encoding="utf-8",
    )
    cfg = AgentConfig(root=tmp_path, model="stub", provider="stub", skills_max_summary_chars=1200)
    state = AgentState(goal="debug ci failure", project_profile=detect_project(tmp_path))

    payload = json.loads(build_prompt(state, cfg, 1))
    catalog = payload["context_pack"]["skill_catalog"]

    assert catalog[0]["name"] == "ci-debug"
    assert catalog[0]["path"] == ".minicodex/skills/ci-debug/SKILL.md"
    assert "content" not in catalog[0]
    assert "read_skill" in payload["context_pack"]["notes"][-1]


def test_skill_tools_are_registered_and_dispatchable(tmp_path: Path) -> None:
    init_skill(tmp_path, name="docs-review", description="Review docs", dry_run=False)
    registry = get_tool_registry()

    assert {"list_skills", "read_skill", "validate_skills", "init_skill"}.issubset(registry)
    catalog = dispatch_tool(
        make_ctx(tmp_path), "list_skills", {"goal": "review docs", "max_skills": 3}
    )
    full = dispatch_tool(
        make_ctx(tmp_path), "read_skill", {"name": "docs-review", "max_chars": 2000}
    )

    assert "SKILL_CATALOG_JSON" in catalog
    assert "docs-review" in catalog
    assert "SKILL_JSON" in full
    assert "Docs Review" in full


def test_project_config_applies_skill_fields(tmp_path: Path) -> None:
    update_project_config(
        tmp_path,
        {
            "skills_enabled": False,
            "skills_max_selected": 3,
            "skills_max_summary_chars": 777,
            "skills_read_max_chars": 2222,
        },
    )

    cfg = apply_project_config(
        AgentConfig(root=tmp_path, model="stub", provider="stub"), explicit_options=set()
    )

    assert cfg.skills_enabled is False
    assert cfg.skills_max_selected == 3
    assert cfg.skills_max_summary_chars == 777
    assert cfg.skills_read_max_chars == 2222


def test_setup_wizard_creates_agents_md_and_example_skill(tmp_path: Path) -> None:
    run_setup_wizard(tmp_path, provider="stub")

    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".minicodex" / "skills" / "targeted-testing" / "SKILL.md").exists()
    assert discover_skills(tmp_path, goal="pytest failure")
