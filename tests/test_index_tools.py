from pathlib import Path

from minicodex_agent.index_tools import build_project_index, read_many_files, search_text


def test_build_project_index_extracts_python_symbols(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("class Service:\n    pass\n\ndef run():\n    return 1\n", encoding="utf-8")

    index = build_project_index(tmp_path)

    assert len(index.files) == 1
    symbols = {(symbol.kind, symbol.name) for symbol in index.files[0].symbols}
    assert ("class", "Service") in symbols
    assert ("function", "run") in symbols


def test_search_text_returns_line_numbers(tmp_path: Path):
    (tmp_path / "README.md").write_text("hello\nMiniCodex agent\n", encoding="utf-8")

    result = search_text(tmp_path, "minicodex")

    assert "README.md:2" in result


def test_read_many_files_combines_sections(tmp_path: Path):
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")

    result = read_many_files(tmp_path, ["a.txt", "b.txt"])

    assert "===== a.txt =====" in result
    assert "alpha" in result
    assert "===== b.txt =====" in result
    assert "beta" in result
