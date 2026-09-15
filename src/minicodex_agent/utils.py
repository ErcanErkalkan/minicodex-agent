"""General utility helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def truncate(text: str, max_chars: int) -> str:
    """Truncate long text while making the truncation explicit."""

    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n...[TRUNCATED]..."


def subprocess_text(value: str | bytes | None) -> str:
    """Normalize subprocess output from normal and timeout code paths."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from a model response."""

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        return parsed

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"Model geçerli JSON döndürmedi:\n{text}")


def to_pretty_json(value: Any) -> str:
    """Serialize a value as stable, readable JSON."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def relative_posix(path: Path, root: Path) -> str:
    """Return a stable repository-relative path for user-facing output."""

    return path.relative_to(root).as_posix()
