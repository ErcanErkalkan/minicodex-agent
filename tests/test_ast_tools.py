from __future__ import annotations

from pathlib import Path

from minicodex_agent.ast_tools import find_python_symbol, inspect_python_ast


def test_inspect_python_ast_lists_symbols(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text(
        '"""module doc"""\n\nimport os\n\nclass Service:\n    def run(self, value):\n        if value:\n            return os.getcwd()\n        return ""\n',
        encoding="utf-8",
    )

    result = inspect_python_ast(tmp_path, "sample.py")

    assert "Python AST özeti" in result
    assert "class" in result
    assert "Service" in result
    assert "function" in result
    assert "run" in result


def test_find_python_symbol_finds_function(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("def target():\n    return 1\n", encoding="utf-8")

    result = find_python_symbol(tmp_path, "target")

    assert "pkg/mod.py" in result
    assert "function target" in result
