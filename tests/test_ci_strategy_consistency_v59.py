from __future__ import annotations

from pathlib import Path

from minicodex_agent import quality_gate
from minicodex_agent.quality_gate import _verification_command_specs, build_test_matrix_plan

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_ci_and_release_use_file_level_coverage_gate() -> None:
    ci = _read(".github/workflows/ci.yml")
    release = _read(".github/workflows/release.yml")

    assert "scripts/run_coverage_gate.py" in ci
    assert "scripts/run_coverage_gate.py" in release
    assert '--marker-expr "not slow' not in ci
    assert '--marker-expr "not slow' not in release
    assert "pytest --cov" not in ci
    assert "pytest --cov" not in release
    assert "python -m pytest --cov" not in ci
    assert "python -m pytest --cov" not in release


def test_precommit_is_bounded_and_not_monolithic_pytest() -> None:
    precommit = _read(".pre-commit-config.yaml")

    assert "scripts/check_python_syntax.py" in precommit
    assert "scripts/run_test_matrix.py --group fast --max-files 12 --json" in precommit
    assert "pytest -q" not in precommit
    assert "--max-files 0" not in precommit


def test_docs_and_readiness_recommend_file_level_coverage() -> None:
    checked = [
        _read("README.md"),
        _read("docs/testing.md"),
        _read("docs/architecture.md"),
        _read("src/minicodex_agent/quality_gate.py"),
    ]

    for text in checked:
        assert "scripts/run_coverage_gate.py" in text
        assert '--marker-expr "not slow' not in text
        assert "pytest --cov=minicodex_agent" not in text
        assert "python -m pytest --cov" not in text


def test_quality_gate_plan_and_verification_specs_use_coverage_script() -> None:
    plan = build_test_matrix_plan(ROOT, group="fast")
    recommended = "\n".join(plan["recommended_ci_commands"])
    assert "scripts/check_python_syntax.py src tests scripts" in recommended
    assert "scripts/run_coverage_gate.py" in recommended
    assert "pytest --cov" not in recommended
    assert "--max-files 0" not in recommended

    syntax_command = plan["commands"][0]
    syntax_text = " ".join(str(part) for part in syntax_command["command"])
    assert syntax_command["kind"] == "syntax"
    assert syntax_command["executes_tests"] is False
    assert "scripts/check_python_syntax.py" in syntax_text
    assert "run_test_matrix.py" not in syntax_text
    assert "pytest" not in syntax_text

    coverage_specs = [
        spec for spec in _verification_command_specs(ROOT) if spec["kind"] == "coverage"
    ]
    assert len(coverage_specs) == 1
    command = " ".join(str(part) for part in coverage_specs[0]["command"])
    assert "scripts/run_coverage_gate.py" in command
    assert "--marker-expr" not in command
    assert "pytest --cov" not in command


def test_verification_specs_detect_ruff_as_a_python_module(monkeypatch) -> None:
    monkeypatch.setattr(
        quality_gate,
        "_python_module_available",
        lambda module: module == "ruff",
    )
    monkeypatch.setattr(quality_gate.shutil, "which", lambda _command: None)

    ruff_spec = next(
        spec for spec in quality_gate._verification_command_specs(ROOT) if spec["name"] == "ruff"
    )

    assert ruff_spec["command"] == [
        quality_gate.sys.executable,
        "-m",
        "ruff",
        "check",
        ".",
    ]
    assert ruff_spec["available"] is True
