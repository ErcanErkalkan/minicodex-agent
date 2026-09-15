from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent import quality_gate


def _write_positioning_project(
    root: Path, *, changelog_line: str = "- Release-readiness gate."
) -> None:
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        'version = "1.2.3"\n'
        'description = "Developer-preview local coding-agent framework."\n'
        "classifiers = [\n"
        '  "Development Status :: 3 - Alpha",\n'
        "]\n",
        encoding="utf-8",
    )
    package = root / "src" / "minicodex_agent"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (root / "README.md").write_text(
        "# Demo\n\nThis is a developer-preview local coding-agent framework.\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## 1.2.3 - Current\n\n{changelog_line}\n",
        encoding="utf-8",
    )


def _payload(rendered: str) -> dict:
    _, raw = rendered.split("\n", 1)
    return json.loads(raw)


def test_current_package_positioning_is_consistent() -> None:
    root = Path(__file__).resolve().parents[1]

    result = quality_gate.check_positioning_consistency(root)

    assert result.status == "pass"
    assert result.details["alpha_classifier_present"] is True
    assert result.details["developer_preview_present"] is True
    assert result.details["forbidden_hit_count"] == 0


def test_positioning_consistency_rejects_overstated_readiness_language(tmp_path: Path) -> None:
    _write_positioning_project(tmp_path, changelog_line="- Added a production-readiness baseline.")

    result = quality_gate.check_positioning_consistency(tmp_path)

    assert result.status == "fail"
    assert result.details["forbidden_hit_count"] == 1
    assert result.details["forbidden_hits"][0]["pattern"] == "production-readiness"
    assert result.details["forbidden_hits"][0]["path"] == "CHANGELOG.md"


def test_positioning_consistency_requires_alpha_and_developer_preview(tmp_path: Path) -> None:
    _write_positioning_project(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    result = quality_gate.check_positioning_consistency(tmp_path)

    assert result.status == "fail"
    assert result.details["alpha_classifier_present"] is False
    assert result.details["developer_preview_present"] is False


def test_final_readiness_includes_positioning_consistency_check(tmp_path: Path) -> None:
    _write_positioning_project(tmp_path, changelog_line="- Added production-ready positioning.")
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
    assert "positioning_consistency" in checks
    assert checks["positioning_consistency"]["status"] == "fail"
