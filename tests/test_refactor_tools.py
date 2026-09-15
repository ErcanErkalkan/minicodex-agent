from __future__ import annotations

from pathlib import Path

from minicodex_agent.refactor_tools import rename_python_symbol


def test_rename_python_symbol_preview_does_not_change_strings_or_comments(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    original = (
        "# old_name should stay in comments\n"
        "old_name = 1\n"
        "text = 'old_name should stay in strings'\n"
        "print(old_name)\n"
    )
    path.write_text(original, encoding="utf-8")

    result = rename_python_symbol(
        tmp_path,
        "old_name",
        "new_name",
        preview_only=True,
    )

    assert "Python rename ÖNİZLEME" in result
    assert path.read_text(encoding="utf-8") == original
    assert "+new_name = 1" in result
    assert "old_name should stay in strings" in result


def test_rename_python_symbol_applies_token_changes(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text("old_name = 1\nprint(old_name)\n", encoding="utf-8")

    result = rename_python_symbol(tmp_path, "old_name", "new_name")

    assert "Python rename UYGULANDI" in result
    assert "new_name = 1" in path.read_text(encoding="utf-8")
    assert list(tmp_path.glob("sample.py.bak_*"))


def test_rename_python_symbol_rejects_invalid_identifier(tmp_path: Path) -> None:
    result = rename_python_symbol(tmp_path, "old-name", "new_name")

    assert "Geçersiz eski Python identifier" in result
