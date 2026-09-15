from __future__ import annotations

import json
import zipfile

from minicodex_agent.quality_gate import build_test_matrix_plan, release_package_manifest


def _json_after_prefix(text: str, prefix: str) -> dict:
    return json.loads(text.split(prefix, 1)[1])


def test_test_matrix_plan_uses_bytecode_free_syntax_checker(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )

    plan = build_test_matrix_plan(tmp_path, group="fast")

    syntax = plan["commands"][0]
    assert syntax["name"] == "syntax"
    assert syntax["kind"] == "syntax"
    assert syntax["executes_tests"] is False
    command = " ".join(str(part) for part in syntax["command"])
    assert "scripts/check_python_syntax.py" in command
    assert "src" in syntax["command"]
    assert "tests" in syntax["command"]
    assert "scripts" in syntax["command"]
    assert "run_test_matrix.py" not in command
    assert "pytest" not in command
    assert "--max-files" not in command
    assert "bytecode" in syntax["note"]
    assert "never calls pytest" in syntax["note"]


def test_zip_release_manifest_uses_zip_metadata_not_working_tree(tmp_path):
    fake_root = tmp_path / "fake-root"
    fake_root.mkdir()
    (fake_root / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    zip_path = tmp_path / "artifact.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("artifact-root/pyproject.toml", '[project]\nversion = "1.2.3"\n')
        archive.writestr("artifact-root/README.md", "# Artifact\n")
        archive.writestr("artifact-root/src/minicodex_agent/__init__.py", '__version__ = "1.2.3"\n')
        archive.writestr("artifact-root/src/minicodex_agent/tools/demo.py", "VALUE = 1\n")
        archive.writestr("artifact-root/tests/test_demo.py", "def test_ok():\n    assert True\n")

    manifest = _json_after_prefix(
        release_package_manifest(fake_root, from_zip=zip_path),
        "RELEASE_PACKAGE_MANIFEST_JSON",
    )

    assert manifest["source"] == "zip"
    assert manifest["version"] == "1.2.3"
    assert manifest["top_level_docs"] == ["README.md"]
    assert manifest["source_modules"] == 2
    assert manifest["test_files"] == 1


def test_test_matrix_plan_recommended_commands_do_not_reuse_unbounded_syntax_path(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )

    plan = build_test_matrix_plan(tmp_path, group="fast")
    recommended = "\n".join(plan["recommended_ci_commands"])

    assert "scripts/check_python_syntax.py src tests scripts" in recommended
    assert "scripts/run_test_matrix.py --max-files 0" not in recommended
    assert "--max-files 0" not in recommended
    assert "syntax-only" not in recommended


def test_run_test_matrix_syntax_result_reports_real_checker_command(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")

    import importlib.util
    from pathlib import Path as _Path

    script = _Path(__file__).resolve().parents[1] / "scripts" / "run_test_matrix.py"
    spec = importlib.util.spec_from_file_location("run_test_matrix_for_regression", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.syntax_check(tmp_path)
    command = " ".join(str(part) for part in result["command"])
    assert "scripts/check_python_syntax.py" in command
    assert "syntax-only-compile" not in command
    assert "run_test_matrix.py" not in command
    assert result["exit_code"] == 0
