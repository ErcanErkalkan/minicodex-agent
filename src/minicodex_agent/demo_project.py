"""Create a small demo repository for trying MiniCodex safely."""

from __future__ import annotations

from pathlib import Path

from .setup_wizard import run_setup_wizard

DEMO_FILES: dict[str, str] = {
    "README.md": """# MiniCodex Demo Project\n\nThis tiny project is intentionally simple. It lets you test MiniCodex on a\nreal project without touching your own code.\n\nTry:\n\n```bash\nminicodex \"inspect the project, run tests, and fix the failing test\" --root .\n```\n""",
    "pyproject.toml": """[build-system]\nrequires = [\"setuptools>=70.0\", \"wheel\"]\nbuild-backend = \"setuptools.build_meta\"\n\n[project]\nname = \"minicodex-demo\"\nversion = \"0.1.0\"\ndescription = \"Tiny project for testing MiniCodex.\"\nrequires-python = \">=3.10\"\n\n[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n""",
    "src/minicodex_demo/__init__.py": """from .calculator import add, subtract\n\n__all__ = [\"add\", \"subtract\"]\n""",
    "src/minicodex_demo/calculator.py": """def add(a: int, b: int) -> int:\n    \"\"\"Return the sum of two integers.\"\"\"\n\n    return a + b\n\n\ndef subtract(a: int, b: int) -> int:\n    \"\"\"Return a minus b.\n\n    This implementation intentionally contains a tiny bug so MiniCodex has\n    something safe to fix in the demo.\n    \"\"\"\n\n    return a + b\n""",
    "tests/test_calculator.py": """from minicodex_demo import add, subtract\n\n\ndef test_add() -> None:\n    assert add(2, 3) == 5\n\n\ndef test_subtract() -> None:\n    assert subtract(7, 4) == 3\n""",
}


def create_demo_project(target: Path, *, overwrite: bool = False, dry_run: bool = False) -> str:
    """Create a small Python demo project under target."""

    target = target.resolve()
    if target.exists() and any(target.iterdir()) and not overwrite:
        return f"Demo project target is not empty: {target}\nUse overwrite=true or choose a new folder."

    written: list[str] = []
    for relative, content in DEMO_FILES.items():
        path = target / relative
        if path.exists() and not overwrite:
            continue
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        written.append(relative)

    setup_result = run_setup_wizard(
        target,
        overwrite=overwrite,
        provider="stub",
        approval="ask",
        safety_profile="strict",
        test_command="pytest -q",
        max_steps=20,
        dry_run=dry_run,
    )

    prefix = "DRY-RUN: demo project not created" if dry_run else "Demo project created"
    return (
        f"{prefix} at: {target}\n"
        f"Files written: {len(written)}\n"
        + "\n".join(f"- {item}" for item in written)
        + "\n\n"
        + setup_result
        + "\n\nTry next:\n"
        + f"cd {target}\n"
        + "pip install -e . pytest\n"
        + 'minicodex "run tests, analyze the failure, and fix the bug" --root .\n'
    )
