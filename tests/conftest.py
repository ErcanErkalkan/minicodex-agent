"""Pytest marker policy for MiniCodex.

The suite intentionally mixes very small unit tests with integration-style tests
that spawn subprocesses, initialize git repositories, or exercise sandbox/agent
run loops.  Running everything as one monolithic pytest process can be slow in
constrained environments, so collection assigns stable markers that CI and the
bundled matrix runner can use to split the suite.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

MARKER_DESCRIPTIONS: dict[str, str] = {
    "unit": "Fast, in-process unit tests with no subprocess/sandbox dependency.",
    "integration": "Cross-module tests or tests that exercise realistic tool/agent workflows.",
    "subprocess": "Tests that spawn subprocesses, git, pytest, or command runner helpers.",
    "sandbox": "Tests that exercise sandbox/workspace isolation or command policy boundaries.",
    "slow": "Tests that can be slower or more variable in constrained CI environments.",
}

# File-level signals are easier to maintain than decorating hundreds of existing
# tests.  New tests can still use explicit @pytest.mark.* decorators when needed.
INTEGRATION_FILE_KEYWORDS = {
    "integration",
    "github_api",
    "github_layer",
    "eval_layer",
    "dev_experience",
    "multi_agent",
    "long_horizon",
    "quality_gate",
    "agent_workspace",
    "real_multi_agent",
    "terminal_session",
    "observability",
}

SLOW_FILE_KEYWORDS = {
    "exit_codes",
    "github_api",
    "integration",
    "quality_gate",
    "real_multi_agent",
    "terminal_session",
    "agent_workspace",
    "eval_layer",
    "dev_experience",
}

SANDBOX_FILE_KEYWORDS = {
    "sandbox",
    "command_sandbox",
    "shell_tools",
    "terminal_session",
    "agent_workspace",
}

SUBPROCESS_TEXT_NEEDLES = (
    "subprocess.",
    "Popen(",
    "run_command(",
    '"run_command"',
    "'run_command'",
    '"run_tests"',
    "'run_tests'",
    "pytest -q",
    "python -m pytest",
    "git init",
    "run_test_matrix.py",
)


def _has_any_marker(item: pytest.Item, names: Iterable[str]) -> bool:
    return any(item.get_closest_marker(name) is not None for name in names)


def _file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")[:300_000]
    except OSError:
        return ""


def pytest_configure(config: pytest.Config) -> None:
    for name, description in MARKER_DESCRIPTIONS.items():
        config.addinivalue_line("markers", f"{name}: {description}")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path = Path(str(item.fspath))
        filename = path.name.lower()
        text = _file_text(path)

        explicit_non_unit = _has_any_marker(item, {"integration", "subprocess", "sandbox", "slow"})

        if any(keyword in filename for keyword in INTEGRATION_FILE_KEYWORDS):
            item.add_marker(pytest.mark.integration)
            explicit_non_unit = True

        if any(keyword in filename for keyword in SANDBOX_FILE_KEYWORDS):
            item.add_marker(pytest.mark.sandbox)
            explicit_non_unit = True

        if any(needle in text for needle in SUBPROCESS_TEXT_NEEDLES):
            item.add_marker(pytest.mark.subprocess)
            explicit_non_unit = True

        if any(keyword in filename for keyword in SLOW_FILE_KEYWORDS):
            item.add_marker(pytest.mark.slow)
            explicit_non_unit = True

        if not explicit_non_unit and item.get_closest_marker("unit") is None:
            item.add_marker(pytest.mark.unit)
