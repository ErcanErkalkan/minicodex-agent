"""Local lexical code search with context snippets."""

from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .fs_tools import is_probably_binary
from .safety import safe_resolve, should_skip_path
from .utils import truncate

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True)
class CodeSearchResult:
    """One ranked local search result."""

    path: str
    line: int
    score: float
    preview: str


def _split_identifier(token: str) -> list[str]:
    pieces: list[str] = []
    for part in token.replace("-", "_").split("_"):
        pieces.extend(CAMEL_RE.sub(" ", part).split())
    return [piece.lower() for piece in pieces if piece]


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase code-aware terms."""

    tokens: list[str] = []
    for match in TOKEN_RE.finditer(text):
        raw = match.group(0)
        lowered = raw.lower()
        tokens.append(lowered)
        tokens.extend(piece for piece in _split_identifier(raw) if piece != lowered)
    return tokens


def _score(query_terms: Counter[str], text_terms: Counter[str]) -> float:
    if not query_terms or not text_terms:
        return 0.0
    dot = sum(query_terms[term] * text_terms.get(term, 0) for term in query_terms)
    if dot == 0:
        return 0.0
    q_norm = math.sqrt(sum(value * value for value in query_terms.values()))
    t_norm = math.sqrt(sum(value * value for value in text_terms.values()))
    if q_norm == 0 or t_norm == 0:
        return 0.0
    return dot / (q_norm * t_norm)


def _candidate_files(root: Path, start_path: str) -> list[Path]:
    target = safe_resolve(root, start_path)
    if not target.exists():
        raise FileNotFoundError(f"Path bulunamadı: {start_path}")
    files = [target] if target.is_file() else sorted(target.rglob("*"))
    return [path for path in files if path.is_file() and not should_skip_path(path, root)]


def _snippet(lines: list[str], line_index: int, context_lines: int) -> str:
    start = max(0, line_index - context_lines)
    end = min(len(lines), line_index + context_lines + 1)
    rows: list[str] = []
    for idx in range(start, end):
        marker = ">" if idx == line_index else " "
        rows.append(f"{marker} L{idx + 1}: {lines[idx]}")
    return "\n".join(rows)


def search_code(
    root: Path,
    query: str,
    start_path: str = ".",
    max_matches: int = 20,
    context_lines: int = 2,
    max_chars: int = 16000,
) -> str:
    """Search code using token overlap and return ranked contextual snippets."""

    query_terms = Counter(tokenize(query))
    if not query_terms:
        return "Arama sorgusu boş veya geçersiz."

    results: list[CodeSearchResult] = []
    exact_query = query.lower().strip()

    for path in _candidate_files(root, start_path):
        if len(results) >= max_matches * 8:
            break
        if is_probably_binary(path):
            continue
        try:
            rel = str(path.relative_to(root))
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = text.splitlines()
        for idx, line in enumerate(lines):
            line_terms = Counter(tokenize(line))
            score = _score(query_terms, line_terms)
            lowered_line = line.lower()
            stripped = line.strip()
            if exact_query and exact_query in lowered_line:
                score += 1.0
            if re.match(r"^(?:async\s+)?def\s+|^class\s+", stripped) and any(
                term in lowered_line for term in query_terms
            ):
                score += 0.75
            if stripped.startswith(("import ", "from ")) and any(
                term in lowered_line for term in query_terms
            ):
                score += 0.35
            if any(term in rel.lower() for term in query_terms):
                score += 0.25
            if score <= 0:
                continue
            results.append(
                CodeSearchResult(
                    path=rel,
                    line=idx + 1,
                    score=score,
                    preview=_snippet(lines, idx, context_lines),
                )
            )

    results.sort(key=lambda item: (-item.score, item.path, item.line))
    if not results:
        return f"Kod aramasında eşleşme bulunamadı: {query}"

    rows: list[str] = [f"Kod arama sonucu: {query}", ""]
    for result in results[:max_matches]:
        rows.append(f"## {result.path}:L{result.line} score={result.score:.3f}")
        rows.append(result.preview)
        rows.append("")

    return truncate("\n".join(rows).rstrip(), max_chars)


def _python_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return sorted(imports)


def build_dependency_graph(
    root: Path, start_path: str = ".", max_files: int = 300, max_chars: int = 16000
) -> str:
    """Return a lightweight dependency/import graph for common source files."""

    graph: dict[str, list[str]] = {}
    files = _candidate_files(root, start_path)[:max_files]
    for path in files:
        if is_probably_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = str(path.relative_to(root))
        except OSError:
            continue
        deps: list[str] = []
        if path.suffix == ".py":
            deps = _python_imports(text)
        else:
            for line in text.splitlines()[:400]:
                m = (
                    re.search(r"import\s+.*?from\s+[\'\"]([^\'\"]+)[\'\"]", line)
                    or re.search(r"require\([\'\"]([^\'\"]+)[\'\"]\)", line)
                    or re.search(r"^\s*import\s+([A-Za-z0-9_.]+);", line)
                )
                if m:
                    deps.append(m.group(1).split("/")[0].split(".")[0])
        if deps:
            graph[rel] = sorted(set(deps))

    if not graph:
        return "No import/dependency edges found."
    return truncate(json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True), max_chars)
