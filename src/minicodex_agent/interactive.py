"""Interactive REPL helpers for MiniCodex."""

from __future__ import annotations

from .agent import MiniCodexAgent, print_header
from .config import AgentConfig
from .i18n import tr


def run_interactive_session(config: AgentConfig) -> None:
    """Run a small terminal REPL that dispatches goals to MiniCodexAgent."""

    print_header(tr("interactive_title", config.lang))
    print(tr("interactive_help", config.lang))
    while True:
        try:
            goal = input("\nminicodex> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + tr("interactive_closed", config.lang))
            return
        if not goal:
            continue
        if goal in {":q", ":quit", ":exit"}:
            print(tr("interactive_closed", config.lang))
            return
        MiniCodexAgent(config).run(goal)
