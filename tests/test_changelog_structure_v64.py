from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent import quality_gate


def _write_minimal_version_files(root: Path, version: str = "1.2.0") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8"
    )
    package = root / "src" / "minicodex_agent"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def _payload(rendered: str) -> dict:
    _, raw = rendered.split("\n", 1)
    return json.loads(raw)


def test_current_changelog_is_canonical_and_unique() -> None:
    root = Path(__file__).resolve().parents[1]

    result = quality_gate.check_changelog_structure(root)

    assert result.status == "pass"
    assert result.details["h1_changelog_lines"] == [1]
    assert result.details["duplicate_versions"] == []
    assert result.details["invalid_format"] == []
    assert result.details["out_of_order"] is False
    assert result.details["current_version"] == "4.4.23"
    assert result.details["current_version_present"] is True


def test_changelog_structure_rejects_duplicate_and_malformed_headings(tmp_path: Path) -> None:
    _write_minimal_version_files(tmp_path, "1.2.0")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## 1.2.0 - Current\n\n- Current entry.\n\n"
        "# Changelog\n\n"
        "## v1.1.0 - Prefixed version\n\n- Bad heading.\n\n"
        "# 1.0.0\n\n- Bad level.\n\n"
        "## 1.2.0 - Duplicate\n\n- Duplicate entry.\n",
        encoding="utf-8",
    )

    result = quality_gate.check_changelog_structure(tmp_path)

    assert result.status == "fail"
    assert result.details["h1_changelog_lines"] == [1, 7]
    assert result.details["duplicate_versions"] == ["1.2.0"]
    assert {record["version"] for record in result.details["invalid_format"]} == {"1.1.0", "1.0.0"}


def test_changelog_structure_rejects_out_of_order_versions(tmp_path: Path) -> None:
    _write_minimal_version_files(tmp_path, "1.2.0")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## 1.1.0 - Older first\n\n- Old.\n\n"
        "## 1.2.0 - Current second\n\n- Current.\n",
        encoding="utf-8",
    )

    result = quality_gate.check_changelog_structure(tmp_path)

    assert result.status == "fail"
    assert result.details["out_of_order"] is True
    assert result.details["version_order"] == ["1.1.0", "1.2.0"]
    assert result.details["expected_order"] == ["1.2.0", "1.1.0"]


def test_final_readiness_includes_changelog_structure_check(tmp_path: Path) -> None:
    _write_minimal_version_files(tmp_path, "1.2.0")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.2.0 - Bad\n\n- Bad.\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "src" / "minicodex_agent" / "cli.py").write_text(
        "print('demo')\n", encoding="utf-8"
    )

    payload = _payload(
        quality_gate.final_readiness_report(
            tmp_path,
            include_cli_smoke=False,
            include_test_matrix=False,
            include_security_audit=False,
            include_verification_tools=False,
            max_chars=20000,
        )
    )

    checks = {check["name"]: check for check in payload["checks"]}
    assert "changelog_structure" in checks
    assert checks["changelog_structure"]["status"] == "fail"
