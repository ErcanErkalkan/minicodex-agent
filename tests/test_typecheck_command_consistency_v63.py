from pathlib import Path

from minicodex_agent.language_adapters import analyze_language_stack
from minicodex_agent.project_inspector import detect_project


def _typecheck_commands(root: Path) -> list[str]:
    report = analyze_language_stack(root)
    return [command.command for command in report.commands if command.purpose == "typecheck"]


def test_minicodex_repo_uses_ci_readme_typecheck_command():
    root = Path(__file__).resolve().parents[1]

    commands = _typecheck_commands(root)
    profile = detect_project(root)

    assert "mypy src/minicodex_agent" in commands
    assert "mypy src/minicodex_agent" in profile.typecheck_commands
    assert "mypy ." not in commands
    assert "mypy ." not in profile.typecheck_commands


def test_src_layout_single_package_gets_package_scoped_mypy(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n"
        "[project.optional-dependencies]\ndev = ['mypy']\n",
        encoding="utf-8",
    )
    package_dir = tmp_path / "src" / "demo_pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "core.py").write_text("value: int = 1\n", encoding="utf-8")

    assert "mypy src/demo_pkg" in _typecheck_commands(tmp_path)


def test_src_layout_multiple_packages_uses_src_scope(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'multi'\nversion = '0.1.0'\n[tool.mypy]\nstrict = true\n",
        encoding="utf-8",
    )
    for package in ["alpha", "beta"]:
        package_dir = tmp_path / "src" / package
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")

    commands = _typecheck_commands(tmp_path)

    assert "mypy src" in commands
    assert "mypy ." not in commands


def test_repository_docs_ci_and_agent_do_not_disagree_on_mypy_scope():
    root = Path(__file__).resolve().parents[1]
    checked_files = [
        root / "README.md",
        root / "docs" / "architecture.md",
        root / "docs" / "testing.md",
        root / ".github" / "workflows" / "ci.yml",
        root / ".github" / "workflows" / "release.yml",
    ]

    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        assert "mypy src/minicodex_agent" in text
        assert "mypy ." not in text

    source = (root / "src" / "minicodex_agent" / "language_adapters.py").read_text(encoding="utf-8")
    assert 'CommandSuggestion("mypy ."' not in source
