from __future__ import annotations

from pathlib import Path

from minicodex_agent.code_search import search_code, tokenize


def test_tokenize_splits_snake_and_camel_case() -> None:
    tokens = tokenize("rename_python_symbol MiniCodexAgent")

    assert "rename" in tokens
    assert "python" in tokens
    assert "symbol" in tokens
    assert "mini" in tokens
    assert "codex" in tokens
    assert "agent" in tokens


def test_search_code_returns_ranked_context(tmp_path: Path) -> None:
    file_path = tmp_path / "agent.py"
    file_path.write_text(
        "def rename_python_symbol(old_name, new_name):\n    return old_name + new_name\n",
        encoding="utf-8",
    )

    result = search_code(tmp_path, "rename python symbol", max_matches=3)

    assert "agent.py:L1" in result
    assert "rename_python_symbol" in result
