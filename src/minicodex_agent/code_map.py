"""Lightweight local code-map generation."""

from __future__ import annotations

from pathlib import Path

from .ast_tools import inspect_python_ast
from .safety import EXCLUDED_DIRS, EXCLUDED_FILE_SUFFIXES
from .utils import truncate


def build_code_map(
    root: Path, start_path: str = ".", max_files: int = 120, max_chars: int = 12000
) -> str:
    """Build a compact map of source files and Python symbols."""

    root = root.resolve()
    base = (root / start_path).resolve()
    if not base.exists():
        return f"Path not found: {start_path}"
    if root != base and root not in base.parents:
        return f"Path escapes project root: {start_path}"

    lines = ["Code map:"]
    count = 0
    iterator = [base] if base.is_file() else sorted(base.rglob("*"))
    for path in iterator:
        if count >= max_files:
            lines.append(f"... truncated after {max_files} files")
            break
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if set(rel.parts) & EXCLUDED_DIRS:
            continue
        if path.suffix.lower() in EXCLUDED_FILE_SUFFIXES:
            continue
        if path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs"}:
            continue
        count += 1
        lines.append(f"\n[{path.suffix.lower() or 'file'}] {rel}")
        if path.suffix.lower() == ".py":
            ast_result = inspect_python_ast(root, str(rel), max_chars=2000)
            for ast_line in ast_result.splitlines():
                if (
                    ast_line.startswith(("class", "function", "async_function", "Imports:"))
                    or " import " in ast_line
                ):
                    lines.append(f"  {ast_line}")
    return truncate("\n".join(lines), max_chars)
