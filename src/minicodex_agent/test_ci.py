"""Test/CI planning, failure classification, and log summarization helpers.

This module keeps the agent's test loop deterministic and cheap.  It does not
try to replace a real CI system; it gives the model a structured map of what to
run first, why a failure happened, and which files are likely relevant.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .failure_tools import ErrorLocation, parse_error_locations
from .project_inspector import ProjectProfile, choose_test_command, detect_project
from .safety import safe_resolve
from .utils import truncate

_TEST_NAME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pytest-nodeid", re.compile(r"([\w./\\-]+\.py::[\w\[\].:/\\-]+)")),
    ("pytest-failed", re.compile(r"FAILED\s+([\w./\\-]+\.py::[^\s]+)")),
    ("unittest", re.compile(r"FAIL:\s+([\w.]+)\s+\(([^)]+)\)")),
    ("jest", re.compile(r"(?:FAIL|PASS)\s+([\w./\\-]+\.(?:test|spec)\.[jt]sx?)")),
)

_FAILURE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("timeout", ("timed out", "timeout", "deadline exceeded")),
    ("syntax", ("syntaxerror", "parse error", "unexpected token", "unterminated")),
    (
        "import",
        (
            "importerror",
            "modulenotfounderror",
            "cannot find module",
            "no module named",
            "package not found",
        ),
    ),
    (
        "typecheck",
        (
            "mypy",
            "pyright",
            "tsc",
            "typescript",
            "type error",
            "incompatible type",
            "attributeerror",
        ),
    ),
    (
        "assertion",
        ("assertionerror", "assert ", "expected", "actual", "should equal", "assert.strict"),
    ),
    ("lint", ("ruff", "flake8", "eslint", "prettier", "black would reformat", "lint")),
    (
        "build",
        (
            "build failed",
            "compilation failure",
            "compile error",
            "javac",
            "cargo build",
            "go build",
        ),
    ),
    (
        "dependency",
        (
            "command not found",
            "not recognized",
            "missing dependency",
            "no such file or directory",
            "could not resolve",
        ),
    ),
)

_FLAKY_PATTERNS = re.compile(
    r"(flaky|rerun|re-run|reran|xpass|xfail|intermittent|race condition|random seed|order-dependent|timing-dependent)",
    re.IGNORECASE,
)

_CI_MARKERS = re.compile(
    r"(github actions|gitlab ci|circleci|buildkite|jenkins|azure pipelines|workflow|job|step)",
    re.IGNORECASE,
)

_TEST_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rs"}


@dataclass(frozen=True)
class TestPlanCommand:
    """One command selected for the next verification step."""

    command: str
    reason: str
    scope: str = "targeted"  # targeted | fallback | full | lint | build
    related_files: tuple[str, ...] = ()
    expected_duration: str = "short"


@dataclass(frozen=True)
class TestPlan:
    """Structured plan for a test/CI verification pass."""

    commands: tuple[TestPlanCommand, ...]
    project_types: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    failed_tests: tuple[str, ...] = ()
    locations: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass(frozen=True)
class FailureClassification:
    """Structured summary of a failing test/build/CI output."""

    category: str
    confidence: float
    summary: str
    locations: tuple[dict[str, Any], ...] = ()
    failed_tests: tuple[str, ...] = ()
    likely_files: tuple[str, ...] = ()
    flaky_signals: tuple[str, ...] = ()
    ci_detected: bool = False
    recommended_next_actions: tuple[str, ...] = ()
    output_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


def _norm_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _safe_existing_file(root: Path, path: str) -> Path | None:
    try:
        candidate = safe_resolve(root, _norm_path(path))
    except ValueError:
        return None
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _dedupe(items: Iterable[str], limit: int = 40) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for item in items:
        value = _norm_path(str(item))
        if value and value not in seen:
            seen[value] = None
        if len(seen) >= limit:
            break
    return tuple(seen)


def extract_failed_tests(output: str, limit: int = 40) -> tuple[str, ...]:
    """Extract likely failed test identifiers from test output."""

    found: list[str] = []
    for source, pattern in _TEST_NAME_PATTERNS:
        for match in pattern.finditer(output):
            if source == "unittest" and len(match.groups()) >= 2:
                value = f"{match.group(2)}.{match.group(1)}"
            else:
                value = match.group(1)
            value = value.strip()
            if value and value not in found:
                found.append(value)
            if len(found) >= limit:
                return tuple(found)
    return tuple(found)


def _location_dict(location: ErrorLocation) -> dict[str, Any]:
    return {
        "path": location.path,
        "line": location.line,
        "column": location.column,
        "source": location.source,
    }


def _category_from_output(output: str) -> tuple[str, float]:
    lowered = output.lower()
    scores: dict[str, int] = {}
    for category, keywords in _FAILURE_KEYWORDS:
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score:
            scores[category] = score
    if not scores:
        if "failed" in lowered or "error" in lowered:
            return "test", 0.55
        return "unknown", 0.25
    category, score = max(scores.items(), key=lambda item: item[1])
    confidence = min(0.95, 0.55 + 0.12 * score)
    return category, confidence


def _flaky_signals(output: str) -> tuple[str, ...]:
    signals: list[str] = []
    for line in output.splitlines():
        if _FLAKY_PATTERNS.search(line):
            cleaned = line.strip()
            if cleaned and cleaned not in signals:
                signals.append(cleaned[:220])
        if len(signals) >= 12:
            break
    return tuple(signals)


def classify_failure_output(
    root: Path, output: str, *, max_excerpt_chars: int = 9000
) -> FailureClassification:
    """Classify failing test/build/CI output and suggest next actions."""

    if not output.strip():
        return FailureClassification(
            category="empty",
            confidence=1.0,
            summary="No failure output was provided.",
            recommended_next_actions=(
                "Run the smallest relevant test command and classify its output.",
            ),
        )

    locations = parse_error_locations(output, root=root)
    failed_tests = extract_failed_tests(output)
    category, confidence = _category_from_output(output)
    flaky = _flaky_signals(output)
    ci_detected = bool(_CI_MARKERS.search(output))

    likely_files = _dedupe(
        [location.path for location in locations]
        + [test.split("::", 1)[0] for test in failed_tests if "." in test]
    )

    actions: list[str] = []
    if failed_tests:
        actions.append("Run the smallest failing test node/test file first, not the full suite.")
    if locations:
        actions.append("Open the detected file/line context before editing.")
    if category == "import":
        actions.append("Check dependency/import path changes before modifying product logic.")
    elif category == "syntax":
        actions.append("Fix syntax first, then rerun the same targeted test.")
    elif category == "assertion":
        actions.append(
            "Compare expected vs actual behavior and prefer minimal product-code changes."
        )
    elif category == "timeout":
        actions.append(
            "Inspect loops, waits, network calls, and test timeouts before broad refactors."
        )
    elif category == "lint":
        actions.append("Run the formatter/linter-specific check after the edit.")
    if flaky:
        actions.append(
            "Rerun the same targeted command to distinguish deterministic failure from flake."
        )
    if ci_detected:
        actions.append(
            "Identify the failing CI job/step and reproduce its exact command locally when possible."
        )
    if not actions:
        actions.append(
            "Use analyze_failure with source context, then run a targeted test after editing."
        )

    first_line = next(
        (line.strip() for line in output.splitlines() if line.strip()), "Failure output provided."
    )
    summary = f"{category} failure detected"
    if failed_tests:
        summary += f"; first failing test: {failed_tests[0]}"
    elif locations:
        loc = locations[0]
        summary += f"; first location: {loc.path}:{loc.line or '?'}"
    else:
        summary += f"; first line: {first_line[:140]}"

    return FailureClassification(
        category=category,
        confidence=confidence,
        summary=summary,
        locations=tuple(_location_dict(location) for location in locations[:20]),
        failed_tests=failed_tests,
        likely_files=likely_files,
        flaky_signals=flaky,
        ci_detected=ci_detected,
        recommended_next_actions=tuple(actions),
        output_excerpt=_failure_excerpt(output, max_excerpt_chars=max_excerpt_chars),
    )


def _python_test_candidates(root: Path, changed_file: str) -> list[TestPlanCommand]:
    path = _norm_path(changed_file)
    candidate = _safe_existing_file(root, path)
    if candidate is None:
        return []
    rel = candidate.relative_to(root).as_posix()
    commands: list[TestPlanCommand] = []
    if candidate.suffix == ".py" and (
        rel.startswith("tests/") or candidate.name.startswith("test_")
    ):
        commands.append(
            TestPlanCommand(
                command=f"pytest -q {rel}",
                reason="Changed file is a Python test file.",
                related_files=(rel,),
            )
        )
        return commands
    if candidate.suffix != ".py":
        return []

    stem = candidate.stem
    names = {stem, stem.replace("_", ""), stem.removeprefix("test_")}
    discovered: list[str] = []
    tests_dir = root / "tests"
    if tests_dir.exists():
        for test_file in tests_dir.rglob("*.py"):
            try:
                test_rel = test_file.relative_to(root).as_posix()
            except ValueError:
                continue
            haystack = test_file.stem.replace("_", "")
            if any(name and name.replace("_", "") in haystack for name in names):
                discovered.append(test_rel)
    if discovered:
        for test_rel in sorted(discovered)[:3]:
            commands.append(
                TestPlanCommand(
                    command=f"pytest -q {test_rel}",
                    reason=f"Likely Python test for changed source file {rel}.",
                    related_files=(rel, test_rel),
                )
            )
    return commands


def _node_test_candidates(root: Path, changed_file: str) -> list[TestPlanCommand]:
    path = _norm_path(changed_file)
    candidate = _safe_existing_file(root, path)
    if candidate is None or candidate.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
        return []
    rel = candidate.relative_to(root).as_posix()
    if re.search(r"\.(test|spec)\.[jt]sx?$", candidate.name):
        return [
            TestPlanCommand(
                command=f"npm test -- {rel}",
                reason="Changed file is a Node/JS test file; pass it as a test filter.",
                related_files=(rel,),
            )
        ]
    return []


def _go_test_candidates(root: Path, changed_file: str) -> list[TestPlanCommand]:
    path = _norm_path(changed_file)
    candidate = _safe_existing_file(root, path)
    if candidate is None or candidate.suffix != ".go":
        return []
    rel = candidate.relative_to(root)
    package_dir = rel.parent.as_posix() or "."
    return [
        TestPlanCommand(
            command=f"go test ./{package_dir}" if package_dir != "." else "go test .",
            reason="Run the Go package containing the changed file.",
            related_files=(rel.as_posix(),),
        )
    ]


def _rust_test_candidates(root: Path, changed_file: str) -> list[TestPlanCommand]:
    path = _norm_path(changed_file)
    candidate = _safe_existing_file(root, path)
    if candidate is None or candidate.suffix != ".rs":
        return []
    rel = candidate.relative_to(root).as_posix()
    command = "cargo test"
    if "/" not in rel and rel.startswith("tests"):
        command = f"cargo test --test {candidate.stem}"
    return [
        TestPlanCommand(
            command=command, reason="Run Rust tests after an .rs change.", related_files=(rel,)
        )
    ]


def _java_test_candidates(root: Path, changed_file: str) -> list[TestPlanCommand]:
    path = _norm_path(changed_file)
    candidate = _safe_existing_file(root, path)
    if candidate is None or candidate.suffix != ".java":
        return []
    rel = candidate.relative_to(root).as_posix()
    if candidate.name.endswith("Test.java") and (root / "pom.xml").exists():
        return [
            TestPlanCommand(
                command=f"mvn -q -Dtest={candidate.stem} test",
                reason="Changed file is a Maven Java test class.",
                related_files=(rel,),
            )
        ]
    return []


def _commands_from_failed_tests(failed_tests: Iterable[str]) -> list[TestPlanCommand]:
    commands: list[TestPlanCommand] = []
    for test in failed_tests:
        test = _norm_path(test)
        if ".py::" in test:
            commands.append(
                TestPlanCommand(
                    command=f"pytest -q {test}",
                    reason="Re-run the exact failing pytest node first.",
                    related_files=(test.split("::", 1)[0],),
                )
            )
        elif test.endswith(".py"):
            commands.append(
                TestPlanCommand(
                    command=f"pytest -q {test}",
                    reason="Re-run the failing pytest file first.",
                    related_files=(test,),
                )
            )
        elif re.search(r"\.(test|spec)\.[jt]sx?$", test):
            commands.append(
                TestPlanCommand(
                    command=f"npm test -- {test}",
                    reason="Re-run the failing JS/TS test file first.",
                    related_files=(test,),
                )
            )
    return commands


def _append_command(commands: list[TestPlanCommand], command: TestPlanCommand) -> None:
    if command.command not in {item.command for item in commands}:
        commands.append(command)


def plan_tests(
    root: Path,
    profile: ProjectProfile | None = None,
    *,
    changed_files: Iterable[str] = (),
    failure_output: str = "",
    command_override: str = "auto",
    include_lint: bool = False,
    include_build: bool = False,
    include_typecheck: bool = False,
    max_commands: int = 5,
) -> TestPlan:
    """Return a targeted verification plan for changed files and failures."""

    profile = profile or detect_project(root)
    changed = _dedupe(changed_files)
    classification = (
        classify_failure_output(root, failure_output) if failure_output.strip() else None
    )
    failed_tests = classification.failed_tests if classification else ()
    locations = classification.locations if classification else ()

    commands: list[TestPlanCommand] = []
    for candidate in _commands_from_failed_tests(failed_tests):
        _append_command(commands, candidate)

    signal_files = list(changed)
    if classification:
        signal_files.extend(classification.likely_files)
    for changed_file in _dedupe(signal_files, limit=30):
        for candidate in (
            _python_test_candidates(root, changed_file)
            + _node_test_candidates(root, changed_file)
            + _go_test_candidates(root, changed_file)
            + _rust_test_candidates(root, changed_file)
            + _java_test_candidates(root, changed_file)
        ):
            _append_command(commands, candidate)
            if len(commands) >= max_commands:
                break
        if len(commands) >= max_commands:
            break

    chosen = choose_test_command(profile, command_override)
    if chosen:
        _append_command(
            commands,
            TestPlanCommand(
                command=chosen,
                reason="Project-level fallback/full test command.",
                scope="full" if not commands else "fallback",
                expected_duration="medium",
            ),
        )

    if include_typecheck:
        for command in getattr(profile, "typecheck_commands", [])[:2]:
            _append_command(
                commands,
                TestPlanCommand(
                    command=command,
                    reason="Requested typecheck verification.",
                    scope="typecheck",
                    expected_duration="medium",
                ),
            )

    if include_lint:
        for command in profile.lint_commands[:2]:
            _append_command(
                commands,
                TestPlanCommand(
                    command=command,
                    reason="Requested lint verification.",
                    scope="lint",
                    expected_duration="medium",
                ),
            )
    if include_build:
        for command in profile.build_commands[:2]:
            _append_command(
                commands,
                TestPlanCommand(
                    command=command,
                    reason="Requested build verification.",
                    scope="build",
                    expected_duration="medium",
                ),
            )

    warnings: list[str] = []
    if not commands:
        warnings.append(
            "No test command could be inferred. Inspect project files or pass a command explicitly."
        )
    if max_commands < 1:
        warnings.append("max_commands was below 1; no commands returned.")

    return TestPlan(
        commands=tuple(commands[: max(0, max_commands)]),
        project_types=tuple(profile.project_types),
        warnings=tuple(warnings),
        changed_files=changed,
        failed_tests=failed_tests,
        locations=locations,
    )


def _failure_excerpt(output: str, *, max_excerpt_chars: int = 9000) -> str:
    important: list[str] = []
    important_re = re.compile(
        r"(FAILED|ERROR|Traceback|AssertionError|SyntaxError|ImportError|ModuleNotFoundError|TypeError|Exit code|FAIL|panic:|error\[|Caused by:)",
        re.IGNORECASE,
    )
    for line in output.splitlines():
        if important_re.search(line):
            important.append(line)
        if len("\n".join(important)) > max_excerpt_chars // 2:
            break
    head = "\n".join(output.splitlines()[:40])
    tail = "\n".join(output.splitlines()[-80:])
    combined = "\n".join(
        part for part in ["\n".join(important), "--- head ---", head, "--- tail ---", tail] if part
    )
    return truncate(combined, max_excerpt_chars)


def summarize_ci_log(root: Path, output: str, *, max_chars: int = 12000) -> dict[str, Any]:
    """Summarize a CI log into failing steps, categories, and next actions."""

    classification = classify_failure_output(root, output, max_excerpt_chars=max_chars // 2)
    failing_steps: list[str] = []
    step_re = re.compile(
        r"(?:##\[group\]|##\[error\]|\[?step\]?|Running|Run)\s*[:\-]?\s*(.+)", re.IGNORECASE
    )
    for line in output.splitlines():
        if "error" in line.lower() or "failed" in line.lower():
            match = step_re.search(line)
            failing_steps.append((match.group(1) if match else line).strip()[:220])
        if len(failing_steps) >= 20:
            break
    return {
        "summary": classification.summary,
        "category": classification.category,
        "confidence": classification.confidence,
        "ci_detected": classification.ci_detected,
        "failing_steps": tuple(dict.fromkeys(failing_steps)),
        "failed_tests": classification.failed_tests,
        "locations": classification.locations,
        "recommended_next_actions": classification.recommended_next_actions,
        "excerpt": truncate(classification.output_excerpt, max_chars),
    }


def detect_flaky_tests(output: str, *, prior_outputs: Iterable[str] = ()) -> dict[str, Any]:
    """Detect common flaky-test signals in one or more outputs."""

    outputs = [output, *list(prior_outputs)]
    signals: list[str] = []
    failed_sets: list[set[str]] = []
    passed_sets: list[set[str]] = []
    for item in outputs:
        signals.extend(_flaky_signals(item))
        failed = set(extract_failed_tests(item))
        failed_sets.append(failed)
        passed = set(re.findall(r"PASSED\s+([\w./\\-]+\.py::[^\s]+)", item))
        passed_sets.append(passed)

    inconsistent: set[str] = set()
    all_failed = set().union(*failed_sets) if failed_sets else set()
    all_passed = set().union(*passed_sets) if passed_sets else set()
    inconsistent.update(all_failed & all_passed)
    if len(failed_sets) >= 2:
        baseline = failed_sets[0]
        for current in failed_sets[1:]:
            inconsistent.update(baseline.symmetric_difference(current))

    likely_flaky = bool(signals or inconsistent)
    recommendation = (
        "Rerun the exact targeted command, then inspect timing/order/randomness if results differ."
        if likely_flaky
        else "No strong flaky signal detected; treat as deterministic until a rerun disagrees."
    )
    return {
        "likely_flaky": likely_flaky,
        "signals": tuple(dict.fromkeys(signals))[:20],
        "inconsistent_tests": tuple(sorted(inconsistent))[:40],
        "recommendation": recommendation,
    }


def render_json(data: Any) -> str:
    """Render helper output as stable readable JSON."""

    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
