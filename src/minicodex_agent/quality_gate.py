"""Final readiness and quality-gate helpers for MiniCodex.

This module is intentionally dependency-free and local-only. It does not run
unbounded tests by itself; instead it produces deterministic reports and safe
commands/scripts that teams can use before a release-readiness review or supervised rollout.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import subprocess_text, to_pretty_json, truncate

GENERATED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    "build",
    "dist",
}
GENERATED_SUFFIXES = (".egg-info",)
GENERATED_FILE_NAMES = {".coverage", "coverage.xml"}
RELEASE_CI_REQUIRED_TOOLS = ("ruff", "mypy", "build", "twine", "pytest-cov")
DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_VERIFICATION_TIMEOUT_SECONDS = 1200
TEST_MATRIX_GROUPS = ("fast", "unit", "integration", "subprocess", "sandbox", "slow", "all")
DEFAULT_READINESS_TEST_GROUP = "fast"


_JSON_REPORT_MIN_CHARS = 1200


def _compact_json_value(
    value: Any,
    *,
    max_string_chars: int,
    max_list_items: int,
    max_dict_items: int,
    depth: int = 0,
    max_depth: int = 8,
) -> Any:
    """Return a JSON-serializable value that is compact but still valid JSON.

    Unlike ``truncate(to_pretty_json(...))``, this never cuts the rendered JSON
    text. Large strings/lists/dicts carry explicit truncation metadata so callers
    can parse the report and decide whether they need a fuller artifact.
    """

    if depth > max_depth:
        return {"truncated": True, "reason": "max_depth", "type": type(value).__name__}
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        preview_chars = max(0, max_string_chars)
        return {
            "truncated": True,
            "original_chars": len(value),
            "preview": value[:preview_chars],
            "omitted_chars": max(0, len(value) - preview_chars),
        }
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        original_count = len(value)
        kept = value[: max(0, max_list_items)]
        compacted = [
            _compact_json_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for item in kept
        ]
        if original_count > len(kept):
            compacted.append(
                {
                    "truncated": True,
                    "omitted_count": original_count - len(kept),
                    "original_count": original_count,
                }
            )
        return compacted
    if isinstance(value, dict):
        items = list(value.items())
        kept_items = items[: max(0, max_dict_items)]
        compacted_dict: dict[str, Any] = {}
        for key, item in kept_items:
            compacted_dict[str(key)] = _compact_json_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                depth=depth + 1,
                max_depth=max_depth,
            )
        if len(items) > len(kept_items):
            compacted_dict["_truncated_items"] = {
                "truncated": True,
                "omitted_count": len(items) - len(kept_items),
                "original_count": len(items),
            }
        return compacted_dict
    return str(value)


def _render_prefixed_json(prefix: str, payload: dict[str, Any], max_chars: int) -> str:
    """Render a prefixed JSON report without ever cutting JSON mid-token.

    If the full JSON is too large, progressively compact high-cardinality values.
    The returned text always has the format ``PREFIX\n<valid-json>``.
    """

    effective_max = max(_JSON_REPORT_MIN_CHARS, int(max_chars))
    base_payload = dict(payload)
    base_payload.setdefault("truncated", False)
    full_json = to_pretty_json(base_payload)
    if len(prefix) + 1 + len(full_json) <= effective_max:
        return f"{prefix}\n{full_json}"

    original_json_chars = len(full_json)
    attempts = [
        (4000, 80, 80),
        (2000, 40, 60),
        (1000, 20, 40),
        (500, 10, 25),
        (240, 5, 15),
        (120, 3, 10),
        (80, 1, 8),
    ]
    for max_string_chars, max_list_items, max_dict_items in attempts:
        compacted = _compact_json_value(
            payload,
            max_string_chars=max_string_chars,
            max_list_items=max_list_items,
            max_dict_items=max_dict_items,
        )
        if not isinstance(compacted, dict):
            compacted = {"data": compacted}
        compacted["truncated"] = True
        compacted["original_json_chars"] = original_json_chars
        compacted["max_chars_requested"] = int(max_chars)
        compacted["truncation_strategy"] = {
            "max_string_chars": max_string_chars,
            "max_list_items": max_list_items,
            "max_dict_items": max_dict_items,
        }
        rendered = to_pretty_json(compacted)
        if len(prefix) + 1 + len(rendered) <= effective_max:
            return f"{prefix}\n{rendered}"

    checks = payload.get("checks", [])
    compact_checks: list[dict[str, Any]] = []
    if isinstance(checks, list):
        for check in checks[:20]:
            if isinstance(check, dict):
                compact_checks.append(
                    {
                        "name": check.get("name"),
                        "status": check.get("status"),
                        "summary": _compact_json_value(
                            check.get("summary", ""),
                            max_string_chars=160,
                            max_list_items=1,
                            max_dict_items=5,
                        ),
                    }
                )
    minimal = {
        "schema_version": payload.get("schema_version", 1),
        "overall_status": payload.get("overall_status", "unknown"),
        "version": payload.get("version", ""),
        "truncated": True,
        "original_json_chars": original_json_chars,
        "max_chars_requested": int(max_chars),
        "omitted_due_to_limit": True,
        "checks": compact_checks,
        "omitted_count": max(0, len(checks) - len(compact_checks))
        if isinstance(checks, list)
        else 0,
    }
    return f"{prefix}\n{to_pretty_json(minimal)}"


@dataclass(frozen=True)
class CheckResult:
    """One deterministic readiness check."""

    name: str
    status: str
    summary: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "details": self.details,
        }


def _read_text(path: Path, max_chars: int = 500_000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except OSError:
        return ""


def _pyproject_version(root: Path) -> str:
    text = _read_text(root / "pyproject.toml")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def _init_version(root: Path) -> str:
    text = _read_text(root / "src" / "minicodex_agent" / "__init__.py")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else ""


def _changelog_mentions(root: Path, version: str) -> bool:
    if not version:
        return False
    return version in _read_text(root / "CHANGELOG.md", max_chars=200_000)


def _iter_project_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        rel_parts = path.relative_to(root).parts
        if any(part in {".git", ".venv", "venv"} for part in rel_parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def _is_generated(path: Path) -> bool:
    name = path.name
    if name in GENERATED_DIR_NAMES or name in GENERATED_FILE_NAMES:
        return True
    return any(
        part in GENERATED_DIR_NAMES or part.endswith(GENERATED_SUFFIXES) for part in path.parts
    )


def check_version_alignment(root: Path) -> CheckResult:
    pyproject = _pyproject_version(root)
    package = _init_version(root)
    changelog = _changelog_mentions(root, pyproject)
    ok = bool(pyproject and package and pyproject == package and changelog)
    return CheckResult(
        name="version_alignment",
        status="pass" if ok else "fail",
        summary=(
            f"version={pyproject} is aligned across pyproject, package, and CHANGELOG"
            if ok
            else "Project version is not aligned across pyproject/package/CHANGELOG."
        ),
        details={
            "pyproject": pyproject,
            "package": package,
            "changelog_mentions_version": changelog,
        },
    )


def _semver_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        return (0, 0, 0)
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return (0, 0, 0)


def _changelog_heading_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        version_match = re.match(r"^(#{1,6})\s+v?(\d+\.\d+\.\d+)(?:\s*-\s*(.*))?\s*$", stripped)
        if version_match:
            marker, version, title = version_match.groups()
            canonical = bool(
                marker == "##" and not re.match(r"^##\s+v", stripped) and title and title.strip()
            )
            records.append(
                {
                    "line": lineno,
                    "heading": stripped,
                    "version": version,
                    "title": (title or "").strip(),
                    "canonical": canonical,
                }
            )
    return records


def check_changelog_structure(root: Path) -> CheckResult:
    """Check that CHANGELOG.md is a single, ordered, non-duplicated release ledger."""

    path = root / "CHANGELOG.md"
    if not path.exists():
        return CheckResult(
            name="changelog_structure",
            status="fail",
            summary="CHANGELOG.md is missing.",
            details={"missing": True},
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    h1_changelog_lines = [
        lineno
        for lineno, line in enumerate(lines, start=1)
        if re.match(r"^#\s+Changelog\s*$", line.strip())
    ]
    other_h1_lines = [
        {"line": lineno, "heading": line.strip()}
        for lineno, line in enumerate(lines, start=1)
        if line.strip().startswith("# ") and not re.match(r"^#\s+Changelog\s*$", line.strip())
    ]
    records = _changelog_heading_records(text)
    invalid_format = [record for record in records if not record["canonical"]]
    versions = [str(record["version"]) for record in records if record["canonical"]]
    duplicate_versions = sorted(
        {version for version in versions if versions.count(version) > 1},
        key=_semver_tuple,
        reverse=True,
    )
    expected_order = sorted(versions, key=_semver_tuple, reverse=True)
    out_of_order = versions != expected_order
    current_version = _pyproject_version(root)
    current_version_present = bool(current_version and current_version in versions)
    first_heading = next((line.strip() for line in lines if line.strip().startswith("#")), "")
    ok = (
        len(h1_changelog_lines) == 1
        and h1_changelog_lines == [1]
        and not other_h1_lines
        and not invalid_format
        and not duplicate_versions
        and not out_of_order
        and current_version_present
        and bool(versions)
        and first_heading == "# Changelog"
    )
    return CheckResult(
        name="changelog_structure",
        status="pass" if ok else "fail",
        summary="CHANGELOG.md has one top-level heading, canonical release headings, unique versions, and descending order."
        if ok
        else "CHANGELOG.md has duplicate, malformed, missing, or out-of-order release headings.",
        details={
            "h1_changelog_lines": h1_changelog_lines,
            "other_h1_lines": other_h1_lines[:20],
            "invalid_format": invalid_format[:20],
            "duplicate_versions": duplicate_versions,
            "version_order": versions,
            "expected_order": expected_order,
            "out_of_order": out_of_order,
            "current_version": current_version,
            "current_version_present": current_version_present,
            "release_count": len(versions),
        },
    )


POSITIONING_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("production-readiness", "Use release-readiness or quality-gate readiness for alpha packages."),
    ("production readiness", "Use release readiness or quality-gate readiness for alpha packages."),
    ("production-ready", "Avoid claiming this alpha package is production-ready."),
    ("production ready", "Avoid claiming this alpha package is production ready."),
    ("production-grade", "Avoid claiming this alpha package is production grade."),
    ("production grade", "Avoid claiming this alpha package is production grade."),
)


def _positioning_scan_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in ("README.md", "CHANGELOG.md", "pyproject.toml"):
        path = root / relative
        if path.exists():
            paths.append(path)
    docs = root / "docs"
    if docs.exists():
        paths.extend(sorted(path for path in docs.rglob("*.md") if path.is_file()))
    return paths


def check_positioning_consistency(root: Path) -> CheckResult:
    """Check that package wording matches the alpha/developer-preview metadata."""

    pyproject_text = _read_text(root / "pyproject.toml", max_chars=200_000)
    readme_text = _read_text(root / "README.md", max_chars=200_000)
    alpha_classifier_present = "Development Status :: 3 - Alpha" in pyproject_text
    developer_preview_present = "developer-preview" in (pyproject_text + "\n" + readme_text).lower()
    forbidden_hits: list[dict[str, Any]] = []
    for path in _positioning_scan_paths(root):
        text = _read_text(path, max_chars=500_000)
        lowered = text.lower()
        for pattern, guidance in POSITIONING_FORBIDDEN_PATTERNS:
            start = 0
            while True:
                index = lowered.find(pattern, start)
                if index < 0:
                    break
                line_no = text.count("\n", 0, index) + 1
                line = text.splitlines()[line_no - 1].strip() if text.splitlines() else ""
                forbidden_hits.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": line_no,
                        "pattern": pattern,
                        "line_text": line[:240],
                        "guidance": guidance,
                    }
                )
                start = index + len(pattern)
    ok = alpha_classifier_present and developer_preview_present and not forbidden_hits
    return CheckResult(
        name="positioning_consistency",
        status="pass" if ok else "fail",
        summary=(
            "Package metadata and user-facing docs consistently present MiniCodex as alpha/developer-preview with release-readiness gates."
            if ok
            else "Package metadata or user-facing docs contain inconsistent maturity/readiness positioning."
        ),
        details={
            "alpha_classifier_present": alpha_classifier_present,
            "developer_preview_present": developer_preview_present,
            "forbidden_patterns": [pattern for pattern, _ in POSITIONING_FORBIDDEN_PATTERNS],
            "forbidden_hits": forbidden_hits[:50],
            "forbidden_hit_count": len(forbidden_hits),
            "scanned_paths": [
                str(path.relative_to(root)) for path in _positioning_scan_paths(root)
            ],
        },
    )


FORMAT_POLICY_WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/release.yml")
CLI_HELP_FORBIDDEN_LANGUAGE_PATTERNS = (
    "Kullanılacak",
    "Maksimum",
    "Varsayılan",
    "Model çağırmadan",
    "çalıştır",
    "dosya",
    "klasör",
    "görev",
    "güvenlik",
)
CLI_HELP_FORBIDDEN_CHARS = set("çğıöşüÇĞİÖŞÜ")


def check_format_policy_consistency(root: Path) -> CheckResult:
    """Ensure CI/release formatting checks match the pre-commit formatting policy."""

    precommit_text = _read_text(root / ".pre-commit-config.yaml", max_chars=200_000)
    precommit_has_ruff_format = "ruff-format" in precommit_text
    workflow_results: list[dict[str, Any]] = []
    missing: list[str] = []
    for rel in FORMAT_POLICY_WORKFLOWS:
        text = _read_text(root / rel, max_chars=200_000)
        has_check = "ruff format --check ." in text
        workflow_results.append({"path": rel, "has_ruff_format_check": has_check})
        if not has_check:
            missing.append(rel)
    ok = precommit_has_ruff_format and not missing
    return CheckResult(
        name="format_policy_consistency",
        status="pass" if ok else "fail",
        summary=(
            "Pre-commit, CI, and release workflows all enforce Ruff formatting."
            if ok
            else "Pre-commit and CI/release formatting policies are not aligned."
        ),
        details={
            "precommit_has_ruff_format": precommit_has_ruff_format,
            "required_workflows": list(FORMAT_POLICY_WORKFLOWS),
            "workflow_results": workflow_results,
            "missing_ruff_format_check": missing,
        },
    )


def check_dev_dependency_hygiene(root: Path) -> CheckResult:
    """Flag known stale development dependencies that are not used by the source tree."""

    pyproject_text = _read_text(root / "pyproject.toml", max_chars=200_000)
    source_text = "\n".join(
        _read_text(path, max_chars=200_000)
        for path in sorted((root / "src").rglob("*.py"))
        if path.is_file()
    )
    stale: list[dict[str, Any]] = []
    if "types-python-dateutil" in pyproject_text and "dateutil" not in source_text:
        stale.append(
            {
                "dependency": "types-python-dateutil",
                "reason": "python-dateutil/dateutil is not imported by the source tree.",
            }
        )
    ok = not stale
    return CheckResult(
        name="dev_dependency_hygiene",
        status="pass" if ok else "warn",
        summary="No known stale dev-only dependencies are present."
        if ok
        else "Known stale dev-only dependencies are present.",
        details={"stale_dependencies": stale, "stale_dependency_count": len(stale)},
    )


def _cli_help_literal_records(root: Path) -> list[dict[str, Any]]:
    cli_path = root / "src" / "minicodex_agent" / "cli.py"
    if not cli_path.exists():
        return []
    try:
        tree = ast.parse(cli_path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    records: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "help":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                records.append({"line": value.lineno, "text": value.value})
    return records


def check_cli_help_language(root: Path) -> CheckResult:
    """Keep public argparse help text in one language: English."""

    records = _cli_help_literal_records(root)
    findings: list[dict[str, Any]] = []
    for record in records:
        text = str(record["text"])
        chars = sorted({char for char in text if char in CLI_HELP_FORBIDDEN_CHARS})
        patterns = [
            pattern
            for pattern in CLI_HELP_FORBIDDEN_LANGUAGE_PATTERNS
            if pattern.lower() in text.lower()
        ]
        if chars or patterns:
            findings.append(
                {
                    "line": record["line"],
                    "text": text,
                    "forbidden_chars": chars,
                    "forbidden_patterns": patterns,
                }
            )
    ok = not findings
    return CheckResult(
        name="cli_help_language",
        status="pass" if ok else "fail",
        summary="Public CLI help strings are consistently English."
        if ok
        else "Public CLI help strings mix English and Turkish.",
        details={
            "checked_help_string_count": len(records),
            "finding_count": len(findings),
            "findings": findings[:50],
            "policy": "Argparse help text is English by default; runtime --lang may localize output chrome separately.",
        },
    )


def check_generated_artifacts(root: Path) -> CheckResult:
    offenders: list[str] = []
    for path in _iter_project_files(root):
        rel = path.relative_to(root)
        if _is_generated(rel):
            offenders.append(str(rel))
    ok = not offenders
    return CheckResult(
        name="generated_artifacts",
        status="pass" if ok else "warn",
        summary="No generated/cache/build artifacts found in source tree."
        if ok
        else "Generated/cache/build artifacts are present.",
        details={"paths": sorted(offenders)[:100], "count": len(offenders)},
    )


def check_syntax(root: Path) -> CheckResult:
    errors: list[dict[str, Any]] = []
    for base in (root / "src", root / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": exc.lineno,
                        "message": exc.msg,
                    }
                )
            except OSError as exc:
                errors.append({"path": str(path.relative_to(root)), "message": str(exc)})
    return CheckResult(
        name="python_syntax",
        status="pass" if not errors else "fail",
        summary="All Python files parse successfully."
        if not errors
        else "One or more Python files have syntax/read errors.",
        details={"errors": errors, "count": len(errors)},
    )


def check_registry_alignment(root: Path) -> CheckResult:
    try:
        sys.path.insert(0, str(root / "src"))
        from minicodex_agent.action_schema import ACTION_SPECS
        from minicodex_agent.plugin_registry import BUILTIN_PLUGINS
        from minicodex_agent.tool_registry import get_tool_registry

        registry = get_tool_registry()
        missing_from_registry = sorted(
            set(ACTION_SPECS) - set(registry) - {"ask_user", "finish", "update_plan"}
        )
        registry_without_schema = sorted(set(registry) - set(ACTION_SPECS))
        plugin_unknown: list[str] = []
        for plugin in BUILTIN_PLUGINS:
            for tool in plugin.tools:
                if tool not in ACTION_SPECS:
                    plugin_unknown.append(f"{plugin.name}:{tool}")
        ok = not missing_from_registry and not registry_without_schema and not plugin_unknown
        return CheckResult(
            name="tool_registry_alignment",
            status="pass" if ok else "fail",
            summary="Action schema, runtime registry, and built-in plugins are aligned."
            if ok
            else "Tool registry/schema/plugin mismatch found.",
            details={
                "action_count": len(ACTION_SPECS),
                "registry_count": len(registry),
                "missing_from_registry": missing_from_registry,
                "registry_without_schema": registry_without_schema,
                "plugin_unknown": plugin_unknown,
            },
        )
    except Exception as exc:  # noqa: BLE001 - readiness should not crash on import errors
        return CheckResult(
            name="tool_registry_alignment",
            status="fail",
            summary="Could not import/validate the tool registry.",
            details={"error": f"{type(exc).__name__}: {exc}"},
        )


def _run_command(
    root: Path, command: list[str], timeout: int, *, env: dict[str, str] | None = None
) -> dict[str, Any]:
    merged_env = os.environ.copy()
    merged_env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if env:
        merged_env.update(env)
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=max(1, timeout),
            shell=False,
            env=merged_env,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout_tail": truncate(completed.stdout or "", 20000),
            "stderr_tail": truncate(completed.stderr or "", 12000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": 124,
            "timeout": timeout,
            "stdout_tail": truncate(str(exc.stdout or ""), 20000),
            "stderr_tail": truncate(str(exc.stderr or ""), 12000),
        }
    except OSError as exc:
        return {"command": command, "exit_code": 127, "error": str(exc)}


def cleanup_python_bytecode(root: Path) -> dict[str, Any]:
    """Remove Python runtime artifacts created by local smoke/readiness checks."""

    removed_dirs = 0
    removed_files = 0
    errors: list[str] = []
    root = root.resolve()
    for path in sorted(root.rglob("*.py[co]"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed_files += 1
        except OSError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
    for dirname in ("__pycache__", ".pytest_cache"):
        for path in sorted(root.rglob(dirname), key=lambda item: len(item.parts), reverse=True):
            if not path.is_dir():
                continue
            try:
                shutil.rmtree(path)
                removed_dirs += 1
            except OSError as exc:
                errors.append(f"{path.relative_to(root)}: {exc}")
    return {"removed_dirs": removed_dirs, "removed_files": removed_files, "errors": errors}


def clean_generated_artifacts(
    root: Path, *, dry_run: bool = False, include_build_outputs: bool = True
) -> dict[str, Any]:
    """Remove generated/cache/build artifacts that can pollute readiness manifests."""

    root = root.resolve()
    removed_dirs: list[str] = []
    removed_files: list[str] = []
    errors: list[str] = []
    protected_dirs = {".git", ".venv", "venv", "node_modules"}
    build_dirs = {"build", "dist"}
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if not rel.parts or any(part in protected_dirs for part in rel.parts):
            continue
        if path.is_dir():
            if path.name in build_dirs and not include_build_outputs:
                continue
            if path.name in GENERATED_DIR_NAMES or path.name.endswith(GENERATED_SUFFIXES):
                if not dry_run:
                    try:
                        shutil.rmtree(path)
                    except OSError as exc:
                        errors.append(f"{rel}: {exc}")
                        continue
                removed_dirs.append(str(rel))
        elif path.is_file():
            if path.name in GENERATED_FILE_NAMES or path.suffix in {".pyc", ".pyo"}:
                if not dry_run:
                    try:
                        path.unlink()
                    except OSError as exc:
                        errors.append(f"{rel}: {exc}")
                        continue
                removed_files.append(rel.as_posix())
    return {
        "dry_run": dry_run,
        "include_build_outputs": include_build_outputs,
        "removed_dirs": sorted(removed_dirs),
        "removed_files": sorted(removed_files),
        "errors": errors,
    }


def _expand_command_globs(root: Path, command: list[str]) -> list[str]:
    """Expand simple glob arguments while keeping shell=False."""

    expanded: list[str] = []
    for item in command:
        if any(char in item for char in "*?["):
            matches = sorted(str(path.relative_to(root)) for path in root.glob(item))
            expanded.extend(matches or [item])
        else:
            expanded.append(item)
    return expanded


def check_cli_smoke(root: Path, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    result = _run_command(
        root, [sys.executable, "-B", "-m", "minicodex_agent.cli", "--help"], timeout
    )
    ok = (
        result.get("exit_code") == 0
        and "usage:" in (result.get("stdout_tail", "") + result.get("stderr_tail", "")).lower()
    )
    return CheckResult(
        name="cli_smoke",
        status="pass" if ok else "fail",
        summary="CLI help command works." if ok else "CLI help command failed.",
        details=result,
    )


def _parse_prefixed_json(rendered: str) -> dict[str, Any]:
    """Parse reports that use a human-readable header plus JSON payload."""

    try:
        body = rendered.split("\n", 1)[1] if "\n" in rendered else rendered
        return json.loads(body)
    except (IndexError, json.JSONDecodeError, TypeError):
        return {}


def check_security_audit_gate(root: Path, *, max_files: int = 1000) -> CheckResult:
    """Run local, network-free release-blocking security checks."""

    try:
        from .secret_scanner import (
            count_findings_by_severity,
            has_blocking_secret_findings,
            scan_secret_findings,
        )
        from .security_audit import builtin_sast_scan, scan_repo_instructions

        sast_findings = builtin_sast_scan(root, max_files=max_files, minimum_severity="high")
        secret_findings, scanned, skipped = scan_secret_findings(
            root,
            max_files=min(max_files, 1000),
            max_findings=50,
            minimum_severity="high",
        )
        instruction_payload = _parse_prefixed_json(scan_repo_instructions(root, max_chars=24000))
        instruction_risk = str(instruction_payload.get("risk", "unknown"))
        instruction_findings = instruction_payload.get("findings", [])
        blocking = (
            bool(sast_findings)
            or has_blocking_secret_findings(secret_findings)
            or instruction_risk in {"critical", "high"}
        )
        secret_counts = count_findings_by_severity(secret_findings)
        return CheckResult(
            name="security_audit_gate",
            status="fail" if blocking else "pass",
            summary=(
                "No release-blocking local security findings were detected."
                if not blocking
                else "Release-blocking security findings were detected."
            ),
            details={
                "builtin_sast_high_or_above": sast_findings[:50],
                "secret_counts_high_or_above": secret_counts,
                "secret_files_scanned": scanned,
                "secret_files_skipped": skipped,
                "secret_findings": [finding.__dict__ for finding in secret_findings[:50]],
                "repo_instruction_risk": instruction_risk,
                "repo_instruction_findings": instruction_findings[:50]
                if isinstance(instruction_findings, list)
                else [],
            },
        )
    except Exception as exc:  # noqa: BLE001 - readiness should not crash on optional audit imports
        return CheckResult(
            name="security_audit_gate",
            status="fail",
            summary="Could not complete the local security audit gate.",
            details={"error": f"{type(exc).__name__}: {exc}"},
        )


def _python_module_available(module: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-B", "-c", f"import {module}"],
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=10,
        shell=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return result.returncode == 0


def _verification_command_specs(root: Path) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if (root / "pyproject.toml").exists():
        specs.extend(
            [
                {
                    "name": "ruff",
                    "kind": "lint",
                    "command": [sys.executable, "-m", "ruff", "check", "."],
                    "available": _python_module_available("ruff"),
                },
                {
                    "name": "mypy",
                    "kind": "typecheck",
                    "command": [sys.executable, "-m", "mypy", "src"],
                    "available": _python_module_available("mypy"),
                },
                {
                    "name": "build",
                    "kind": "build",
                    "command": [sys.executable, "-m", "build", "--sdist", "--wheel"],
                    "available": _python_module_available("build"),
                },
                {
                    "name": "twine",
                    "kind": "package-check",
                    "command": [sys.executable, "-m", "twine", "check", "dist/*"],
                    "available": _python_module_available("twine"),
                },
                {
                    "name": "file-level-coverage",
                    "kind": "coverage",
                    "command": [
                        sys.executable,
                        "scripts/run_coverage_gate.py",
                        "--group",
                        "all",
                        "--fail-under",
                        "85",
                        "--json",
                    ],
                    "available": (root / "scripts" / "run_coverage_gate.py").exists()
                    and _python_module_available("pytest")
                    and _python_module_available("pytest_cov")
                    and _python_module_available("coverage"),
                },
            ]
        )
    if (root / "package.json").exists():
        npm_available = shutil.which("npm") is not None
        specs.extend(
            [
                {
                    "name": "npm-lint",
                    "kind": "lint",
                    "command": ["npm", "run", "lint"],
                    "available": npm_available,
                },
                {
                    "name": "npm-typecheck",
                    "kind": "typecheck",
                    "command": ["npm", "run", "typecheck"],
                    "available": npm_available,
                },
                {
                    "name": "npm-build",
                    "kind": "build",
                    "command": ["npm", "run", "build"],
                    "available": npm_available,
                },
            ]
        )
    if (root / "pom.xml").exists():
        specs.append(
            {
                "name": "maven-test",
                "kind": "build",
                "command": ["mvn", "test"],
                "available": shutil.which("mvn") is not None,
            }
        )
    if (root / "go.mod").exists():
        specs.extend(
            [
                {
                    "name": "go-test",
                    "kind": "test",
                    "command": ["go", "test", "./..."],
                    "available": shutil.which("go") is not None,
                },
                {
                    "name": "go-vet",
                    "kind": "lint",
                    "command": ["go", "vet", "./..."],
                    "available": shutil.which("go") is not None,
                },
            ]
        )
    if (root / "Cargo.toml").exists():
        specs.extend(
            [
                {
                    "name": "cargo-test",
                    "kind": "test",
                    "command": ["cargo", "test"],
                    "available": shutil.which("cargo") is not None,
                },
                {
                    "name": "cargo-clippy",
                    "kind": "lint",
                    "command": ["cargo", "clippy", "--", "-D", "warnings"],
                    "available": shutil.which("cargo") is not None,
                },
                {
                    "name": "cargo-build",
                    "kind": "build",
                    "command": ["cargo", "build"],
                    "available": shutil.which("cargo") is not None,
                },
            ]
        )
    return specs


def check_verification_tools(
    root: Path, *, run_tools: bool = False, timeout: int = DEFAULT_TIMEOUT_SECONDS
) -> CheckResult:
    """Report build/lint/typecheck availability and optionally run installed checks."""

    specs = _verification_command_specs(root)
    if not specs:
        return CheckResult(
            name="verification_tools_gate",
            status="pass",
            summary="No supported build/lint/typecheck manifest was detected.",
            details={"commands": [], "results": []},
        )
    results: list[dict[str, Any]] = []
    missing = [spec for spec in specs if not spec.get("available")]
    failures: list[dict[str, Any]] = []
    if run_tools:
        with tempfile.TemporaryDirectory(prefix="minicodex-verification-") as tmp:
            temp_root = Path(tmp)
            python_workspace = temp_root / "workspace"
            artifact_dir = temp_root / "dist"
            python_spec_names = {"ruff", "mypy", "build", "twine", "file-level-coverage"}

            def ignore_generated(_directory: str, names: list[str]) -> set[str]:
                ignored = {
                    name
                    for name in names
                    if name in {".git", ".venv", "venv", "node_modules", ".tox", ".nox"}
                    or name in GENERATED_DIR_NAMES
                    or name in GENERATED_FILE_NAMES
                    or name.endswith(GENERATED_SUFFIXES)
                    or name.endswith((".pyc", ".pyo"))
                }
                return ignored

            if any(spec.get("available") and spec["name"] in python_spec_names for spec in specs):
                shutil.copytree(root, python_workspace, ignore=ignore_generated)
                artifact_dir.mkdir()

            for spec in specs:
                if not spec.get("available"):
                    continue
                command = list(spec["command"])
                run_root = python_workspace if spec["name"] in python_spec_names else root
                if spec["name"] == "build":
                    command = [*command, "--outdir", str(artifact_dir)]
                elif spec["name"] == "twine":
                    command = [item for item in command if item != "dist/*"]
                    artifacts = sorted(
                        str(path) for path in artifact_dir.glob("*") if path.is_file()
                    )
                    command.extend(artifacts or [str(artifact_dir / "missing-distribution")])
                command = _expand_command_globs(run_root, command)
                result = _run_command(run_root, command, timeout)
                result.update({"name": spec["name"], "kind": spec["kind"]})
                results.append(result)
                if result.get("exit_code") != 0:
                    failures.append(result)
    status = "fail" if failures else "warn" if missing or not run_tools else "pass"
    if failures:
        summary = "One or more build/lint/typecheck commands failed."
    elif run_tools:
        summary = "Installed build/lint/typecheck commands completed successfully; missing optional commands are reported."
    else:
        summary = "Build/lint/typecheck commands are planned; pass run_verification_tools=true to execute installed tools."
    return CheckResult(
        name="verification_tools_gate",
        status=status,
        summary=summary,
        details={
            "run_tools": run_tools,
            "python_tools_use_isolated_copy": run_tools and (root / "pyproject.toml").exists(),
            "commands": specs,
            "release_ci_required_tools": list(RELEASE_CI_REQUIRED_TOOLS),
            "missing_tools": [
                {"name": item["name"], "kind": item["kind"], "command": item["command"]}
                for item in missing
            ],
            "results": results,
        },
    )


def check_test_matrix_result(
    root: Path,
    *,
    run_matrix: bool = True,
    per_file_timeout: int = 20,
    max_files: int = 3,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    group: str = DEFAULT_READINESS_TEST_GROUP,
) -> CheckResult:
    """Run or require a bounded marker-aware test-matrix result for readiness."""

    if group not in TEST_MATRIX_GROUPS:
        return CheckResult(
            name="test_matrix_result_gate",
            status="fail",
            summary=f"Unsupported test matrix group: {group}",
            details={"group": group, "supported_groups": list(TEST_MATRIX_GROUPS)},
        )

    script = root / "scripts" / "run_test_matrix.py"
    if not script.exists():
        return CheckResult(
            name="test_matrix_result_gate",
            status="warn",
            summary="scripts/run_test_matrix.py is missing; file-level matrix result is unavailable.",
            details={"script": str(script.relative_to(root))},
        )
    if not run_matrix:
        return CheckResult(
            name="test_matrix_result_gate",
            status="warn",
            summary="Test matrix result was not run for this readiness report.",
            details={
                "recommended_command": [
                    sys.executable,
                    "scripts/run_test_matrix.py",
                    "--json",
                    "--group",
                    group,
                ],
                "planned_max_files": max_files,
                "per_file_timeout": per_file_timeout,
                "group": group,
            },
        )
    command = [
        sys.executable,
        "-B",
        "scripts/run_test_matrix.py",
        "--json",
        "--group",
        group,
        "--timeout",
        str(per_file_timeout),
    ]
    if max_files > 0:
        command.extend(["--max-files", str(max_files)])
    effective_timeout = max(
        timeout, 120 + max(1, max_files if max_files > 0 else 10) * max(1, per_file_timeout)
    )
    result = _run_command(
        root, command, effective_timeout, env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    )
    payload: dict[str, Any] = {}
    if result.get("stdout_tail"):
        try:
            payload = json.loads(str(result["stdout_tail"]))
        except json.JSONDecodeError:
            payload = {}
    ok = result.get("exit_code") == 0 and payload.get("overall_status") == "pass"
    return CheckResult(
        name="test_matrix_result_gate",
        status="pass" if ok else "fail",
        summary=(
            "Bounded test matrix completed successfully."
            if ok
            else "Bounded test matrix failed or did not produce a passing JSON report."
        ),
        details={
            "bounded": max_files > 0,
            "max_files": max_files,
            "per_file_timeout": per_file_timeout,
            "group": group,
            "command_result": result,
            "matrix_summary": {
                "overall_status": payload.get("overall_status"),
                "test_file_count": payload.get("test_file_count"),
                "candidate_test_file_count": payload.get("candidate_test_file_count"),
                "selected_test_file_count": payload.get("selected_test_file_count"),
                "executed_test_file_count": payload.get("executed_test_file_count"),
                "skipped_file_count": payload.get("skipped_file_count"),
                "file_prefilter": payload.get("file_prefilter"),
                "group": payload.get("group"),
                "marker_expr": payload.get("marker_expr"),
                "failure_count": payload.get("failure_count"),
            },
        },
    )


REQUIRED_DOCUMENTATION_FILES = (
    "README.md",
    "CHANGELOG.md",
    "PROJECT_DOCUMENTATION.md",
    "docs/quickstart.md",
    "docs/usage.md",
    "docs/testing.md",
    "docs/security.md",
    "docs/local-llm.md",
    "docs/evals.md",
    "docs/github.md",
    "docs/architecture.md",
)


def _readme_documentation_references(root: Path) -> list[str]:
    readme = root / "README.md"
    if not readme.exists():
        return []
    text = readme.read_text(encoding="utf-8", errors="replace")
    refs = re.findall(r"docs/[A-Za-z0-9_.\-/]+\.md", text)
    return sorted(set(refs))


def check_docs_presence(root: Path) -> CheckResult:
    expected = sorted(
        set(REQUIRED_DOCUMENTATION_FILES) | set(_readme_documentation_references(root))
    )
    missing = [name for name in expected if not (root / name).exists()]
    return CheckResult(
        name="documentation_presence",
        status="pass" if not missing else "fail",
        summary="Canonical and user-facing documentation files are present."
        if not missing
        else "Required user-facing or layer documentation files are missing.",
        details={
            "missing": missing,
            "checked": expected,
            "readme_references_checked": _readme_documentation_references(root),
            "static_required_docs": list(REQUIRED_DOCUMENTATION_FILES),
        },
    )


def _markdown_files_for_cli_validation(root: Path) -> list[Path]:
    candidates = [root / "README.md"]
    docs_dir = root / "docs"
    if docs_dir.exists():
        candidates.extend(sorted(docs_dir.glob("*.md")))
    return [path for path in candidates if path.exists() and path.is_file()]


def _extract_documented_cli_commands(root: Path) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for path in _markdown_files_for_cli_validation(root):
        rel = str(path.relative_to(root))
        for lineno, raw_line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            line = raw_line.strip()
            if not line or "minicodex" not in line:
                continue
            line = re.sub(r"^(?:\$|>)\s*", "", line)
            line = line.split(" #", 1)[0].strip()
            if not line or any(token in line for token in ("|", "&&", ";", "$(", "`")):
                continue
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            args: list[str] | None = None
            if tokens and tokens[0] == "minicodex":
                args = tokens[1:]
            else:
                for index, token in enumerate(tokens):
                    if token == "minicodex":
                        args = tokens[index + 1 :]
                        break
                    if (
                        token == "-m"
                        and index + 1 < len(tokens)
                        and tokens[index + 1] == "minicodex_agent.cli"
                    ):
                        args = tokens[index + 2 :]
                        break
            if args is None:
                continue
            commands.append({"file": rel, "line": lineno, "command": line, "args": args})
    return commands


def _parse_documented_cli_args_batch(
    root: Path, args_list: list[list[str]], *, timeout: int = 20
) -> list[dict[str, Any]]:
    if not args_list:
        return []
    code = r"""
