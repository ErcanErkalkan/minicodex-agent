from __future__ import annotations

from pathlib import Path

from minicodex_agent.config_tools import validate_config_file


def test_validate_config_file_json_passes(tmp_path: Path):
    target = tmp_path / "package.json"
    target.write_text('{"scripts": {"test": "pytest"}}', encoding="utf-8")

    result = validate_config_file(tmp_path, "package.json")

    assert "Detected format: json" in result
    assert "Status: PASS" in result


def test_validate_config_file_env_duplicate_key(tmp_path: Path):
    target = tmp_path / ".env.example"
    target.write_text("A=1\nA=2\n", encoding="utf-8")

    result = validate_config_file(tmp_path, ".env.example")

    assert "tekrar eden env anahtarı" in result
    assert "Status: CHECK" in result
