"""Deterministic process exit codes for MiniCodex CLI runs.

The CLI maps agent outcomes to stable numeric codes so CI/CD jobs can
understand why a run failed without parsing human-readable logs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import IntEnum


class ExitCode(IntEnum):
    """Stable MiniCodex process exit codes."""

    SUCCESS = 0
    USER_CONFIG_ERROR = 1
    MODEL_ACTION_ERROR = 2
    TESTS_FAILED = 3
    POLICY_BLOCKED = 4
    TOOL_EXECUTION_FAILED = 5


@dataclass(frozen=True)
class RunResult:
    """Structured result returned by MiniCodexAgent.run()."""

    exit_code: ExitCode
    status: str
    reason: str = ""

    @property
    def ok(self) -> bool:
        """Return True when the run completed successfully."""

        return self.exit_code == ExitCode.SUCCESS


_EXIT_RE = re.compile(r"Exit code:\s*(-?\d+)")

_POLICY_PREFIXES = (
    "POLICY BLOCK:",
    "TOOL BLOCK:",
    "COMMAND BLOCK:",
    "SANDBOX BLOCK:",
    "MANUAL APPROVAL REQUIRED:",
)

_TOOL_FAILURE_PREFIXES = (
    "Action failed:",
    "PATCH PLAN FAILED:",
    "PATCH VERIFY FAILED:",
    "PATCH VALIDATION FAILED:",
    "PATCH ROLLBACK:",
)

_TOOL_FAILURE_SNIPPETS = (
    "Command failed to start:",
    "Command timed out after",
    "Test komutu otomatik bulunamadı",
    "Kullanıcı ",
    "User rejected",
)

_MODEL_ACTION_SNIPPETS = (
    "Bilinmeyen action:",
    "Model geçersiz JSON/action",
    "Model çağrısı tamamlanamadı",
    "Model action schema",
)


def _first_exit_code(observation: str) -> int | None:
    match = _EXIT_RE.search(observation)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def classify_action_outcome(action: str, observation: str) -> RunResult | None:
    """Classify one action observation into a non-success result when needed.

    The function returns None for observations that should not change the run
    result. The first non-success outcome usually wins in the agent loop.
    """

    stripped = observation.strip()

    if stripped.startswith("TOOL_RESULT_JSON:"):
        try:
            payload = json.loads(stripped.split("TOOL_RESULT_JSON:\n", 1)[1])
        except (IndexError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            status = str(payload.get("status", ""))
            summary = str(payload.get("summary", ""))
            content = str(payload.get("content", ""))
            combined = "\n".join(part for part in (summary, content) if part)
            if status == "blocked" or combined.startswith(_POLICY_PREFIXES):
                return RunResult(
                    ExitCode.POLICY_BLOCKED, "policy_blocked", summary or "tool blocked"
                )
            if status == "failed" or payload.get("ok") is False:
                if action == "run_tests":
                    return RunResult(
                        ExitCode.TESTS_FAILED, "tests_failed", summary or "tests failed"
                    )
                return RunResult(
                    ExitCode.TOOL_EXECUTION_FAILED,
                    "tool_execution_failed",
                    summary or "tool failed",
                )
            stripped = combined or stripped

    if stripped.startswith(_POLICY_PREFIXES):
        return RunResult(ExitCode.POLICY_BLOCKED, "policy_blocked", stripped.splitlines()[0])

    if stripped.startswith(_TOOL_FAILURE_PREFIXES) or any(
        snippet in stripped for snippet in _TOOL_FAILURE_SNIPPETS
    ):
        return RunResult(
            ExitCode.TOOL_EXECUTION_FAILED, "tool_execution_failed", stripped.splitlines()[0]
        )

    if any(snippet in stripped for snippet in _MODEL_ACTION_SNIPPETS):
        return RunResult(
            ExitCode.MODEL_ACTION_ERROR, "model_action_error", stripped.splitlines()[0]
        )

    code = _first_exit_code(stripped)
    if code is not None and code != 0:
        if action == "run_tests":
            return RunResult(ExitCode.TESTS_FAILED, "tests_failed", f"run_tests exited with {code}")
        if action in {"run_command", "run_terminal_session"}:
            return RunResult(
                ExitCode.TOOL_EXECUTION_FAILED,
                "tool_execution_failed",
                f"{action} exited with {code}",
            )

    return None


def worse_result(current: RunResult, candidate: RunResult | None) -> RunResult:
    """Return the earlier/current failure unless the current result is success."""

    if candidate is None:
        return current
    if current.exit_code == ExitCode.SUCCESS:
        return candidate
    return current
