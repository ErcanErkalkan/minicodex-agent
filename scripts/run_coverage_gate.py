#!/usr/bin/env python3
"""Run MiniCodex coverage as a bounded marker-aware file-level gate.

This complements ``scripts/run_test_matrix.py``.  It intentionally avoids one
large ``pytest --cov`` process because that can inherit pipes from nested
subprocess tests and hang in constrained CI runners.  Instead, it erases any
previous coverage data, runs pytest once per selected file with a per-file
``timeout`` wrapper, appends coverage data, reports the aggregate result, and
optionally removes the generated ``.coverage`` file.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from run_test_matrix import (  # type: ignore[import-not-found]
    DEFAULT_GROUP_TIMEOUTS,
    GROUP_MARKERS,
    _collect_test_files,
    _command_with_timeout,
    _emit_progress,
    _group_expression,
    _terminate_process_tree,
    syntax_check,
)


def _module_available(module: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-B", "-c", f"import {module}"],
        text=True,
        capture_output=True,
        timeout=10,
        shell=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return result.returncode == 0


def _cleanup_coverage_files(root: Path) -> list[str]:
    removed: list[str] = []
    for pattern in (".coverage", ".coverage.*", "coverage.xml"):
        for path in root.glob(pattern):
            if path.is_file():
                path.unlink()
                removed.append(str(path.relative_to(root)))
    return sorted(set(removed))


def _run_coverage_command(root: Path, command: list[str], timeout: int) -> dict[str, object]:
    """Run a coverage command without disabling pytest plugin autoload.

    The matrix runner deliberately disables plugin autoload.  Coverage is the one
    gate that must allow pytest-cov to load, while still avoiding PIPE-based
    output capture that can hang with nested subprocess tests.
    """

    started = time.time()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_path = str(root / "src")
    env["PYTHONPATH"] = (
        src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath
    )
    env.setdefault("PYTEST_ADDOPTS", "-p no:cacheprovider")
    env["COVERAGE_FILE"] = str(root / ".coverage")
    effective_command, uses_external_timeout = _command_with_timeout(command, timeout)
    timed_out = False

    with tempfile.TemporaryDirectory(prefix="minicodex-coverage-") as tmp:
        stdout_path = Path(tmp) / "stdout.txt"
        stderr_path = Path(tmp) / "stderr.txt"
        with (
            stdout_path.open("w+", encoding="utf-8") as stdout_fh,
            stderr_path.open("w+", encoding="utf-8") as stderr_fh,
        ):
            popen_kwargs: dict[str, Any] = {
                "cwd": str(root),
                "stdin": subprocess.DEVNULL,
                "text": True,
                "stdout": stdout_fh,
                "stderr": stderr_fh,
                "shell": False,
                "env": env,
            }
            if os.name == "posix" and not uses_external_timeout:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(effective_command, **popen_kwargs)
            try:
                exit_code = process.wait(timeout=None if uses_external_timeout else timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process_tree(process)
                exit_code = 124
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    exit_code = 124
            if uses_external_timeout and exit_code in {124, 137}:
                timed_out = True
            stdout_fh.flush()
            stderr_fh.flush()
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")

    payload: dict[str, object] = {
        "command": command,
        "exit_code": exit_code,
        "duration_seconds": round(time.time() - started, 3),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }
    if exit_code == 5 and "deselected" in stdout + stderr:
        payload["no_tests_selected"] = True
        payload["exit_code"] = 0
        payload["original_exit_code"] = 5
    if timed_out:
        payload["timeout_seconds"] = timeout
    return payload


def _selected_jobs(
    root: Path,
    *,
    groups: list[str],
    max_files: int,
    marker_expr: str | None,
    exclude_slow: bool,
    prefilter: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    if marker_expr is not None and len(groups) != 1:
        raise ValueError("--marker-expr can only be used with one --group")
    for group in groups:
        effective_prefilter = prefilter and marker_expr is None
        files, candidate_count = _collect_test_files(
            root, group, max_files, prefilter=effective_prefilter
        )
        expr = _group_expression(group, marker_expr, exclude_slow)
        group_summaries.append(
            {
                "group": group,
                "candidate_test_file_count": candidate_count,
                "selected_test_file_count": len(files),
                "marker_expr": expr,
                "file_prefilter": effective_prefilter,
            }
        )
        for file in files:
            jobs.append({"file": file, "group": group, "marker_expr": expr})
    return jobs, {"groups": group_summaries}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run pytest coverage by file with marker groups and per-file timeouts."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--group",
        choices=sorted(GROUP_MARKERS),
        action="append",
        default=None,
        help="Marker group to include. Can be passed more than once. Defaults to fast.",
    )
    parser.add_argument(
        "--marker-expr",
        default=None,
        help="Custom pytest -m expression. Overrides the selected group expression.",
    )
    parser.add_argument(
        "--exclude-slow",
        action="store_true",
        help="Append 'not slow' to the selected marker expression.",
    )
    parser.add_argument(
        "--no-file-prefilter",
        action="store_true",
        help="Do not prefilter files by group; rely on pytest -m deselection.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Per-file timeout. 0 uses the largest selected group default.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Run at most this many test files per group; 0 means all files.",
    )
    parser.add_argument("--fail-under", type=int, default=85, help="Coverage percentage threshold.")
    parser.add_argument(
        "--json", action="store_true", help="Print full JSON report instead of concise lines."
    )
    parser.add_argument(
        "--jsonl-progress",
        default="",
        help="Optional file path for streaming JSONL progress events.",
    )
    parser.add_argument(
        "--progress-to-stderr", action="store_true", help="Emit JSONL progress events to stderr."
    )
    parser.add_argument(
        "--keep-data", action="store_true", help="Keep .coverage files after reporting."
    )
    parser.add_argument(
        "--stop-on-fail", action="store_true", help="Stop on the first failing test file."
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    groups = args.group or ["fast"]
    per_file_timeout = (
        args.timeout if args.timeout > 0 else max(DEFAULT_GROUP_TIMEOUTS[group] for group in groups)
    )
    progress_path = Path(args.jsonl_progress).resolve() if args.jsonl_progress else None
    if progress_path:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text("", encoding="utf-8")

    missing_modules = [
        name for name in ("pytest", "pytest_cov", "coverage") if not _module_available(name)
    ]
    if missing_modules:
        report = {
            "schema_version": 1,
            "overall_status": "fail",
            "reason": "Missing coverage dependencies.",
            "missing_modules": missing_modules,
            "recommended_install": 'python -m pip install -e ".[dev]"',
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    pre_cleanup = _cleanup_coverage_files(root)
    results: list[dict[str, object]] = []
    syntax = syntax_check(root)
    syntax["name"] = "syntax"
    syntax["group"] = "syntax"
    results.append(syntax)
    _emit_progress(
        progress_path,
        {"event": "finished", "name": "syntax", "exit_code": syntax["exit_code"]},
        to_stderr=args.progress_to_stderr,
    )
    if syntax["exit_code"] != 0:
        report = {
            "schema_version": 1,
            "overall_status": "fail",
            "results": results,
            "pre_cleanup": pre_cleanup,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    erase = _run_coverage_command(root, [sys.executable, "-B", "-m", "coverage", "erase"], 60)
    erase["name"] = "coverage-erase"
    erase["group"] = "coverage"
    results.append(erase)
    if erase["exit_code"] != 0:
        report = {
            "schema_version": 1,
            "overall_status": "fail",
            "results": results,
            "pre_cleanup": pre_cleanup,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    jobs, selection_summary = _selected_jobs(
        root,
        groups=groups,
        max_files=args.max_files,
        marker_expr=args.marker_expr,
        exclude_slow=args.exclude_slow,
        prefilter=not args.no_file_prefilter,
    )

    for job in jobs:
        file = Path(job["file"])
        rel = str(file.relative_to(root))
        group = str(job["group"])
        expr = str(job["marker_expr"])
        command = [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov=minicodex_agent",
            "--cov-append",
            "--cov-report=",
            "--cov-fail-under=0",
        ]
        if expr:
            command.extend(["-m", expr])
        command.append(rel)
        _emit_progress(
            progress_path,
            {"event": "started", "name": rel, "group": group},
            to_stderr=args.progress_to_stderr,
        )
        result = _run_coverage_command(root, command, per_file_timeout)
        result["name"] = rel
        result["group"] = group
        result["marker_expr"] = expr
        results.append(result)
        if not args.json:
            status = (
                "SKIP"
                if result.get("no_tests_selected")
                else "PASS"
                if result["exit_code"] == 0
                else "FAIL"
            )
            print(f"{status:4} {result['duration_seconds']:>7}s {group:>10} {rel}", flush=True)
        _emit_progress(
            progress_path,
            {
                "event": "finished",
                "name": rel,
                "group": group,
                "exit_code": result["exit_code"],
                "duration_seconds": result["duration_seconds"],
                "no_tests_selected": bool(result.get("no_tests_selected")),
            },
            to_stderr=args.progress_to_stderr,
        )
        if result["exit_code"] != 0 and args.stop_on_fail:
            break

    failures = [item for item in results if item["exit_code"] != 0]
    coverage_report: dict[str, object] | None = None
    if not failures:
        command = [
            sys.executable,
            "-B",
            "-m",
            "coverage",
            "report",
            "--show-missing",
            f"--fail-under={args.fail_under}",
        ]
        coverage_report = _run_coverage_command(root, command, 120)
        coverage_report["name"] = "coverage-report"
        coverage_report["group"] = "coverage"
        results.append(coverage_report)
        if coverage_report["exit_code"] != 0:
            failures.append(coverage_report)

    post_cleanup: list[str] = []
    if not args.keep_data:
        post_cleanup = _cleanup_coverage_files(root)

    report = {
        "schema_version": 1,
        "overall_status": "pass" if not failures else "fail",
        "groups": groups,
        "per_file_timeout": per_file_timeout,
        "bounded": args.max_files > 0,
        "max_files": args.max_files,
        "fail_under": args.fail_under,
        "selected_job_count": len(jobs),
        "failure_count": len(failures),
        "pre_cleanup": pre_cleanup,
        "post_cleanup": post_cleanup,
        "selection": selection_summary,
        "coverage_stdout_tail": coverage_report.get("stdout_tail") if coverage_report else "",
        "coverage_stderr_tail": coverage_report.get("stderr_tail") if coverage_report else "",
        "results": results,
        "recommended_commands": [
            "python scripts/run_coverage_gate.py --group all --fail-under 85 --json",
        ],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
