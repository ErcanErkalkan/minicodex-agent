from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.agent import AgentState, Observation, build_prompt
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.context_manager import (
    build_context_pack,
    compact_observations,
    discover_repo_instructions,
    rank_relevant_files,
    summarize_large_output,
)
from minicodex_agent.project_inspector import ProjectProfile, detect_project
from minicodex_agent.project_settings import update_project_config


def test_repo_instructions_loads_agents_md_with_budget(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "# Agent Rules\nAlways run pytest before finishing.\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")

    instructions = discover_repo_instructions(tmp_path, max_chars=2000)

    assert [item.path for item in instructions] == ["AGENTS.md"]
    assert "Always run pytest" in instructions[0].content
    assert "sk-secret" not in instructions[0].content


def test_rank_relevant_files_uses_goal_symbols_and_skips_sensitive_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        "class TokenValidator:\n    def validate_token(self, token):\n        return token == 'ok'\n",
        encoding="utf-8",
    )
    (src / "other.py").write_text("def unrelated():\n    return 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")

    files = rank_relevant_files(tmp_path, "fix token validation bug", max_files=5)

    assert files[0].path == "src/auth.py"
    assert all(item.path != ".env" for item in files)
    assert "TokenValidator" in " ".join(files[0].symbols)


def test_large_output_compaction_preserves_failure_lines() -> None:
    output = "\n".join(
        ["noise"] * 80
        + ["FAILED tests/test_app.py::test_x", "AssertionError: bad", "tail"]
        + ["more"] * 80
    )

    compacted = summarize_large_output(output, max_chars=700)

    assert "large output compacted" in compacted
    assert "FAILED tests/test_app.py::test_x" in compacted
    assert "AssertionError" in compacted
    assert len(compacted) <= 760


def test_compact_observations_replaces_recent_observation_payloads() -> None:
    obs = [
        Observation(
            step=1,
            action="run_tests",
            args="{}",
            observation="ok\n" + "noise\n" * 200 + "ERROR boom\n",
        ),
        Observation(step=2, action="read_file", args='{"path":"a.py"}', observation="small"),
    ]

    compacted = compact_observations(obs, max_chars_each=500)

    assert len(compacted) == 2
    assert compacted[0].action == "run_tests"
    assert "ERROR boom" in compacted[0].summary
    assert compacted[1].summary == "small"


def test_build_context_pack_includes_instructions_skills_files_and_observations(
    tmp_path: Path,
) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\nUse minimal patches.\n", encoding="utf-8")
    skills = tmp_path / ".minicodex" / "skills" / "testing"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "# Testing Skill\nDescription: Run focused pytest first.\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("def run_tests():\n    return True\n", encoding="utf-8")
    profile = ProjectProfile(
        project_types=["python"],
        package_managers=[],
        test_commands=["pytest"],
        key_files=["app.py"],
        notes=[],
    )

    pack = build_context_pack(
        root=tmp_path,
        goal="fix failing pytest tests",
        profile=profile,
        observations=[
            Observation(step=1, action="run_tests", args="{}", observation="FAILED test_x")
        ],
        budget_chars=6000,
        relevant_files=5,
    )

    assert pack.enabled is True
    assert pack.repo_instructions[0].path == "AGENTS.md"
    assert pack.skill_catalog[0].name == "testing"
    assert any(item.path == "app.py" for item in pack.relevant_files)
    assert pack.compacted_observations[0].action == "run_tests"
    assert pack.used_chars <= pack.budget_chars


def test_build_prompt_includes_context_pack_and_compacted_observations(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\nRead before edit.\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    cfg = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        context_max_chars=8000,
        context_relevant_files=4,
    )
    state = AgentState(goal="update main function", project_profile=detect_project(tmp_path))
    state.observations.append(
        Observation(
            step=1, action="run_tests", args="{}", observation="noise\n" * 200 + "FAILED main"
        )
    )

    payload = json.loads(build_prompt(state, cfg, 2))

    assert payload["context_policy"]["enabled"] is True
    assert payload["context_pack"]["repo_instructions"][0]["path"] == "AGENTS.md"
    assert any(item["path"] == "main.py" for item in payload["context_pack"]["relevant_files"])
    assert payload["recent_observations"][0]["action"] == "run_tests"
    assert "FAILED main" in payload["recent_observations"][0]["observation"]


def test_project_config_applies_context_fields(tmp_path: Path) -> None:
    update_project_config(
        tmp_path,
        {
            "context_enabled": False,
            "context_max_chars": 12345,
            "context_instruction_max_chars": 2345,
            "context_relevant_files": 7,
            "context_observation_chars_each": 999,
        },
    )

    cfg = apply_project_config(
        AgentConfig(root=tmp_path, model="stub", provider="stub"), explicit_options=set()
    )

    assert cfg.context_enabled is False
    assert cfg.context_max_chars == 12345
    assert cfg.context_instruction_max_chars == 2345
    assert cfg.context_relevant_files == 7
    assert cfg.context_observation_chars_each == 999
