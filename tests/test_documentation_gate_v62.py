from __future__ import annotations

from pathlib import Path

from minicodex_agent import quality_gate


def _write_required_docs(root: Path) -> None:
    for rel in quality_gate.REQUIRED_DOCUMENTATION_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}\n", encoding="utf-8")


def test_documentation_presence_includes_quickstart_testing_and_readme_refs(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Demo\n\n- [Quickstart](docs/quickstart.md)\n- [Testing](docs/testing.md)\n- [Ops](docs/ops.md)\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "ops.md").write_text("# Ops\n", encoding="utf-8")

    result = quality_gate.check_docs_presence(tmp_path)

    assert result.status == "pass"
    assert "docs/quickstart.md" in result.details["checked"]
    assert "docs/testing.md" in result.details["checked"]
    assert "docs/ops.md" in result.details["checked"]

    (tmp_path / "docs" / "testing.md").unlink()
    missing_result = quality_gate.check_docs_presence(tmp_path)

    assert missing_result.status == "fail"
    assert "docs/testing.md" in missing_result.details["missing"]


def test_documented_cli_examples_in_current_docs_parse() -> None:
    result = quality_gate.check_documented_cli_commands(Path.cwd())

    assert result.status == "pass"
    assert result.details["checked_command_count"] > 0
    assert result.details["invalid_command_count"] == 0


def test_documented_cli_examples_reject_unknown_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        quality_gate,
        "_extract_documented_cli_commands",
        lambda root: [
            {
                "file": "docs/usage.md",
                "line": 1,
                "command": "minicodex --definitely-not-a-real-doc-flag --root .",
                "args": ["--definitely-not-a-real-doc-flag", "--root", "."],
            }
        ],
    )

    result = quality_gate.check_documented_cli_commands(Path.cwd())

    assert result.status == "fail"
    assert result.details["invalid_command_count"] == 1
    assert "--definitely-not-a-real-doc-flag" in result.details["invalid_commands"][0]["command"]
