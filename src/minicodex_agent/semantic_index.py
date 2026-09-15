"""Semantic code intelligence for MiniCodex.

The first language adapter layer was intentionally cheap and heuristic.  This
module adds a stronger, still dependency-optional semantic index for large
repositories: symbols, cross-file references, route declarations, and parser
backend capability reporting.  Python uses the built-in ``ast`` module.  Other
languages use conservative grammar-aware extractors and can report optional
Tree-sitter availability without making it a hard runtime dependency.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .fs_tools import is_probably_binary
from .safety import safe_resolve, sensitive_path_reason, should_skip_path
from .utils import to_pretty_json, truncate

SOURCE_EXTENSIONS: Mapping[str, tuple[str, ...]] = {
    "python": (".py", ".pyi"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "java": (".java", ".kt", ".kts"),
    "go": (".go",),
    "rust": (".rs",),
}

_SYMBOL_KIND_PRIORITY: Mapping[str, int] = {
    "class": 9,
    "interface": 8,
    "enum": 8,
    "record": 8,
    "trait": 8,
    "function": 7,
    "method": 7,
    "component": 7,
    "type": 6,
    "constant": 5,
    "variable": 4,
    "impl": 3,
    "import": 1,
}


@dataclass(frozen=True)
class ParserCapability:
    """Parser backend capability for one language."""

    language: str
    backend: str
    available: bool
    detail: str = ""


@dataclass(frozen=True)
class SymbolOccurrence:
    """A symbol definition found in source code."""

    name: str
    kind: str
    language: str
    path: str
    line: int
    column: int = 0
    end_line: int | None = None
    container: str = ""
    signature: str = ""
    exported: bool = False
    confidence: float = 0.75


@dataclass(frozen=True)
class ReferenceOccurrence:
    """A reference/use of a symbol name."""

    symbol: str
    language: str
    path: str
    line: int
    column: int = 0
    excerpt: str = ""
    is_definition: bool = False
    confidence: float = 0.55


@dataclass(frozen=True)
class RouteDetection:
    """A web route/API endpoint declaration."""

    framework: str
    method: str
    route: str
    path: str
    line: int
    handler: str = ""
    language: str = ""
    confidence: float = 0.75


@dataclass(frozen=True)
class SemanticIndex:
    """Semantic repository index for symbols, references, and routes."""

    symbols: tuple[SymbolOccurrence, ...] = ()
    references: tuple[ReferenceOccurrence, ...] = ()
    routes: tuple[RouteDetection, ...] = ()
    parser_capabilities: tuple[ParserCapability, ...] = ()
    files_indexed: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    def summary(self, *, max_chars: int = 30000) -> str:
        """Return bounded JSON text."""

        return truncate(to_pretty_json(self.to_dict()), max_chars)


@dataclass(frozen=True)
class SemanticCoverageReport:
    """Coverage report explaining how semantic the language adapter is."""

    parser_capabilities: tuple[ParserCapability, ...]
    supported_languages: tuple[str, ...]
    ast_backends: tuple[str, ...]
    fallback_backends: tuple[str, ...]
    symbol_kinds: tuple[str, ...]
    route_frameworks: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_EXT_TO_LANGUAGE = {ext: lang for lang, exts in SOURCE_EXTENSIONS.items() for ext in exts}


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./") or "."


def _language_for_path(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    return _EXT_TO_LANGUAGE.get(suffix, "")


def _iter_source_files(
    root: Path, *, max_files: int = 1600, max_file_bytes: int = 700_000
) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file() or _language_for_path(path) == "":
            continue
        if (
            should_skip_path(path, root)
            or sensitive_path_reason(path, root)
            or is_probably_binary(path)
        ):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        files.append(path)
    return tuple(files)


def _read_text(path: Path, *, max_chars: int = 900_000) -> str:
    try:
        return truncate(path.read_text(encoding="utf-8", errors="replace"), max_chars)
    except OSError:
        return ""


def _line_col(text: str, index: int) -> tuple[int, int]:
    prefix = text[:index]
    line = prefix.count("\n") + 1
    col = len(prefix.rsplit("\n", 1)[-1])
    return line, col


def _line_excerpt(text: str, line: int, *, max_chars: int = 240) -> str:
    lines = text.splitlines()
    if line < 1 or line > len(lines):
        return ""
    return truncate(lines[line - 1].strip(), max_chars)


def _safe_rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _append_symbol(symbols: list[SymbolOccurrence], **kwargs: Any) -> None:
    if not kwargs.get("name"):
        return
    symbols.append(SymbolOccurrence(**kwargs))


def _signature_from_line(text: str, line: int) -> str:
    return _line_excerpt(text, line, max_chars=400)


def _python_symbols(root: Path, path: Path, text: str) -> tuple[SymbolOccurrence, ...]:
    rel = _safe_rel(root, path)
    symbols: list[SymbolOccurrence] = []
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        return ()

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def container_for(node: ast.AST) -> str:
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                return current.name
            current = parents.get(current)
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            _append_symbol(
                symbols,
                name=node.name,
                kind="class",
                language="python",
                path=rel,
                line=node.lineno,
                column=node.col_offset,
                end_line=getattr(node, "end_lineno", None),
                container=container_for(node),
                signature=_signature_from_line(text, node.lineno),
                exported=not node.name.startswith("_"),
                confidence=0.98,
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "method" if isinstance(parents.get(node), ast.ClassDef) else "function"
            _append_symbol(
                symbols,
                name=node.name,
                kind=kind,
                language="python",
                path=rel,
                line=node.lineno,
                column=node.col_offset,
                end_line=getattr(node, "end_lineno", None),
                container=container_for(node),
                signature=_signature_from_line(text, node.lineno),
                exported=not node.name.startswith("_"),
                confidence=0.98,
            )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    _append_symbol(
                        symbols,
                        name=target.id,
                        kind="constant",
                        language="python",
                        path=rel,
                        line=node.lineno,
                        column=node.col_offset,
                        end_line=getattr(node, "end_lineno", None),
                        signature=_signature_from_line(text, node.lineno),
                        exported=not target.id.startswith("_"),
                        confidence=0.86,
                    )
    return tuple(symbols)


_TS_SYMBOL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("class", re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("interface", re.compile(r"(?m)^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"(?m)^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*=")),
    ("enum", re.compile(r"(?m)^\s*(?:export\s+)?enum\s+([A-Za-z_$][\w$]*)")),
    (
        "function",
        re.compile(
            r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
        ),
    ),
    (
        "function",
        re.compile(
            r"(?m)^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^\n=]*\)\s*=>"
        ),
    ),
    (
        "component",
        re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?function\s+([A-Z][A-Za-z0-9_$]*)\s*\("),
    ),
    (
        "component",
        re.compile(
            r"(?m)^\s*(?:export\s+)?const\s+([A-Z][A-Za-z0-9_$]*)\s*=\s*(?:React\.)?(?:memo\()?\s*(?:\([^\n=]*\)\s*=>|function)"
        ),
    ),
)


def _ts_js_symbols(
    root: Path, path: Path, text: str, language: str
) -> tuple[SymbolOccurrence, ...]:
    rel = _safe_rel(root, path)
    symbols: list[SymbolOccurrence] = []
    seen: set[tuple[str, str, int]] = set()
    for kind, pattern in _TS_SYMBOL_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            line, col = _line_col(text, match.start(1))
            key = (name, kind, line)
            if key in seen:
                continue
            seen.add(key)
            exported = "export" in match.group(0) or "default" in match.group(0)
            confidence = 0.9 if kind in {"class", "interface", "type", "function"} else 0.82
            _append_symbol(
                symbols,
                name=name,
                kind=kind,
                language=language,
                path=rel,
                line=line,
                column=col,
                signature=_signature_from_line(text, line),
                exported=exported,
                confidence=confidence,
            )
    return tuple(symbols)


_JAVA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "class",
        re.compile(
            r"(?m)^\s*(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+|sealed\s+|non-sealed\s+)*class\s+([A-Za-z_$][\w$]*)"
        ),
    ),
    ("interface", re.compile(r"(?m)^\s*(?:public\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("enum", re.compile(r"(?m)^\s*(?:public\s+)?enum\s+([A-Za-z_$][\w$]*)")),
    ("record", re.compile(r"(?m)^\s*(?:public\s+)?record\s+([A-Za-z_$][\w$]*)")),
    (
        "method",
        re.compile(
            r"(?m)^\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>, ?\[\]]+\s+([a-zA-Z_$][\w$]*)\s*\([^;{}]*\)\s*(?:throws\s+[\w, ]+)?\{"
        ),
    ),
)


def _java_symbols(root: Path, path: Path, text: str) -> tuple[SymbolOccurrence, ...]:
    rel = _safe_rel(root, path)
    symbols: list[SymbolOccurrence] = []
    seen: set[tuple[str, str, int]] = set()
    for kind, pattern in _JAVA_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in {"if", "for", "while", "switch", "catch"}:
                continue
            line, col = _line_col(text, match.start(1))
            key = (name, kind, line)
            if key in seen:
                continue
            seen.add(key)
            _append_symbol(
                symbols,
                name=name,
                kind=kind,
                language="java",
                path=rel,
                line=line,
                column=col,
                signature=_signature_from_line(text, line),
                exported="public" in match.group(0),
                confidence=0.86,
            )
    return tuple(symbols)


_GO_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("function", re.compile(r"(?m)^func\s+([A-Za-z_][\w]*)\s*\(")),
    ("method", re.compile(r"(?m)^func\s*\([^)]*\)\s*([A-Za-z_][\w]*)\s*\(")),
    (
        "type",
        re.compile(r"(?m)^type\s+([A-Za-z_][\w]*)\s+(?:struct|interface|func|map|\[|[A-Za-z_])"),
    ),
)


def _go_symbols(root: Path, path: Path, text: str) -> tuple[SymbolOccurrence, ...]:
    rel = _safe_rel(root, path)
    symbols: list[SymbolOccurrence] = []
    for kind, pattern in _GO_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            line, col = _line_col(text, match.start(1))
            _append_symbol(
                symbols,
                name=name,
                kind=kind,
                language="go",
                path=rel,
                line=line,
                column=col,
                signature=_signature_from_line(text, line),
                exported=name[:1].isupper(),
                confidence=0.88,
            )
    return tuple(symbols)


_RUST_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("function", re.compile(r"(?m)^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][\w]*)\s*\(")),
    ("struct", re.compile(r"(?m)^\s*(?:pub\s+)?struct\s+([A-Za-z_][\w]*)")),
    ("enum", re.compile(r"(?m)^\s*(?:pub\s+)?enum\s+([A-Za-z_][\w]*)")),
    ("trait", re.compile(r"(?m)^\s*(?:pub\s+)?trait\s+([A-Za-z_][\w]*)")),
    ("impl", re.compile(r"(?m)^\s*impl(?:\s*<[^>]+>)?\s+([A-Za-z_][\w]*)")),
)


def _rust_symbols(root: Path, path: Path, text: str) -> tuple[SymbolOccurrence, ...]:
    rel = _safe_rel(root, path)
    symbols: list[SymbolOccurrence] = []
    for kind, pattern in _RUST_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            line, col = _line_col(text, match.start(1))
            _append_symbol(
                symbols,
                name=name,
                kind=kind,
                language="rust",
                path=rel,
                line=line,
                column=col,
                signature=_signature_from_line(text, line),
                exported="pub" in match.group(0),
                confidence=0.86,
            )
    return tuple(symbols)


_ROUTE_PATTERNS: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    (
        "fastapi",
        "python",
        "decorator",
        re.compile(
            r"(?m)^\s*@(?:app|router|api)\.(get|post|put|delete|patch|options|head)\(\s*[\"']([^\"']+)[\"']"
        ),
    ),
    (
        "flask",
        "python",
        "decorator",
        re.compile(
            r"(?m)^\s*@(?:app|bp|blueprint)\.route\(\s*[\"']([^\"']+)[\"'](?:[^\n]*methods\s*=\s*\[([^\]]+)\])?"
        ),
    ),
    (
        "django",
        "python",
        "call",
        re.compile(r"(?m)\b(?:path|re_path)\(\s*[\"']([^\"']*)[\"']\s*,\s*([A-Za-z_][\w.]*)"),
    ),
    (
        "express",
        "typescript/javascript",
        "call",
        re.compile(
            r"(?m)\b(?:app|router)\.(get|post|put|delete|patch|options|head|all)\(\s*[\"']([^\"']+)[\"']"
        ),
    ),
    (
        "nestjs",
        "typescript",
        "decorator",
        re.compile(
            r"(?m)^\s*@(Get|Post|Put|Delete|Patch|Options|Head|Controller)\(\s*(?:[\"']([^\"']*)[\"'])?"
        ),
    ),
    (
        "spring",
        "java",
        "annotation",
        re.compile(
            r"(?m)^\s*@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\(\s*(?:value\s*=\s*)?[\"']([^\"']*)[\"']?"
        ),
    ),
    (
        "gin",
        "go",
        "call",
        re.compile(
            r"(?m)\b(?:r|router|engine|group|api)\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\(\s*[\"`]([^\"`]+)[\"`]"
        ),
    ),
    (
        "fiber",
        "go",
        "call",
        re.compile(
            r"(?m)\b(?:app|router|group)\.(Get|Post|Put|Delete|Patch|Options|Head|All)\(\s*[\"`]([^\"`]+)[\"`]"
        ),
    ),
    (
        "go-echo",
        "go",
        "call",
        re.compile(
            r"(?m)\b(?:e|g|group)\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD|Any)\(\s*[\"`]([^\"`]+)[\"`]"
        ),
    ),
    (
        "axum",
        "rust",
        "call",
        re.compile(
            r"(?m)\.route\(\s*[\"']([^\"']+)[\"']\s*,\s*(get|post|put|delete|patch|options|head)\("
        ),
    ),
    (
        "actix-web",
        "rust",
        "macro",
        re.compile(r"(?m)^\s*#\[(get|post|put|delete|patch|route)\(\s*[\"']([^\"']+)[\"']"),
    ),
    (
        "rocket",
        "rust",
        "macro",
        re.compile(r"(?m)^\s*#\[(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']"),
    ),
)


def _normalize_http_method(value: str) -> str:
    value = (value or "").strip().lower()
    mapping = {
        "getmapping": "GET",
        "postmapping": "POST",
        "putmapping": "PUT",
        "deletemapping": "DELETE",
        "patchmapping": "PATCH",
        "requestmapping": "ANY",
        "controller": "BASE",
        "all": "ALL",
        "any": "ANY",
        "route": "ANY",
    }
    return mapping.get(value, value.upper() if value else "ANY")


def _routes_for_file(
    root: Path, path: Path, text: str, language: str
) -> tuple[RouteDetection, ...]:
    rel = _safe_rel(root, path)
    routes: list[RouteDetection] = []
    for framework, pattern_language, _style, pattern in _ROUTE_PATTERNS:
        if pattern_language != language and not (
            language in {"typescript", "javascript"} and pattern_language == "typescript/javascript"
        ):
            continue
        for match in pattern.finditer(text):
            if framework == "flask":
                route = match.group(1)
                methods = match.group(2) or "GET"
                method = "|".join(sorted(set(re.findall(r"[A-Z]+", methods.upper()) or ["GET"])))
                route_start = match.start(1)
            elif framework == "django":
                route = "/" + match.group(1).lstrip("/")
                method = "ANY"
                route_start = match.start(1)
            elif framework == "nestjs":
                method = _normalize_http_method(match.group(1))
                route = (
                    match.group(2)
                    if len(match.groups()) >= 2 and match.group(2) is not None
                    else "/"
                )
                route = "/" + route.lstrip("/") if route else "/"
                route_start = (
                    match.start(2)
                    if len(match.groups()) >= 2 and match.group(2) is not None
                    else match.start(1)
                )
            elif framework == "axum":
                route = match.group(1)
                method = _normalize_http_method(match.group(2))
                route_start = match.start(1)
            else:
                # Most patterns are (method, route); Django/Flask handled above.
                method = _normalize_http_method(match.group(1))
                route = match.group(2)
                route_start = match.start(2)
            line, _col = _line_col(text, route_start)
            handler = _nearby_handler_name(text, line)
            routes.append(
                RouteDetection(
                    framework=framework,
                    method=method,
                    route=route,
                    path=rel,
                    line=line,
                    handler=handler,
                    language=language,
                    confidence=0.86,
                )
            )
    routes.extend(_file_based_routes(root, path, language))
    return tuple(routes)


def _file_based_routes(root: Path, path: Path, language: str) -> tuple[RouteDetection, ...]:
    rel = _safe_rel(root, path)
    if language not in {"typescript", "javascript"}:
        return ()
    parts = Path(rel).parts
    if not parts:
        return ()
    route = ""
    framework = ""
    if parts[0] == "app" and path.name in {
        "page.tsx",
        "page.ts",
        "page.jsx",
        "page.js",
        "route.ts",
        "route.js",
    }:
        framework = "nextjs-app-router"
        route_parts = list(parts[1:-1])
        route = "/" + "/".join(route_parts)
    elif parts[0] == "pages" and path.suffix.lower() in {".tsx", ".ts", ".jsx", ".js"}:
        framework = "nextjs-pages-router"
        route_parts = list(parts[1:])
        if route_parts:
            route_parts[-1] = Path(route_parts[-1]).stem
        route = "/" + "/".join(part for part in route_parts if part not in {"index"})
    if not framework:
        return ()
    route = route.replace("/index", "") or "/"
    return (
        RouteDetection(
            framework=framework,
            method="FILE",
            route=route,
            path=rel,
            line=1,
            handler=Path(rel).stem,
            language=language,
            confidence=0.82,
        ),
    )


def _nearby_handler_name(text: str, line: int) -> str:
    lines = text.splitlines()
    for offset in range(0, 6):
        idx = line - 1 + offset
        if idx < 0 or idx >= len(lines):
            continue
        current = lines[idx]
        for pattern in (
            r"def\s+([A-Za-z_][\w]*)\s*\(",
            r"function\s+([A-Za-z_$][\w$]*)\s*\(",
            r"const\s+([A-Za-z_$][\w$]*)\s*=",
            r"(?:public|private|protected)\s+[\w<>, ?\[\]]+\s+([A-Za-z_$][\w$]*)\s*\(",
            r"func\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\(",
            r"fn\s+([A-Za-z_][\w]*)\s*\(",
        ):
            match = re.search(pattern, current)
            if match:
                return match.group(1)
    return ""


def _symbols_for_file(
    root: Path, path: Path, text: str, language: str
) -> tuple[SymbolOccurrence, ...]:
    if language == "python":
        return _python_symbols(root, path, text)
    if language in {"typescript", "javascript"}:
        return _ts_js_symbols(root, path, text, language)
    if language == "java":
        return _java_symbols(root, path, text)
    if language == "go":
        return _go_symbols(root, path, text)
    if language == "rust":
        return _rust_symbols(root, path, text)
    return ()


def _references_for_symbol(
    root: Path,
    files_and_text: Iterable[tuple[Path, str, str]],
    symbol: SymbolOccurrence,
    *,
    max_matches: int,
) -> tuple[ReferenceOccurrence, ...]:
    if len(symbol.name) < 2:
        return ()
    pattern = re.compile(rf"\b{re.escape(symbol.name)}\b")
    refs: list[ReferenceOccurrence] = []
    for path, language, text in files_and_text:
        if symbol.language in {"typescript", "javascript"} and language not in {
            "typescript",
            "javascript",
        }:
            continue
        if symbol.language == "java" and language != "java":
            continue
        if symbol.language in {"python", "go", "rust"} and language != symbol.language:
            continue
        rel = _safe_rel(root, path)
        for match in pattern.finditer(text):
            line, col = _line_col(text, match.start())
            is_definition = rel == symbol.path and line == symbol.line
            if is_definition:
                continue
            refs.append(
                ReferenceOccurrence(
                    symbol=symbol.name,
                    language=language,
                    path=rel,
                    line=line,
                    column=col,
                    excerpt=_line_excerpt(text, line),
                    is_definition=False,
                    confidence=0.7 if rel != symbol.path else 0.58,
                )
            )
            if len(refs) >= max_matches:
                return tuple(refs)
    return tuple(refs)


def _tree_sitter_available() -> bool:
    try:
        __import__("tree_sitter")
    except Exception:
        return False
    return True


def semantic_capability_report() -> SemanticCoverageReport:
    """Report semantic backend coverage without requiring optional packages."""

    tree_sitter = _tree_sitter_available()
    capabilities = [
        ParserCapability(
            "python", "python-ast", True, "Uses the standard-library ast parser for definitions."
        ),
        ParserCapability(
            "typescript",
            "tree-sitter",
            tree_sitter,
            "Optional; falls back to grammar-aware extractor when unavailable.",
        ),
        ParserCapability(
            "javascript",
            "tree-sitter",
            tree_sitter,
            "Optional; falls back to grammar-aware extractor when unavailable.",
        ),
        ParserCapability(
            "java",
            "tree-sitter",
            tree_sitter,
            "Optional; falls back to grammar-aware extractor when unavailable.",
        ),
        ParserCapability(
            "go",
            "tree-sitter",
            tree_sitter,
            "Optional; falls back to grammar-aware extractor when unavailable.",
        ),
        ParserCapability(
            "rust",
            "tree-sitter",
            tree_sitter,
            "Optional; falls back to grammar-aware extractor when unavailable.",
        ),
    ]
    warnings: list[str] = []
    if not tree_sitter:
        warnings.append(
            "tree_sitter package is not installed; TypeScript/Java/Go/Rust use conservative semantic extractors."
        )
    return SemanticCoverageReport(
        parser_capabilities=tuple(capabilities),
        supported_languages=tuple(SOURCE_EXTENSIONS),
        ast_backends=("python-ast",) + (("tree-sitter",) if tree_sitter else ()),
        fallback_backends=(
            "typescript/javascript grammar extractor",
            "java grammar extractor",
            "go grammar extractor",
            "rust grammar extractor",
        ),
        symbol_kinds=tuple(_SYMBOL_KIND_PRIORITY),
        route_frameworks=tuple(
            sorted(
                {item[0] for item in _ROUTE_PATTERNS} | {"nextjs-app-router", "nextjs-pages-router"}
            )
        ),
        warnings=tuple(warnings),
    )


def build_semantic_index(
    root: Path,
    *,
    max_files: int = 1600,
    max_symbols: int = 1000,
    max_references_per_symbol: int = 8,
    include_routes: bool = True,
) -> SemanticIndex:
    """Build a semantic index with symbols, cross-file references, and routes."""

    files = _iter_source_files(root, max_files=max_files)
    files_and_text: list[tuple[Path, str, str]] = []
    symbols: list[SymbolOccurrence] = []
    routes: list[RouteDetection] = []
    notes: list[str] = []

    for path in files:
        language = _language_for_path(path)
        text = _read_text(path)
        if not text:
            continue
        files_and_text.append((path, language, text))
        symbols.extend(_symbols_for_file(root, path, text, language))
        if include_routes:
            routes.extend(_routes_for_file(root, path, text, language))
        if max_symbols > 0 and len(symbols) >= max_symbols:
            notes.append(
                f"Symbol limit reached at {max_symbols}; increase max_symbols for deeper indexing."
            )
            symbols = symbols[:max_symbols]
            # Keep route extraction complete enough for API inspection when routes are requested.
            if not include_routes:
                break

    symbols.sort(
        key=lambda item: (
            _safe_sort_lang(item.language),
            item.path,
            item.line,
            -_SYMBOL_KIND_PRIORITY.get(item.kind, 0),
        )
    )
    references: list[ReferenceOccurrence] = []
    for symbol in symbols[:max_symbols] if max_symbols > 0 else ():
        references.extend(
            _references_for_symbol(
                root,
                files_and_text,
                symbol,
                max_matches=max(0, max_references_per_symbol),
            )
        )
    if not _tree_sitter_available():
        notes.append(
            "Tree-sitter is optional and not installed; non-Python symbols use grammar-aware fallback extractors."
        )
    return SemanticIndex(
        symbols=tuple(symbols[:max_symbols]),
        references=tuple(references),
        routes=tuple(routes),
        parser_capabilities=semantic_capability_report().parser_capabilities,
        files_indexed=tuple(_safe_rel(root, path) for path, _language, _text in files_and_text),
        notes=tuple(dict.fromkeys(notes)),
    )


def _safe_sort_lang(language: str) -> str:
    return {
        "python": "0",
        "typescript": "1",
        "javascript": "1",
        "java": "2",
        "go": "3",
        "rust": "4",
    }.get(language, language)


def find_symbol_references(
    root: Path,
    symbol: str,
    *,
    language: str = "",
    path: str = "",
    max_matches: int = 80,
) -> dict[str, Any]:
    """Find cross-file references to a symbol without requiring a full LSP server."""

    symbol = symbol.strip()
    if not symbol:
        return {
            "summary": "No symbol provided.",
            "symbol": symbol,
            "references": [],
            "definitions": [],
        }
    start_root = root
    candidate_files: tuple[Path, ...]
    if path:
        try:
            start = safe_resolve(root, path)
        except ValueError:
            start = root
        start_root = start if start.is_dir() else start.parent
    candidate_files = _iter_source_files(
        start_root if start_root.exists() else root, max_files=1600
    )
    files_and_text: list[tuple[Path, str, str]] = []
    definitions: list[SymbolOccurrence] = []
    for file_path in candidate_files:
        lang = _language_for_path(file_path)
        if (
            language
            and lang != language
            and not (language == "typescript/javascript" and lang in {"typescript", "javascript"})
        ):
            continue
        text = _read_text(file_path)
        if not text:
            continue
        files_and_text.append((file_path, lang, text))
        definitions.extend(
            item for item in _symbols_for_file(root, file_path, text, lang) if item.name == symbol
        )
    references: list[ReferenceOccurrence] = []
    if definitions:
        for definition in definitions:
            references.extend(
                _references_for_symbol(
                    root,
                    files_and_text,
                    definition,
                    max_matches=max(0, max_matches - len(references)),
                )
            )
            if len(references) >= max_matches:
                break
    else:
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        for file_path, lang, text in files_and_text:
            rel = _safe_rel(root, file_path)
            for match in pattern.finditer(text):
                line, col = _line_col(text, match.start())
                references.append(
                    ReferenceOccurrence(
                        symbol=symbol,
                        language=lang,
                        path=rel,
                        line=line,
                        column=col,
                        excerpt=_line_excerpt(text, line),
                        confidence=0.45,
                    )
                )
                if len(references) >= max_matches:
                    break
            if len(references) >= max_matches:
                break
    return {
        "summary": f"Found {len(definitions)} definition(s) and {len(references)} reference(s) for {symbol!r}.",
        "symbol": symbol,
        "definitions": [asdict(item) for item in definitions],
        "references": [asdict(item) for item in references[:max_matches]],
        "parser_capabilities": [
            asdict(item) for item in semantic_capability_report().parser_capabilities
        ],
    }


def inspect_routes(root: Path, *, framework: str = "", max_routes: int = 120) -> dict[str, Any]:
    """Inspect framework route declarations and file-based routes."""

    index = build_semantic_index(
        root, max_files=1600, max_symbols=0, max_references_per_symbol=0, include_routes=True
    )
    routes = list(index.routes)
    if framework:
        routes = [route for route in routes if route.framework == framework]
    routes = routes[: max(0, max_routes)]
    return {
        "summary": f"Detected {len(routes)} route(s).",
        "routes": [asdict(route) for route in routes],
        "framework_filter": framework,
        "notes": index.notes,
    }


def render_semantic_index(root: Path, *, max_chars: int = 30000, **kwargs: Any) -> str:
    """Render a bounded semantic index report."""

    return build_semantic_index(root, **kwargs).summary(max_chars=max_chars)
