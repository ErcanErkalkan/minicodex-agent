import json
from pathlib import Path

from minicodex_agent.project_inspector import choose_test_command, detect_project


def test_detects_python_pytest(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    profile = detect_project(tmp_path)
    assert "python" in profile.project_types
    assert "pytest -q" in profile.test_commands
    assert choose_test_command(profile) == "pytest -q"


def test_detects_node_scripts(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "build": "vite build", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    profile = detect_project(tmp_path)
    assert "node" in profile.project_types
    assert "npm test" in profile.test_commands
    assert "npm run build" in profile.build_commands
    assert "npm run lint" in profile.lint_commands


def test_detects_makefile_targets(tmp_path: Path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    profile = detect_project(tmp_path)
    assert "make test" in profile.test_commands


def test_override_test_command(tmp_path: Path):
    profile = detect_project(tmp_path)
    assert choose_test_command(profile, "python -m unittest") == "python -m unittest"
