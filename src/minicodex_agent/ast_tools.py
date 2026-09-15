"""Python AST inspection and light refactor-analysis tools."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .fs_tools import is_probably_binary
from .safety import safe_resolve
from .utils import relative_posix, truncate


@dataclass
class SymbolInfo:
    """A discovered Python symbol."""

    kind: str
    name: str
    lineno: int
    end_lineno: int | None = None
    args: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    docstring: bool = False

    def render(self) -> str:
        """Return a concise human-readable line."""

        end = f"-{self.end_lineno}" if self.end_lineno and self.end_lineno != self.lineno else ""
        args = f"({', '.join(self.args)})" if self.args else ""
        decorators = f" decorators=[{', '.join(self.decorators)}]" if self.decorators else ""
        doc = " docstring=yes" if self.docstring else " docstring=no"
        return f"{self.kind:<14} L{self.lineno}{end:<6} {self.name}{args}{decorators}{doc}"


def _name_from_decorator(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse is normally available
        if isinstance(node, ast.Name):
            return node.id
        return node.__class__.__name__


def _args_from_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args: list[str] = []
    for arg in list(node.args.posonlyargs) + list(node.args.args):
        args.append(arg.arg)
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    for arg in node.args.kwonlyargs:
        args.append(arg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return args


def _iter_symbols(tree: ast.AST) -> Iterable[SymbolInfo]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            yield SymbolInfo(
                kind="class",
                name=node.name,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", None),
                decorators=[_name_from_decorator(dec) for dec in node.decorator_list],
                docstring=ast.get_docstring(node) is not None,
            )
        elif isinstance(node, ast.AsyncFunctionDef):
            yield SymbolInfo(
                kind="async_function",
                name=node.name,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", None),
                args=_args_from_node(node),
                decorators=[_name_from_decorator(dec) for dec in node.decorator_list],
                docstring=ast.get_docstring(node) is not None,
            )
        elif isinstance(node, ast.FunctionDef):
            yield SymbolInfo(
                kind="function",
                name=node.name,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", None),
                args=_args_from_node(node),
                decorators=[_name_from_decorator(dec) for dec in node.decorator_list],
                docstring=ast.get_docstring(node) is not None,
            )


def _import_lines(tree: ast.AST) -> list[str]:
    lines: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = ", ".join(
                alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
                for alias in node.names
            )
            lines.append(f"L{node.lineno}: import {names}")
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            names = ", ".join(
                alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
                for alias in node.names
            )
            lines.append(f"L{node.lineno}: from {module} import {names}")
    return lines


def _complexity_score(node: ast.AST) -> int:
    """Return a tiny cyclomatic-style score for prioritizing review targets."""

    branch_nodes = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.ExceptHandler,
        ast.BoolOp,
        ast.IfExp,
        ast.Match,
    )
    return 1 + sum(1 for child in ast.walk(node) if isinstance(child, branch_nodes))


def inspect_python_ast(root: Path, user_path: str, max_chars: int = 20000) -> str:
    """Inspect a Python file with AST and return symbols, imports, and review hints."""

    path = safe_resolve(root, user_path)
    if not path.exists():
        return f"Dosya bulunamadı: {user_path}"
    if not path.is_file():
        return f"Dosya değil: {user_path}"
    if path.suffix != ".py":
        return f"Python dosyası değil: {user_path}"
    if is_probably_binary(path):
        return f"Binary veya desteklenmeyen dosya atlandı: {user_path}"

    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=user_path)
    except SyntaxError as exc:
        return f"Python AST parse hatası: {user_path}:{exc.lineno}:{exc.offset}: {exc.msg}"

    symbols = sorted(_iter_symbols(tree), key=lambda item: (item.lineno, item.kind, item.name))
    imports = _import_lines(tree)
    module_doc = ast.get_docstring(tree) is not None

    complexity_rows: list[str] = []
    missing_docstrings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            score = _complexity_score(node)
            if score >= 6:
                complexity_rows.append(f"L{node.lineno}: {node.name} complexity~{score}")
            if not ast.get_docstring(node) and not node.name.startswith("_"):
                missing_docstrings.append(f"L{node.lineno}: {node.name}")

    output = [
        f"Python AST özeti: {user_path}",
        f"Module docstring: {'yes' if module_doc else 'no'}",
    ]
    output.append("\nImports:")
    output.extend(imports or ["- import yok"])
    output.append("\nSymbols:")
    output.extend(symbol.render() for symbol in symbols) if symbols else output.append(
        "- sembol yok"
    )
    output.append("\nReview hints:")
    if complexity_rows:
        output.append("Potentially complex blocks:")
        output.extend(f"- {row}" for row in complexity_rows[:20])
    else:
        output.append("- High-complexity block detected: no")
    if missing_docstrings:
        output.append("Public symbols without docstrings:")
        output.extend(f"- {row}" for row in missing_docstrings[:20])
    else:
        output.append("- Public docstring gaps detected: no")

    return truncate("\n".join(output), max_chars)


def find_python_symbol(
    root: Path, symbol_name: str, start_path: str = ".", max_matches: int = 50
) -> str:
    """Find Python class/function definitions by exact symbol name."""

    target = safe_resolve(root, start_path)
    if not target.exists():
        return f"Path bulunamadı: {start_path}"

    files = [target] if target.is_file() else sorted(target.rglob("*.py"))
    matches: list[str] = []

    for path in files:
        if len(matches) >= max_matches:
            break
        if is_probably_binary(path):
            continue
        try:
            rel = relative_posix(path, root)
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=str(rel))
        except (OSError, SyntaxError, ValueError):
            continue
        for symbol in _iter_symbols(tree):
            if symbol.name == symbol_name:
                matches.append(f"{rel}:L{symbol.lineno}: {symbol.kind} {symbol.name}")
                if len(matches) >= max_matches:
                    break

    return "\n".join(matches) if matches else f"Python sembolü bulunamadı: {symbol_name}"
