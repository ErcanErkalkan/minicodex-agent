"""Project indexing and text-search tools."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .fs_tools import is_probably_binary, read_file
from .safety import safe_resolve, should_skip_path
from .utils import truncate

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c/c++ header",
    ".cpp": "c++",
    ".cc": "c++",
    ".hpp": "c++ header",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".md": "markdown",
    ".toml": "toml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
}


@dataclass
class IndexedSymbol:
    """A lightweight symbol discovered in a source file."""

    kind: str
    name: str
    line: int


@dataclass
class IndexedFile:
    """A lightweight file record used by the coding agent."""

    path: str
    language: str
    size_bytes: int
    line_count: int
    symbols: list[IndexedSymbol] = field(default_factory=list)


@dataclass
class ProjectIndex:
    """Serializable project index."""

    files: list[IndexedFile] = field(default_factory=list)
    skipped_files: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)

    def summary(self, max_files: int = 80) -> str:
        """Return a compact human-readable summary."""

        language_counts: dict[str, int] = {}
        for item in self.files:
            language_counts[item.language] = language_counts.get(item.language, 0) + 1

        rows = [
            f"Indexed files: {len(self.files)}",
            f"Skipped files: {self.skipped_files}",
            f"Truncated: {self.truncated}",
            "Languages: " + json.dumps(language_counts, ensure_ascii=False, sort_keys=True),
            "",
            "Key files and symbols:",
        ]

        for item in self.files[:max_files]:
            symbol_text = ", ".join(
                f"{symbol.kind} {symbol.name}@{symbol.line}" for symbol in item.symbols[:8]
            )
            if symbol_text:
                rows.append(f"- {item.path} [{item.language}] -> {symbol_text}")
            else:
                rows.append(f"- {item.path} [{item.language}]")

        if len(self.files) > max_files:
            rows.append(f"... {len(self.files) - max_files} more files")

        return "\n".join(rows)


def language_for_path(path: Path) -> str:
    """Infer language from file suffix or well-known filename."""

    name = path.name.lower()
    if name == "makefile":
        return "makefile"
    if name == "dockerfile":
        return "dockerfile"
    if name.endswith("requirements.txt"):
        return "python-requirements"
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text")


def extract_symbols(text: str, language: str) -> list[IndexedSymbol]:
    """Extract lightweight symbols using conservative regular expressions."""

    symbols: list[IndexedSymbol] = []
    lines = text.splitlines()

    patterns_by_language: dict[str, list[tuple[str, re.Pattern[str]]]] = {
        "python": [
            ("class", re.compile(r"^\s*class\s+([A-Za-z_][\w]*)")),
            ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(")),
        ],
        "javascript": [
            ("class", re.compile(r"^\s*class\s+([A-Za-z_$][\w$]*)")),
            (
                "function",
                re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
            ),
            (
                "function",
                re.compile(
                    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("
                ),
            ),
        ],
        "typescript": [
            ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")),
            ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)")),
            (
                "function",
                re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
            ),
            (
                "function",
                re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[:=]"),
            ),
        ],
        "java": [
            ("class", re.compile(r"^\s*(?:public\s+)?(?:final\s+)?class\s+([A-Za-z_][\w]*)")),
            ("interface", re.compile(r"^\s*(?:public\s+)?interface\s+([A-Za-z_][\w]*)")),
            ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+([A-Za-z_][\w]*)")),
            (
                "method",
                re.compile(r"^\s*(?:public|private|protected)\s+[^=;]+\s+([A-Za-z_][\w]*)\s*\("),
            ),
        ],
        "markdown": [
            ("heading", re.compile(r"^(#{1,6})\s+(.+)$")),
        ],
    }

    aliases = {
        "javascript-react": "javascript",
        "typescript-react": "typescript",
    }
    normalized_language = aliases.get(language, language)
    patterns = patterns_by_language.get(normalized_language, [])

    for line_number, line in enumerate(lines, start=1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            if normalized_language == "markdown" and kind == "heading":
                name = match.group(2).strip()
            else:
                name = match.group(1).strip()
            symbols.append(IndexedSymbol(kind=kind, name=name, line=line_number))
            break

    return symbols[:80]


def build_project_index(
    root: Path,
    start_path: str = ".",
    max_files: int = 500,
    max_file_chars: int = 80000,
) -> ProjectIndex:
    """Build a lightweight index of text/code files under the workspace."""

    target = safe_resolve(root, start_path)
    index = ProjectIndex()

    if not target.exists():
        raise FileNotFoundError(f"Path bulunamadı: {start_path}")

    candidates = [target] if target.is_file() else sorted(target.rglob("*"))

    for path in candidates:
        if path.is_dir():
            continue
        if should_skip_path(path, root) or is_probably_binary(path):
            index.skipped_files += 1
            continue
        if len(index.files) >= max_files:
            index.truncated = True
            break

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            size = path.stat().st_size
        except OSError:
            index.skipped_files += 1
            continue

        language = language_for_path(path)
        sampled_text = text[:max_file_chars]
        rel_path = str(path.relative_to(root))
        index.files.append(
            IndexedFile(
                path=rel_path,
                language=language,
                size_bytes=size,
                line_count=text.count("\n") + (1 if text else 0),
                symbols=extract_symbols(sampled_text, language),
            )
        )

    return index


def index_project(
    root: Path,
    start_path: str = ".",
    max_files: int = 500,
    max_file_chars: int = 80000,
    save: bool = True,
    dry_run: bool = False,
) -> str:
    """Build and optionally persist a project index."""

    index = build_project_index(root, start_path, max_files, max_file_chars)
    summary = index.summary()
    if save and dry_run:
        return "DRY-RUN: project index not saved.\n\n" + summary
    if save:
        index_dir = root / ".minicodex"
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "index.json").write_text(
            json.dumps(index.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return summary


def search_text(
    root: Path,
    query: str,
    start_path: str = ".",
    max_matches: int = 50,
    context_chars: int = 180,
) -> str:
    """Search visible text files for a query and return path:line snippets."""

    if not query.strip():
        return "Arama sorgusu boş olamaz."

    target = safe_resolve(root, start_path)
    if not target.exists():
        return f"Path bulunamadı: {start_path}"

    query_lower = query.lower()
    matches: list[str] = []
    candidates = [target] if target.is_file() else sorted(target.rglob("*"))

    for path in candidates:
        if len(matches) >= max_matches:
            break
        if path.is_dir() or should_skip_path(path, root) or is_probably_binary(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel_path = path.relative_to(root)
        for line_number, line in enumerate(lines, start=1):
            if query_lower not in line.lower():
                continue
            snippet = line.strip()
            if len(snippet) > context_chars:
                pos = line.lower().find(query_lower)
                start = max(0, pos - context_chars // 2)
                snippet = line[start : start + context_chars].strip()
                if start > 0:
                    snippet = "..." + snippet
                if start + context_chars < len(line):
                    snippet += "..."
            matches.append(f"{rel_path}:{line_number}: {snippet}")
            if len(matches) >= max_matches:
                break

    if not matches:
        return f"Eşleşme bulunamadı: {query}"
    suffix = "" if len(matches) < max_matches else f"\n... ilk {max_matches} eşleşme gösterildi"
    return "\n".join(matches) + suffix


def read_many_files(root: Path, paths: list[str], max_chars_each: int = 12000) -> str:
    """Read multiple files in one tool result."""

    if not paths:
        return "Okunacak dosya listesi boş."

    sections: list[str] = []
    for path in paths:
        sections.append(f"===== {path} =====")
        sections.append(read_file(root, path, max_chars_each))
    return truncate("\n\n".join(sections), max_chars_each * max(1, min(len(paths), 5)))


def rg_search(
    root: Path,
    pattern: str,
    start_path: str = ".",
    max_matches: int = 80,
    context_lines: int = 0,
    case_sensitive: bool = False,
) -> str:
    """Regex search visible text files using ripgrep-like output.

    This is implemented in Python so it works even when rg is not installed,
    while keeping shell execution out of the search path.
    """

    if not pattern.strip():
        return "Regex pattern boş olamaz."
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags=flags)
    except re.error as exc:
        return f"Regex pattern geçersiz: {exc}"

    target = safe_resolve(root, start_path)
    if not target.exists():
        return f"Path bulunamadı: {start_path}"

    candidates = [target] if target.is_file() else sorted(target.rglob("*"))
    matches: list[str] = []
    for path in candidates:
        if len(matches) >= max_matches:
            break
        if path.is_dir() or should_skip_path(path, root) or is_probably_binary(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = path.relative_to(root)
        for line_number, line in enumerate(lines, start=1):
            if not regex.search(line):
                continue
            if context_lines > 0:
                start = max(1, line_number - context_lines)
                end = min(len(lines), line_number + context_lines)
                for idx in range(start, end + 1):
                    marker = ":" if idx == line_number else "-"
                    matches.append(f"{rel}{marker}{idx}{marker} {lines[idx - 1]}")
                    if len(matches) >= max_matches:
                        break
            else:
                matches.append(f"{rel}:{line_number}: {line.strip()}")
            if len(matches) >= max_matches:
                break

    if not matches:
        return f"Regex eşleşmesi bulunamadı: {pattern}"
    suffix = "" if len(matches) < max_matches else f"\n... ilk {max_matches} eşleşme gösterildi"
    return "\n".join(matches) + suffix
