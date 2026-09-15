from pathlib import Path

from minicodex_agent.language_adapters import analyze_language_stack
from minicodex_agent.project_inspector import detect_project


def _framework_names(root: Path) -> set[str]:
    return {item.name for item in analyze_language_stack(root).frameworks}


def test_framework_detector_ignores_own_pattern_literals(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'detector-tool'\nversion = '0.1.0'\n"
        "[project.optional-dependencies]\ndev = ['pytest']\n",
        encoding="utf-8",
    )
    package_dir = tmp_path / "src" / "detector_tool"
    package_dir.mkdir(parents=True)
    (package_dir / "language_adapters.py").write_text(
        "FRAMEWORK_PATTERNS = {\n"
        "    'fastapi': ('python', ('fastapi', 'from fastapi', 'FastAPI(')),\n"
        "    'django': ('python', ('django', 'manage.py', 'DJANGO_SETTINGS_MODULE')),\n"
        "    'flask': ('python', ('flask', 'from flask', 'Flask(')),\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    frameworks = _framework_names(tmp_path)

    assert "pytest" in frameworks
    assert "fastapi" not in frameworks
    assert "django" not in frameworks
    assert "flask" not in frameworks


def test_project_profile_does_not_report_web_frameworks_for_minicodex_repo():
    root = Path(__file__).resolve().parents[1]

    profile = detect_project(root)

    assert "pytest" in profile.frameworks
    assert "fastapi" not in profile.frameworks
    assert "django" not in profile.frameworks
    assert "flask" not in profile.frameworks


def test_framework_detector_still_detects_real_fastapi_and_flask_apps(tmp_path: Path):
    app_dir = tmp_path / "src" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "from flask import Flask\n"
        "fastapi_app = FastAPI()\n"
        "flask_app = Flask(__name__)\n",
        encoding="utf-8",
    )

    frameworks = _framework_names(tmp_path)

    assert "fastapi" in frameworks
    assert "flask" in frameworks
