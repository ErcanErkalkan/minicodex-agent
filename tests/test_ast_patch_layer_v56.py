import json

from minicodex_agent.ast_patch_tools import (
    ast_patch_capability_report,
    cleanup_dead_code,
    detect_dead_code,
    format_and_verify,
    organize_imports,
    plan_semantic_edit,
    rename_symbol_semantic,
)
from minicodex_agent.tool_registry import get_tool_registry


def _json(text: str):
    return json.loads(text)


def test_ast_patch_tools_are_registered():
    registry = get_tool_registry()
    for name in [
        "ast_patch_capability_report",
        "plan_semantic_edit",
        "rename_symbol_semantic",
        "organize_imports",
        "detect_dead_code",
        "cleanup_dead_code",
        "format_and_verify",
    ]:
        assert name in registry


def test_ast_capability_report_is_structured(tmp_path):
    data = _json(ast_patch_capability_report(tmp_path))
    assert data["summary"].startswith("AST-aware")
    names = {item["name"] for item in data["capabilities"]}
    assert "python-ast" in names
    assert "libcst" in names


def test_plan_semantic_edit_recommends_semantic_rename(tmp_path):
    (tmp_path / "app.py").write_text("def old_name():\n    return 1\n", encoding="utf-8")
    data = _json(
        plan_semantic_edit(
            tmp_path, operation="rename_symbol", symbol="old_name", new_name="new_name"
        )
    )
    assert data["ok"] is True
    assert "rename_symbol_semantic" in data["recommended_tools"]


def test_python_semantic_rename_skips_strings_and_comments(tmp_path):
    path = tmp_path / "app.py"
    path.write_text(
        "def old_name():\n"
        "    text = 'old_name should stay in string'\n"
        "    # old_name should stay in comment\n"
        "    return old_name.__name__\n",
        encoding="utf-8",
    )
    result = _json(
        rename_symbol_semantic(
            tmp_path,
            old_name="old_name",
            new_name="new_name",
            language="python",
            preview_only=False,
        )
    )
    assert result["ok"] is True
    text = path.read_text(encoding="utf-8")
    assert "def new_name" in text
    assert "return new_name.__name__" in text
    assert "old_name should stay in string" in text
    assert "old_name should stay in comment" in text


def test_typescript_semantic_rename_skips_string_and_comment(tmp_path):
    path = tmp_path / "widget.ts"
    path.write_text(
        "const oldName = 1;\n"
        "// oldName in comment\n"
        "const s = 'oldName in string';\n"
        "export function get() { return oldName; }\n",
        encoding="utf-8",
    )
    result = _json(
        rename_symbol_semantic(
            tmp_path,
            old_name="oldName",
            new_name="newName",
            language="typescript",
            preview_only=False,
        )
    )
    assert result["ok"] is True
    text = path.read_text(encoding="utf-8")
    assert "const newName = 1" in text
    assert "return newName" in text
    assert "// oldName in comment" in text
    assert "'oldName in string'" in text


def test_organize_python_imports_preview_and_apply(tmp_path):
    path = tmp_path / "app.py"
    path.write_text(
        "import zlib\nimport os\nfrom b import c\nfrom a import b\n\nprint(os.name)\n",
        encoding="utf-8",
    )
    preview = _json(organize_imports(tmp_path, path="app.py", language="python", preview_only=True))
    assert preview["mode"] == "preview"
    assert "import os" in preview["changes"][0]["diff"]
    applied = _json(
        organize_imports(tmp_path, path="app.py", language="python", preview_only=False)
    )
    assert applied["ok"] is True
    text = path.read_text(encoding="utf-8")
    assert text.index("import os") < text.index("import zlib")
    assert text.index("from a import b") < text.index("from b import c")


def test_detect_and_cleanup_private_python_dead_code(tmp_path):
    path = tmp_path / "app.py"
    path.write_text(
        "def _unused():\n    return 1\n\ndef used():\n    return 2\n\nprint(used())\n",
        encoding="utf-8",
    )
    detected = _json(detect_dead_code(tmp_path, language="python"))
    names = {item["name"] for item in detected["candidates"]}
    assert "_unused" in names
    result = _json(cleanup_dead_code(tmp_path, names=("_unused",), preview_only=False))
    assert result["ok"] is True
    assert "def _unused" not in path.read_text(encoding="utf-8")


def test_format_and_verify_python_syntax_without_formatter(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("x = 1\n", encoding="utf-8")
    data = _json(
        format_and_verify(tmp_path, path="app.py", run_formatter=False, verify_syntax=True)
    )
    assert data["ok"] is True
    assert data["syntax_ok"] is True
