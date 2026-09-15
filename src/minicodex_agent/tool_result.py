"""Structured tool-result envelopes for MiniCodex.

The public tool handlers still return plain strings for backwards
compatibility, but the agent loop can wrap every observation in a compact,
machine-readable envelope.  This gives models a stable status/summary/data
contract without losing the original human-readable output.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import truncate

_BLOCK_PREFIXES = (
    "TOOL BLOCK",
    "COMMAND BLOCK",
    "POLICY BLOCK",
    "MANUAL APPROVAL REQUIRED",
    "SANDBOX BLOCK",
    "ROLE TOOL BLOCK",
)
_ERROR_PATTERNS = re.compile(
    r"(failed|failure|error|exception|traceback|not found|bulunamad[ıi]|reddetti|blocked|block|engellendi|timeout|timed out|validation failed)",
    re.IGNORECASE,
)
_SUCCESS_PATTERNS = re.compile(
    r"(başar[ıi]l[ıi]|created|updated|written|dosya yaz[ıi]ld[ıi]|exit code: 0|no findings|finished)",
    re.IGNORECASE,
)
_PATH_LINE_RE = re.compile(r"(?P<path>[\w./\\-]+):(?P<line>\d+):")
_FILE_CHANGE_RE = re.compile(r"^(?:\+\+\+|---)\s+[ab]/(?P<path>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class ToolResult:
    """Machine-readable result for a single tool call."""

    ok: bool
    status: str
    action: str
    summary: str
    content: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    files_read: tuple[str, ...] = ()
    files_changed: tuple[str, ...] = ()
    commands_run: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)

    def render(self, *, max_chars: int = 12000) -> str:
        """Render a JSON envelope plus the original content for compatibility."""

        payload = self.to_dict()
        if len(str(payload.get("content", ""))) > max_chars:
            payload["content"] = truncate(str(payload["content"]), max_chars)
            payload["truncated"] = True
        return "TOOL_RESULT_JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _first_meaningful_line(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return fallback


def _extract_paths(text: str) -> tuple[str, ...]:
    paths: list[str] = []
    for match in _PATH_LINE_RE.finditer(text):
        path = match.group("path").replace("\\", "/")
        if path and path not in paths:
            paths.append(path)
    return tuple(paths[:40])


def _extract_changed_files(text: str) -> tuple[str, ...]:
    changed: list[str] = []
    for match in _FILE_CHANGE_RE.finditer(text):
        path = match.group("path").strip()
        if path != "/dev/null" and path not in changed:
            changed.append(path)
    return tuple(changed[:40])


def infer_tool_result(
    *,
    action: str,
    text: str,
    args: Mapping[str, object] | None = None,
    max_content_chars: int = 12000,
) -> ToolResult:
    """Infer a structured result envelope from a legacy string observation."""

    args = args or {}
    raw_text = str(text)
    truncated = len(raw_text) > max_content_chars
    content = truncate(raw_text, max_content_chars)
    lowered = raw_text.lower()

    status = "ok"
    ok = True
    errors: list[str] = []
    warnings: list[str] = []

    if raw_text.startswith(_BLOCK_PREFIXES):
        status = "blocked"
        ok = False
        errors.append(_first_meaningful_line(raw_text, "Tool blocked."))
    elif "exit code:" in lowered:
        match = re.search(r"Exit code:\s*(-?\d+)", raw_text, flags=re.IGNORECASE)
        if match and int(match.group(1)) != 0:
            status = "failed"
            ok = False
            errors.append(f"Command exited with code {match.group(1)}.")
        elif match:
            status = "ok"
    elif _ERROR_PATTERNS.search(raw_text) and not _SUCCESS_PATTERNS.search(raw_text):
        status = "failed"
        ok = False
        errors.append(_first_meaningful_line(raw_text, "Tool reported an error."))

    if truncated:
        warnings.append(f"Tool content truncated to {max_content_chars} chars.")

    files_read: list[str] = []
    files_changed: list[str] = list(_extract_changed_files(raw_text))
    commands_run: list[str] = []

    paths_arg = args.get("paths")
    if action in {"read_file", "read_file_range"} and isinstance(args.get("path"), str):
        files_read.append(str(args["path"]))
    elif action == "read_many_files" and isinstance(paths_arg, list):
        files_read.extend(str(item) for item in paths_arg)
    elif action in {"search_text", "rg_search", "search_code"}:
        files_read.extend(_extract_paths(raw_text))
    elif action in {"write_file", "replace_in_file"} and isinstance(args.get("path"), str):
        files_changed.append(str(args["path"]))
    elif action in {"run_command", "run_tests"} and isinstance(args.get("command"), str):
        commands_run.append(str(args["command"]))

    data: dict[str, Any] = {
        "legacy_format": True,
        "content_chars": len(raw_text),
    }
    if "exit code:" in lowered:
        match = re.search(r"Exit code:\s*(-?\d+)", raw_text, flags=re.IGNORECASE)
        if match:
            data["exit_code"] = int(match.group(1))

    summary = _first_meaningful_line(raw_text, f"{action} completed.")
    stripped = raw_text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            candidate = parsed.get("summary") or parsed.get("status") or parsed.get("message")
            if isinstance(candidate, str) and candidate.strip():
                summary = candidate.strip()
    if len(summary) > 240:
        summary = summary[:237] + "..."

    return ToolResult(
        ok=ok,
        status=status,
        action=action,
        summary=summary,
        content=content,
        data=data,
        files_read=tuple(dict.fromkeys(files_read)),
        files_changed=tuple(dict.fromkeys(files_changed)),
        commands_run=tuple(dict.fromkeys(commands_run)),
        warnings=tuple(warnings),
        errors=tuple(errors),
        truncated=truncated,
    )


def render_structured_observation(
    *,
    action: str,
    text: str,
    args: Mapping[str, object] | None = None,
    max_content_chars: int = 12000,
) -> str:
    """Render a legacy observation as a structured MiniCodex tool result."""

    return infer_tool_result(
        action=action,
        text=text,
        args=args,
        max_content_chars=max_content_chars,
    ).render(max_chars=max_content_chars)
