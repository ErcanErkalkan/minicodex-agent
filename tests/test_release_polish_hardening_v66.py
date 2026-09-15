from __future__ import annotations

import json
import zipfile
from pathlib import Path

from minicodex_agent import quality_gate
from minicodex_agent.quality_gate import release_package_manifest


def _payload(rendered: str) -> dict:
    return json.loads(rendered.split("\n", 1)[1])


def test_format_policy_consistency_requires_ci_release_format_checks(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: ruff-format\n",
        encoding="utf-8",
    )
    for rel in quality_gate.FORMAT_POLICY_WORKFLOWS:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "steps:\n  - run: ruff check .\n  - run: ruff format --check .\n", encoding="utf-8"
        )

    result = quality_gate.check_format_policy_consistency(tmp_path)

    assert result.status == "pass"
    assert result.details["precommit_has_ruff_format"] is True
    assert result.details["missing_ruff_format_check"] == []

    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "steps:\n  - run: ruff check .\n",
        encoding="utf-8",
    )
    missing_result = quality_gate.check_format_policy_consistency(tmp_path)

    assert missing_result.status == "fail"
    assert ".github/workflows/ci.yml" in missing_result.details["missing_ruff_format_check"]


def test_current_package_format_dependency_and_cli_help_gates_pass() -> None:
    root = Path(__file__).resolve().parents[1]

    assert quality_gate.check_format_policy_consistency(root).status == "pass"
    assert quality_gate.check_dev_dependency_hygiene(root).status == "pass"
    help_result = quality_gate.check_cli_help_language(root)
    assert help_result.status == "pass"
    assert help_result.details["finding_count"] == 0


def test_verification_tools_use_isolated_copy_and_share_build_artifacts(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    seen: list[tuple[Path, list[str]]] = []
    monkeypatch.setattr(
        quality_gate,
        "_verification_command_specs",
        lambda _root: [
            {
                "name": "build",
                "kind": "build",
                "command": ["python", "-m", "build"],
                "available": True,
            },
            {
                "name": "twine",
                "kind": "package-check",
                "command": ["python", "-m", "twine", "check", "dist/*"],
                "available": True,
            },
        ],
    )

    def fake_run(root: Path, command: list[str], timeout: int) -> dict:
        seen.append((root, command))
        if command[2:4] == ["build", "--outdir"]:
            output = Path(command[4])
            output.mkdir(parents=True, exist_ok=True)
            (output / "demo-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
        return {"command": command, "exit_code": 0, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr(quality_gate, "_run_command", fake_run)

    result = quality_gate.check_verification_tools(tmp_path, run_tools=True, timeout=90)

    assert result.status == "pass"
    assert result.details["python_tools_use_isolated_copy"] is True
    assert all(run_root != tmp_path for run_root, _command in seen)
    twine_command = seen[1][1]
    assert "dist/*" not in twine_command
    assert any(part.endswith(".whl") for part in twine_command)
    assert not (tmp_path / "dist").exists()
    assert not (tmp_path / "build").exists()


def test_dev_dependency_hygiene_flags_unused_dateutil_stub(tmp_path: Path) -> None:
    (tmp_path / "src" / "demo").mkdir(parents=True)
    (tmp_path / "src" / "demo" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n[project.optional-dependencies]\ndev = ["types-python-dateutil>=2"]\n',
        encoding="utf-8",
    )

    result = quality_gate.check_dev_dependency_hygiene(tmp_path)

    assert result.status == "warn"
    assert result.details["stale_dependencies"][0]["dependency"] == "types-python-dateutil"


def test_cli_help_language_rejects_turkish_help_literal(tmp_path: Path) -> None:
    cli_dir = tmp_path / "src" / "minicodex_agent"
    cli_dir.mkdir(parents=True)
    (cli_dir / "cli.py").write_text(
        "import argparse\n"
        "def parse_args():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--model', help='Kullanılacak model adı.')\n",
        encoding="utf-8",
    )

    result = quality_gate.check_cli_help_language(tmp_path)

    assert result.status == "fail"
    assert result.details["finding_count"] == 1
    assert "Kullanılacak" in result.details["findings"][0]["forbidden_patterns"]


def test_zip_manifest_reports_artifact_name_root_match(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    matching = tmp_path / "pkg-root.zip"
    with zipfile.ZipFile(matching, "w") as zf:
        zf.writestr("pkg-root/pyproject.toml", '[project]\nversion = "1.0.0"\n')
        zf.writestr("pkg-root/src/minicodex_agent/__init__.py", '__version__ = "1.0.0"\n')

    manifest = _payload(release_package_manifest(root, from_zip=matching))

    assert manifest["artifact_name"] == "pkg-root"
    assert manifest["artifact_root_name"] == "pkg-root"
    assert manifest["artifact_name_matches_root"] is True

    mismatching = tmp_path / "outer-name.zip"
    with zipfile.ZipFile(mismatching, "w") as zf:
        zf.writestr("inner-name/pyproject.toml", '[project]\nversion = "1.0.0"\n')
        zf.writestr("inner-name/src/minicodex_agent/__init__.py", '__version__ = "1.0.0"\n')

    mismatch_manifest = _payload(release_package_manifest(root, from_zip=mismatching))

    assert mismatch_manifest["artifact_name"] == "outer-name"
    assert mismatch_manifest["artifact_root_name"] == "inner-name"
    assert mismatch_manifest["artifact_name_matches_root"] is False


def test_final_readiness_includes_release_polish_checks(tmp_path: Path) -> None:
    (tmp_path / "src" / "minicodex_agent").mkdir(parents=True)
    (tmp_path / "src" / "minicodex_agent" / "__init__.py").write_text(
        '__version__ = "1.0.0"\n', encoding="utf-8"
    )
    (tmp_path / "src" / "minicodex_agent" / "cli.py").write_text(
        "import argparse\n"
        "def parse_args():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--model', help='Kullanılacak model adı.')\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\ndescription = "developer-preview"\nclassifiers = ["Development Status :: 3 - Alpha"]\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("developer-preview\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0 - Current\n", encoding="utf-8")

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
    assert "format_policy_consistency" in checks
    assert "dev_dependency_hygiene" in checks
    assert "cli_help_language" in checks
    assert checks["cli_help_language"]["status"] == "fail"
