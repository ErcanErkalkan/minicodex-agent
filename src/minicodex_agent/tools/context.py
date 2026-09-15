"""Runtime context passed to MiniCodex tool handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from minicodex_agent.config import AgentConfig
from minicodex_agent.run_logger import RunLogger

ConfirmFn = Callable[..., bool]
PrintHeaderFn = Callable[[str], None]
AutoSnapshotFn = Callable[[str, str], tuple[bool, str]]
MarkSnapshotHandledFn = Callable[[], None]


@dataclass
class ToolContext:
    """Shared runtime dependencies for tool handlers.

    Tool handlers should depend on this context instead of importing the agent
    class. This keeps the dispatch layer small and makes tools easier to test.
    """

    config: AgentConfig
    state: Any
    logger: RunLogger
    confirm_fn: ConfirmFn
    print_header_fn: PrintHeaderFn
    ensure_auto_snapshot_before_edit: AutoSnapshotFn
    mark_auto_snapshot_handled_fn: MarkSnapshotHandledFn

    def confirm(self, question: str, *, force_manual: bool = False) -> bool:
        """Ask for approval using the agent's configured approval mode."""

        kwargs = {
            "force_manual": force_manual,
            "non_interactive": self.config.non_interactive,
            "default_answer": self.config.default_answer,
            "lang": self.config.lang,
        }
        try:
            return self.confirm_fn(question, self.config.auto_approve, **kwargs)
        except TypeError:
            # Test doubles or older integrations may still accept only
            # (question, auto_approve).
            return self.confirm_fn(question, self.config.auto_approve)

    def print_header(self, title: str) -> None:
        """Print a standard section header."""

        self.print_header_fn(title)

    def mark_auto_snapshot_handled(self) -> None:
        """Tell the agent that an explicit snapshot was already created."""

        self.mark_auto_snapshot_handled_fn()
