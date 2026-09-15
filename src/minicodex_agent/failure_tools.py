"""Failure-output parsing helpers for fix-test loops."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .fs_tools import is_probably_binary
from .safety import safe_resolve
from .utils import truncate


@dataclass(frozen=True)
class ErrorLocation:
    """A file/line location extracted from a failing command output."""

    path: str
    line: int | None = None
    column: int | None = None
    source: str = "unknown"

    def key(self) -> tuple[str, int | None, int | None]:
        return (self.path, self.line, self.column)


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("python-traceback", re.compile(r'File "([^"]+)", line (\d+)')),
    ("pytest-nodeid", re.compile(r"([A-Za-z0-9_./\\-]+\.py):(\d+)(?::\d+)?")),
    ("generic-colon", re.compile(r"(^|\s)([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+):(\d+)(?::(\d+))?")),
    ("java-maven", re.compile(r"([A-Za-z0-9_./\\-]+\.java):\[(\d+),(\d+)\]")),
    ("ts-js", re.compile(r"([A-Za-z0-9_./\\-]+\.(?:ts|tsx|js|jsx))\((\d+),(\d+)\)")),
    ("go", re.compile(r"([A-Za-z0-9_./\\-]+\.go):(\d+):(\d+)")),
    ("rust", re.compile(r"-->\s+([A-Za-z0-9_./\\-]+\.rs):(\d+):(\d+)")),
]


def _clean_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    return path


def parse_error_locations(output: str, root: Path | None = None) -> list[ErrorLocation]:
    """Extract likely source locations from command output."""

    found: list[ErrorLocation] = []
    seen: set[tuple[str, int | None, int | None]] = set()

    for source, pattern in PATTERNS:
        for match in pattern.finditer(output):
            groups = match.groups()
            if source == "generic-colon":
                path = _clean_path(groups[1])
                line = int(groups[2]) if groups[2] else None
                column = int(groups[3]) if len(groups) > 3 and groups[3] else None
            else:
                path = _clean_path(groups[0])
                line = int(groups[1]) if len(groups) > 1 and groups[1] else None
                column = int(groups[2]) if len(groups) > 2 and groups[2] else None

            if root is not None:
                try:
                    candidate = safe_resolve(root, path)
                except ValueError:
                    continue
                # Keep locations even if file does not exist; they may refer to generated paths.
                if candidate.exists():
                    try:
                        path = candidate.relative_to(root).as_posix()
                    except ValueError:
                        continue

            location = ErrorLocation(path=path, line=line, column=column, source=source)
            if location.key() in seen:
                continue
            seen.add(location.key())
            found.append(location)

    return found[:40]


def _read_context(root: Path, location: ErrorLocation, context_lines: int) -> str:
    try:
        path = safe_resolve(root, location.path)
    except ValueError as exc:
        return f"{location.path}: okunamadı ({exc})"

    if not path.exists() or not path.is_file():
        return f"{location.path}: dosya bulunamadı"
    if is_probably_binary(path):
        return f"{location.path}: binary/desteklenmeyen dosya"

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"{location.path}: okunamadı ({exc})"

    if location.line is None:
        return f"{location.path}: satır bilgisi yok"

    start = max(1, location.line - context_lines)
    end = min(len(lines), location.line + context_lines)
    rendered = [f"--- {location.path}:{location.line} ({location.source}) ---"]
    for line_number in range(start, end + 1):
        marker = ">" if line_number == location.line else " "
        rendered.append(f"{marker} {line_number:4d} | {lines[line_number - 1]}")
    return "\n".join(rendered)


def analyze_failure_output(
    root: Path, output: str, context_lines: int = 4, max_chars: int = 16000
) -> str:
    """Summarize failing output and include source context for extracted locations."""

    if not output.strip():
        return "Analiz edilecek hata çıktısı boş."

    locations = parse_error_locations(output, root=root)
    lines = ["Failure analysis", "================", ""]

    exit_matches = re.findall(r"Exit code:\s*(-?\d+)", output)
    if exit_matches:
        lines.append(f"Exit code: {exit_matches[-1]}")

    if locations:
        lines.append("Detected locations:")
        for location in locations:
            line = f"- {location.path}"
            if location.line is not None:
                line += f":{location.line}"
            if location.column is not None:
                line += f":{location.column}"
            line += f" [{location.source}]"
            lines.append(line)
        lines.append("")
        lines.append("Context:")
        for location in locations[:8]:
            lines.append(_read_context(root, location, context_lines))
            lines.append("")
    else:
        lines.append("Dosya/satır konumu otomatik bulunamadı.")

    tail = "\n".join(output.splitlines()[-80:])
    lines.append("Output tail:")
    lines.append(tail)

    return truncate("\n".join(lines), max_chars)
