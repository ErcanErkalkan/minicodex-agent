from __future__ import annotations

import json
import zipfile
from pathlib import Path

from minicodex_agent.quality_gate import release_package_manifest


def _payload(rendered: str) -> dict:
    return json.loads(rendered.split("\n", 1)[1])


def test_zip_manifest_derives_all_metadata_from_zip_not_root(tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-root"
    fake_root.mkdir()
    (fake_root / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (fake_root / "README.md").write_text("# Fake root\n", encoding="utf-8")
    (fake_root / "src" / "minicodex_agent").mkdir(parents=True)
    (fake_root / "src" / "minicodex_agent" / "root_only.py").write_text(
        "ROOT_ONLY = True\n", encoding="utf-8"
    )
    (fake_root / "tests" / "unit").mkdir(parents=True)
    (fake_root / "tests" / "unit" / "test_root_only.py").write_text(
        "def test_root_only():\n    assert True\n", encoding="utf-8"
    )
    (fake_root / ".pytest_cache").mkdir()
    (fake_root / ".pytest_cache" / "noise").write_text("local cache", encoding="utf-8")

    archive = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("artifact-root/pyproject.toml", '[project]\nversion = "1.2.3"\n')
        zf.writestr("artifact-root/README.md", "# Artifact\n")
        zf.writestr("artifact-root/CHANGELOG.md", "## 1.2.3\n")
        zf.writestr("artifact-root/src/minicodex_agent/__init__.py", '__version__ = "1.2.3"\n')
        zf.writestr("artifact-root/src/minicodex_agent/tools/demo.py", "VALUE = 1\n")
        zf.writestr("artifact-root/tests/test_top_level.py", "def test_ok():\n    assert True\n")
        zf.writestr(
            "artifact-root/tests/unit/test_nested.py", "def test_nested():\n    assert True\n"
        )

    manifest = _payload(release_package_manifest(fake_root, from_zip=archive))

    assert manifest["source"] == "zip"
    assert manifest["metadata_source"] == "zip_members"
    assert manifest["root_used_for_metadata"] is False
    assert manifest["artifact_root_prefix"] == "artifact-root/"
    assert manifest["version"] == "1.2.3"
    assert manifest["top_level_docs"] == ["CHANGELOG.md", "README.md"]
    assert manifest["source_modules"] == 2
    assert manifest["test_files"] == 2
    assert manifest["generated_artifact_count"] == 0


def test_zip_manifest_counts_generated_artifacts_inside_zip_after_prefix_normalization(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    archive = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("pkg/pyproject.toml", '[project]\nversion = "2.0.0"\n')
        zf.writestr("pkg/src/minicodex_agent/__init__.py", '__version__ = "2.0.0"\n')
        zf.writestr("pkg/src/minicodex_agent/__pycache__/bad.pyc", b"cache")
        zf.writestr("pkg/.coverage", "coverage data")

    manifest = _payload(release_package_manifest(root, from_zip=archive))

    assert manifest["source"] == "zip"
    assert manifest["metadata_source"] == "zip_members"
    assert manifest["root_used_for_metadata"] is False
    assert manifest["generated_artifact_count"] == 2
    assert ".coverage" in manifest["generated_artifacts"]
    assert "src/minicodex_agent/__pycache__/bad.pyc" in manifest["generated_artifacts"]


def test_working_tree_manifest_uses_root_and_counts_nested_tests(tmp_path: Path) -> None:
    (tmp_path / "src" / "minicodex_agent" / "tools").mkdir(parents=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "3.0.0"\n', encoding="utf-8")
    (tmp_path / "src" / "minicodex_agent" / "__init__.py").write_text(
        '__version__ = "3.0.0"\n', encoding="utf-8"
    )
    (tmp_path / "src" / "minicodex_agent" / "tools" / "demo.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_top_level.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "unit" / "test_nested.py").write_text(
        "def test_nested():\n    assert True\n", encoding="utf-8"
    )

    manifest = _payload(release_package_manifest(tmp_path))

    assert manifest["source"] == "working_tree"
    assert manifest["metadata_source"] == "working_tree"
    assert manifest["root_used_for_metadata"] is True
    assert manifest["version"] == "3.0.0"
    assert manifest["source_modules"] == 2
    assert manifest["test_files"] == 2