import contextlib
import io
import json
import sys

from minicodex_agent.cli import parse_args

args_list = json.loads(sys.stdin.read())
results = []
for args in args_list:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        try:
            sys.argv = ["minicodex"] + list(args)
            parse_args()
            exit_code = 0
        except SystemExit as exc:
            code = exc.code
            exit_code = int(code) if isinstance(code, int) else 1
    results.append({
        "exit_code": exit_code,
        "stdout": stdout_buffer.getvalue(),
        "stderr": stderr_buffer.getvalue(),
    })
print(json.dumps(results))
""".lstrip()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            input=json.dumps(args_list),
            text=True,
            capture_output=True,
            timeout=max(timeout, 5 + len(args_list)),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return [
            {
                "exit_code": 124,
                "stdout_tail": truncate(subprocess_text(exc.stdout), 2000),
                "stderr_tail": "documented CLI parse validation timed out",
            }
            for _ in args_list
        ]
    if completed.returncode != 0:
        return [
            {
                "exit_code": completed.returncode,
                "stdout_tail": truncate(completed.stdout, 2000),
                "stderr_tail": truncate(completed.stderr, 2000),
            }
            for _ in args_list
        ]
    try:
        raw_results = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return [
            {
                "exit_code": 1,
                "stdout_tail": truncate(completed.stdout, 2000),
                "stderr_tail": truncate(completed.stderr, 2000),
            }
            for _ in args_list
        ]
    results: list[dict[str, Any]] = []
    for result in raw_results:
        results.append(
            {
                "exit_code": int(result.get("exit_code", 1)),
                "stdout_tail": truncate(str(result.get("stdout", "")), 2000),
                "stderr_tail": truncate(str(result.get("stderr", "")), 2000),
            }
        )
    return results


def check_documented_cli_commands(root: Path, *, timeout: int = 10) -> CheckResult:
    commands = _extract_documented_cli_commands(root)
    invalid: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    parse_results = _parse_documented_cli_args_batch(
        root, [command["args"] for command in commands], timeout=timeout
    )
    for command, result in zip(commands, parse_results, strict=True):
        record = {**command, "parse_result": result}
        if result["exit_code"] == 0:
            valid.append(record)
        else:
            invalid.append(record)
    return CheckResult(
        name="documentation_cli_examples",
        status="pass" if not invalid else "fail",
        summary="Documented MiniCodex CLI examples parse successfully."
        if not invalid
        else "Some documented MiniCodex CLI examples do not match the CLI parser.",
        details={
            "checked_command_count": len(commands),
            "valid_command_count": len(valid),
            "invalid_command_count": len(invalid),
            "invalid_commands": invalid[:20],
            "checked_files": [
                str(path.relative_to(root)) for path in _markdown_files_for_cli_validation(root)
            ],
        },
    )


def build_test_matrix_plan(
    root: Path, *, per_file_timeout: int = 60, group: str = "all"
) -> dict[str, Any]:
    test_files = sorted(
        path.relative_to(root).as_posix() for path in (root / "tests").glob("test_*.py")
    )
    if group not in TEST_MATRIX_GROUPS:
        group = "all"
    groups = {
        "fast": {
            "marker_expr": "unit and not slow and not subprocess and not sandbox",
            "description": "Fast local gate for pull requests and final-readiness smoke checks.",
            "timeout_seconds_each": min(per_file_timeout, 30),
        },
        "unit": {
            "marker_expr": "unit",
            "description": "All in-process unit tests.",
            "timeout_seconds_each": min(per_file_timeout, 30),
        },
        "integration": {
            "marker_expr": "integration",
            "description": "Cross-module workflow tests.",
            "timeout_seconds_each": max(per_file_timeout, 45),
        },
        "subprocess": {
            "marker_expr": "subprocess",
            "description": "Tests that spawn subprocesses, git, pytest, or command runners.",
            "timeout_seconds_each": max(per_file_timeout, 45),
        },
        "sandbox": {
            "marker_expr": "sandbox",
            "description": "Sandbox/workspace isolation and command-policy tests.",
            "timeout_seconds_each": max(per_file_timeout, 60),
        },
        "slow": {
            "marker_expr": "slow",
            "description": "Longer or more variable tests intended for scheduled/full CI.",
            "timeout_seconds_each": max(per_file_timeout, 90),
        },
        "all": {
            "marker_expr": "",
            "description": "Full file matrix across every test file.",
            "timeout_seconds_each": per_file_timeout,
        },
    }
    commands = [
        {
            "name": "syntax",
            "kind": "syntax",
            "command": [
                sys.executable,
                "scripts/check_python_syntax.py",
                "src",
                "tests",
                "scripts",
            ],
            "note": "Parses Python files with ast.parse only; it never calls pytest or the test matrix and does not create bytecode artifacts.",
            "executes_tests": False,
            "timeout_seconds": 120,
        },
        {
            "name": "pytest-file-matrix",
            "group": group,
            "command": [sys.executable, "scripts/run_test_matrix.py", "--group", group, "--json"],
            "env": {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            "timeout_seconds_each": groups[group]["timeout_seconds_each"],
            "marker_expr": groups[group]["marker_expr"],
            "test_files": test_files,
        },
    ]
    if (root / "pyproject.toml").exists():
        commands.append(
            {
                "name": "build-check",
                "command": [sys.executable, "-m", "build"],
                "timeout_seconds": 180,
                "optional_dependency": "build",
            }
        )
    return {
        "schema_version": 1,
        "purpose": "Avoid monolithic pytest timeouts by running marker-aware deterministic file-level batches.",
        "selected_group": group,
        "groups": groups,
        "test_file_count": len(test_files),
        "commands": commands,
        "recommended_ci_commands": [
            "python scripts/check_python_syntax.py src tests scripts",
            "python scripts/run_test_matrix.py --group fast --json",
            "python scripts/run_test_matrix.py --group integration --json",
            "python scripts/run_test_matrix.py --group subprocess --json",
            "python scripts/run_test_matrix.py --group sandbox --json",
            "python scripts/run_test_matrix.py --group slow --json",
            "python scripts/run_coverage_gate.py --group all --fail-under 85 --json",
        ],
        "notes": [
            "Use the bundled scripts/run_test_matrix.py for JSON output and JSONL progress streaming.",
            "Run fast/unit groups on pull requests; run subprocess/sandbox/slow groups in scheduled or full CI.",
            "Use scripts/run_coverage_gate.py for aggregate coverage; avoid package-wide monolithic pytest coverage gates.",
        ],
    }


def final_readiness_report(
    root: Path,
    *,
    include_cli_smoke: bool = True,
    include_test_matrix: bool = True,
    include_security_audit: bool = True,
    include_verification_tools: bool = True,
    run_test_matrix: bool = True,
    test_matrix_max_files: int = 3,
    test_matrix_timeout: int = 20,
    test_matrix_group: str = DEFAULT_READINESS_TEST_GROUP,
    run_verification_tools: bool = False,
    verification_timeout: int = DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = 30000,
) -> str:
    """Render a deterministic final-readiness report without leaving bytecode artifacts."""

    pre_cleanup = cleanup_python_bytecode(root)
    checks = [
        check_version_alignment(root),
        check_changelog_structure(root),
        check_positioning_consistency(root),
        check_format_policy_consistency(root),
        check_dev_dependency_hygiene(root),
        check_cli_help_language(root),
        check_generated_artifacts(root),
        check_syntax(root),
        check_registry_alignment(root),
        check_docs_presence(root),
        check_documented_cli_commands(root),
    ]
    if include_security_audit:
        checks.append(check_security_audit_gate(root))
    if include_verification_tools:
        checks.append(
            check_verification_tools(
                root,
                run_tools=run_verification_tools,
                timeout=verification_timeout,
            )
        )
    if include_test_matrix:
        checks.append(
            check_test_matrix_result(
                root,
                run_matrix=run_test_matrix,
                per_file_timeout=test_matrix_timeout,
                max_files=test_matrix_max_files,
                timeout=timeout,
                group=test_matrix_group,
            )
        )
    if include_cli_smoke:
        checks.append(check_cli_smoke(root, timeout=timeout))
    status_order = {"fail": 3, "warn": 2, "pass": 1}
    worst = max((status_order.get(check.status, 0) for check in checks), default=0)
    overall = "fail" if worst == 3 else "warn" if worst == 2 else "pass"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "overall_status": overall,
        "version": _pyproject_version(root),
        "checks": [check.to_dict() for check in checks],
        "recommended_next_commands": [
            "python scripts/run_test_matrix.py --group fast --json",
            "python scripts/run_test_matrix.py --group integration --json",
            "ruff check .",
            "ruff format --check .",
            "mypy src/minicodex_agent",
            "python scripts/run_coverage_gate.py --group all --fail-under 85 --json",
            "python -m build",
            "twine check dist/*",
            "python -m minicodex_agent.cli --security-audit --root .",
            "python -m minicodex_agent.cli --help",
        ],
    }
    if include_test_matrix:
        payload["test_matrix_plan"] = build_test_matrix_plan(root, group=test_matrix_group)
    post_cleanup = cleanup_python_bytecode(root)
    payload["bytecode_cleanup"] = {"before_checks": pre_cleanup, "after_checks": post_cleanup}
    return _render_prefixed_json("FINAL_READINESS_JSON", payload, max_chars)


def _zip_member_files(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        return sorted(info.filename for info in archive.infolist() if not info.is_dir())


def _zip_common_root_prefix(files: list[str]) -> str:
    first_parts = [path.split("/", 1)[0] for path in files if "/" in path]
    if first_parts and len(first_parts) == len(files) and len(set(first_parts)) == 1:
        return first_parts[0] + "/"
    return ""


def _strip_zip_prefix(path: str, prefix: str) -> str:
    return path[len(prefix) :] if prefix and path.startswith(prefix) else path


def _version_from_pyproject_text(text: str) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def _zip_text(zip_path: Path, member: str) -> str:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            with archive.open(member) as handle:
                return handle.read(500_000).decode("utf-8", errors="replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return ""


def release_package_manifest(
    root: Path, *, from_zip: str | Path | None = None, max_chars: int = 30000
) -> str:
    """Render a release-package manifest and cleanliness summary.

    When ``from_zip`` is provided, every artifact-specific field is derived from
    the immutable zip member list and zip file contents. The working-tree
    ``root`` is used only to resolve a relative zip path; it must never influence
    version, document, source-module, test-file, or generated-artifact counts for
    a zip-sourced manifest.
    """

    zip_path = Path(from_zip).expanduser() if from_zip else None
    if zip_path is not None:
        if not zip_path.is_absolute():
            zip_path = root / zip_path
        if not zip_path.exists() or not zip_path.is_file():
            payload = {
                "schema_version": 1,
                "source": "zip",
                "metadata_source": "zip_members",
                "root_used_for_metadata": False,
                "zip_path": str(zip_path),
                "error": "zip file not found",
            }
            return _render_prefixed_json("RELEASE_PACKAGE_MANIFEST_JSON", payload, max_chars)
        try:
            zip_member_files = _zip_member_files(zip_path)
        except zipfile.BadZipFile as exc:
            payload = {
                "schema_version": 1,
                "source": "zip",
                "metadata_source": "zip_members",
                "root_used_for_metadata": False,
                "zip_path": str(zip_path),
                "error": f"bad zip file: {exc}",
            }
            return _render_prefixed_json("RELEASE_PACKAGE_MANIFEST_JSON", payload, max_chars)

        artifact_root_prefix = _zip_common_root_prefix(zip_member_files)
        artifact_root_name = artifact_root_prefix.rstrip("/")
        artifact_name = zip_path.stem
        artifact_name_matches_root = bool(
            artifact_root_name and artifact_name == artifact_root_name
        )
        relative_files = sorted(
            _strip_zip_prefix(path, artifact_root_prefix) for path in zip_member_files
        )
        relative_to_member = {
            _strip_zip_prefix(path, artifact_root_prefix): path for path in zip_member_files
        }
        pyproject_member = relative_to_member.get("pyproject.toml", "")
        version = (
            _version_from_pyproject_text(_zip_text(zip_path, pyproject_member))
            if pyproject_member
            else ""
        )
        top_level_docs = sorted(
            path for path in relative_files if "/" not in path and path.endswith(".md")
        )
        source_modules = sum(
            1
            for path in relative_files
            if path.startswith("src/minicodex_agent/") and path.endswith(".py")
        )
        test_files = sum(
            1
            for path in relative_files
            if path.startswith("tests/")
            and Path(path).name.startswith("test_")
            and path.endswith(".py")
        )
        generated = [path for path in relative_files if _is_generated(Path(path))]
        payload = {
            "schema_version": 1,
            "source": "zip",
            "metadata_source": "zip_members",
            "root_used_for_metadata": False,
            "version": version,
            "zip_path": str(zip_path),
            "artifact_root_prefix": artifact_root_prefix,
            "artifact_root_name": artifact_root_name,
            "artifact_name": artifact_name,
            "artifact_name_matches_root": artifact_name_matches_root,
            "file_count": len(zip_member_files),
            "normalized_file_count": len(relative_files),
            "generated_artifact_count": len(generated),
            "generated_artifacts": sorted(generated)[:200],
            "top_level_docs": top_level_docs,
            "source_modules": source_modules,
            "test_files": test_files,
            "recommended_clean_command": "python -m minicodex_agent.cli --clean-generated-artifacts --root .",
            "recommended_zip_command": "python -m minicodex_agent.cli --release-package-manifest --from-zip path/to/release.zip --root .",
        }
        return _render_prefixed_json("RELEASE_PACKAGE_MANIFEST_JSON", payload, max_chars)

    files = [str(path.relative_to(root)) for path in _iter_project_files(root)]
    generated = [path for path in files if _is_generated(Path(path))]
    payload = {
        "schema_version": 1,
        "source": "working_tree",
        "metadata_source": "working_tree",
        "root_used_for_metadata": True,
        "version": _pyproject_version(root),
        "zip_path": "",
        "artifact_root_prefix": "",
        "artifact_root_name": root.name,
        "artifact_name": "",
        "artifact_name_matches_root": None,
        "file_count": len(files),
        "normalized_file_count": len(files),
        "generated_artifact_count": len(generated),
        "generated_artifacts": sorted(generated)[:200],
        "top_level_docs": sorted(str(path.name) for path in root.glob("*.md")),
        "source_modules": len(list((root / "src" / "minicodex_agent").rglob("*.py"))),
        "test_files": len(list((root / "tests").rglob("test_*.py"))),
        "recommended_clean_command": "python -m minicodex_agent.cli --clean-generated-artifacts --root .",
        "recommended_zip_command": "python -m minicodex_agent.cli --release-package-manifest --from-zip path/to/release.zip --root .",
    }
    return _render_prefixed_json("RELEASE_PACKAGE_MANIFEST_JSON", payload, max_chars)
