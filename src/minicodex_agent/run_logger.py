"""Persistent run logging for MiniCodex.

The logger is deliberately conservative: run logs can otherwise become a
secondary secret store because they may contain model tool arguments, command
output, diffs, or file contents.  By default every value is recursively redacted
and long text values are capped before being written to disk.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .secret_scanner import redact_secret
from .utils import truncate

DEFAULT_MAX_LOG_VALUE_CHARS = 6000
DEFAULT_MAX_LOG_COLLECTION_ITEMS = 100


class RunLogger:
    """Write per-run JSONL logs under .minicodex/runs.

    Args:
        base_dir: Directory that contains timestamped run folders.
        enabled: When False, no directories or files are created.
        redaction: When True, redact likely secrets before writing logs.
        max_value_chars: Maximum length for each string value in logs.
        max_collection_items: Maximum number of list/tuple/set items logged.
    """

    def __init__(
        self,
        base_dir: Path,
        enabled: bool = True,
        *,
        redaction: bool = True,
        max_value_chars: int = DEFAULT_MAX_LOG_VALUE_CHARS,
        max_collection_items: int = DEFAULT_MAX_LOG_COLLECTION_ITEMS,
    ) -> None:
        self.enabled = enabled
        self.redaction = redaction
        self.max_value_chars = max(200, int(max_value_chars))
        self.max_collection_items = max(1, int(max_collection_items))
        self.base_dir = base_dir
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = base_dir / timestamp
        if self.enabled:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.events_path = self.run_dir / "events.jsonl"
            self.plan_path = self.run_dir / "plan.md"
            self.final_path = self.run_dir / "final.json"
        else:
            self.events_path = Path("")
            self.plan_path = Path("")
            self.final_path = Path("")

    def sanitize(self, value: Any) -> Any:
        """Return a redacted and size-capped JSON-safe representation."""

        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            text = redact_secret(value) if self.redaction else value
            return truncate(text, self.max_value_chars)
        if isinstance(value, Path):
            return self.sanitize(str(value))
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= self.max_collection_items:
                    sanitized["…truncated_items…"] = len(value) - self.max_collection_items
                    break
                safe_key = str(self.sanitize(str(key)))
                sanitized[safe_key] = self.sanitize(item)
            return sanitized
        if isinstance(value, list | tuple | set):
            values = list(value)
            sanitized_list = [self.sanitize(item) for item in values[: self.max_collection_items]]
            if len(values) > self.max_collection_items:
                sanitized_list.append(
                    f"…truncated {len(values) - self.max_collection_items} additional items…"
                )
            return sanitized_list
        return self.sanitize(str(value))

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        """Write redacted run metadata."""

        if not self.enabled:
            return
        safe_metadata = self.sanitize(metadata)
        (self.run_dir / "metadata.json").write_text(
            json.dumps(safe_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def log_event(self, event: dict[str, Any]) -> None:
        """Append one redacted JSON event."""

        if not self.enabled:
            return
        safe_event = self.sanitize(event)
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(safe_event, ensure_ascii=False) + "\n")

    def write_plan(self, steps: list[str]) -> None:
        """Persist the current plan as redacted markdown."""

        if not self.enabled:
            return
        lines = ["# MiniCodex Plan", ""]
        for index, step in enumerate(steps[: self.max_collection_items], start=1):
            safe_step = str(self.sanitize(step))
            lines.append(f"{index}. {safe_step}")
        if len(steps) > self.max_collection_items:
            lines.append(
                f"... truncated {len(steps) - self.max_collection_items} additional steps ..."
            )
        self.plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_final(self, final: dict[str, Any]) -> None:
        """Persist the redacted final response."""

        if not self.enabled:
            return
        safe_final = self.sanitize(final)
        self.final_path.write_text(
            json.dumps(safe_final, ensure_ascii=False, indent=2), encoding="utf-8"
        )
