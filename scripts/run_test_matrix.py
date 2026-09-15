#!/usr/bin/env python3
"""Run MiniCodex tests as a marker-aware file-level matrix.

Why this exists:
- The full suite contains fast unit tests plus integration/subprocess/sandbox
  tests.  A single monolithic ``pytest -q`` process can be slow or can hang in
  constrained environments when nested subprocesses inherit pipes.
- This runner executes tests by file with per-file timeouts, disables bytecode
  and pytest cache artifacts, supports marker groups, and can stream JSONL
  progress while still producing a final JSON summary.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

GROUP_MARKERS: dict[str, str] = {
    "all": "",
    "unit": "unit",
    "fast": "unit and not slow and not subprocess and not sandbox",
    "integration": "integration",
    "subprocess": "subprocess",
    "sandbox": "sandbox",
    "slow": "slow",
}

DEFAULT_GROUP_TIMEOUTS: dict[str, int] = {
    "fast": 20,
    "unit": 20,
    "integration": 45,
    "subprocess": 45,
    "sandbox": 60,
    "slow": 90,
    "all": 60,
}

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


def _base_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    # Keep pytest deterministic and avoid writing .pytest_cache.
    env.setdefault("PYTEST_ADDOPTS", "-p no:cacheprovider")
    if extra:
        env.update(extra)
    return env


def _command_with_timeout(command: list[str], timeout: int) -> tuple[list[str], bool]:
    uses_external_timeout = os.name == "posix" and shutil.which("timeout") is not None
    if uses_external_timeout:
        return ["timeout", "--kill-after=5", str(timeout), *command], True
    return command, False


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate a timed-out command and all of its descendants."""

    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=10,
            shell=False,
            check=False,
        )
        if completed.returncode != 0 and process.poll() is None:
            process.kill()
        return
    killpg = getattr(os, "killpg", None)
    sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
    try:
        if killpg is None:
            raise OSError("process-group termination is unavailable")
        killpg(process.pid, sigkill)
    except OSError:
        process.kill()


def run(
    command: list[str], *, cwd: Path, timeout: int, env: dict[str, str] | None = None
) -> dict[str, object]:
    started = time.time()
    merged_env = _base_env(env)

    # Write child output to temporary files rather than PIPEs. Some tests spawn
    # nested subprocesses; if a grandchild inherits a pipe, communicate() can
    # wait forever even after the top-level pytest process exits or is killed.
    effective_command, uses_external_timeout = _command_with_timeout(command, timeout)

    with tempfile.TemporaryDirectory(prefix="minicodex-test-") as tmp:
        stdout_path = Path(tmp) / "stdout.txt"
        stderr_path = Path(tmp) / "stderr.txt"
        with (
            stdout_path.open("w+", encoding="utf-8") as stdout_fh,
            stderr_path.open("w+", encoding="utf-8") as stderr_fh,
        ):
            popen_kwargs: dict[str, Any] = {
                "cwd": str(cwd),
                "stdin": subprocess.DEVNULL,
                "text": True,
                "stdout": stdout_fh,
                "stderr": stderr_fh,
                "shell": False,
                "env": merged_env,
            }
            if os.name == "posix" and not uses_external_timeout:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(effective_command, **popen_kwargs)
            timed_out = False
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


def syntax_check(root: Path) -> dict[str, object]:
    started = time.time()
    errors: list[dict[str, object]] = []
    for base in (root / "src", root / "tests", root / "scripts"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except Exception as exc:  # noqa: BLE001 - report all syntax/read failures
                errors.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "command": [sys.executable, "scripts/check_python_syntax.py", "src", "tests", "scripts"],
        "exit_code": 0 if not errors else 1,
        "duration_seconds": round(time.time() - started, 3),
        "stdout_tail": "",
        "stderr_tail": json.dumps(errors, ensure_ascii=False)[-4000:] if errors else "",
        "errors": errors,
    }


def _emit_progress(path: Path | None, event: dict[str, Any], *, to_stderr: bool) -> None:
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    if path is not None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    if to_stderr:
        print(line, file=sys.stderr, flush=True)


def _file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")[:300_000]
    except OSError:
        return ""


def _classify_file(path: Path) -> set[str]:
    filename = path.name.lower()
    text = _file_text(path)
    markers: set[str] = set()
    if any(keyword in filename for keyword in INTEGRATION_FILE_KEYWORDS):
        markers.add("integration")
    if any(keyword in filename for keyword in SANDBOX_FILE_KEYWORDS):
        markers.add("sandbox")
    if any(keyword in filename for keyword in SLOW_FILE_KEYWORDS):
        markers.add("slow")
    if any(needle in text for needle in SUBPROCESS_TEXT_NEEDLES):
        markers.add("subprocess")
    if not markers:
        markers.add("unit")
    return markers


def _matches_group(path: Path, group: str) -> bool:
    if group == "all":
        return True
    markers = _classify_file(path)
    if group == "fast":
        return "unit" in markers and not markers.intersection({"slow", "subprocess", "sandbox"})
    return group in markers


def _collect_test_files(
    root: Path, group: str, max_files: int, *, prefilter: bool
) -> tuple[list[Path], int]:
    discovered = sorted((root / "tests").glob("test_*.py"))
    candidates = (
        [path for path in discovered if _matches_group(path, group)] if prefilter else discovered
    )
    selected = candidates[:max_files] if max_files > 0 else candidates
    return selected, len(candidates)


def _group_expression(group: str, marker_expr: str | None, exclude_slow: bool) -> str:
    expr = marker_expr if marker_expr is not None else GROUP_MARKERS[group]
    if exclude_slow:
        expr = f"({expr}) and not slow" if expr else "not slow"
    return expr


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run pytest by file with per-file timeouts and marker groups."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--timeout", type=int, default=0, help="Per-file timeout. 0 uses a group-specific default."
    )
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
        "--max-files",
        type=int,
        default=0,
        help="Run at most this many test files after syntax; 0 means all files.",
    )
    parser.add_argument("--stop-on-fail", action="store_true")
    parser.add_argument(
        "--group", choices=sorted(GROUP_MARKERS), default="all", help="Marker group to run."
    )
    parser.add_argument(
        "--marker-expr", default=None, help="Custom pytest -m marker expression. Overrides --group."
    )
    parser.add_argument(
        "--exclude-slow",
        action="store_true",
        help="Append 'not slow' to the selected marker expression.",
    )
    parser.add_argument(
        "--no-file-prefilter",
        action="store_true",
        help="Do not prefilter test files by group; rely only on pytest -m deselection.",
    )
    parser.add_argument(
        "--list-groups", action="store_true", help="Print supported groups and exit."
    )
    args = parser.parse_args()

    if args.list_groups:
        print(
            json.dumps(
                {"groups": GROUP_MARKERS, "default_timeouts": DEFAULT_GROUP_TIMEOUTS},
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    root = Path(args.root).resolve()
    per_file_timeout = args.timeout if args.timeout > 0 else DEFAULT_GROUP_TIMEOUTS[args.group]
    discovered_test_files = sorted((root / "tests").glob("test_*.py"))
    prefilter = not args.no_file_prefilter and args.marker_expr is None
    test_files, candidate_file_count = _collect_test_files(
        root, args.group, args.max_files, prefilter=prefilter
    )
    marker_expr = _group_expression(args.group, args.marker_expr, args.exclude_slow)
    progress_path = Path(args.jsonl_progress).resolve() if args.jsonl_progress else None
    if progress_path:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text("", encoding="utf-8")

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
    if syntax["exit_code"] != 0 and args.stop_on_fail:
        early_report = {"overall_status": "fail", "results": results}
        print(json.dumps(early_report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    for file in test_files:
        rel = file.relative_to(root).as_posix()
        command = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if marker_expr:
            command.extend(["-m", marker_expr])
        command.append(rel)
        _emit_progress(
            progress_path,
            {"event": "started", "name": rel, "group": args.group},
            to_stderr=args.progress_to_stderr,
        )
        result = run(command, cwd=root, timeout=per_file_timeout)
        result["name"] = rel
        result["group"] = args.group
        result["marker_expr"] = marker_expr
        results.append(result)
        if not args.json:
            status = (
                "SKIP"
                if result.get("no_tests_selected")
                else "PASS"
                if result["exit_code"] == 0
                else "FAIL"
            )
            print(f"{status:4} {result['duration_seconds']:>7}s {rel}", flush=True)
        _emit_progress(
            progress_path,
            {
                "event": "finished",
                "name": rel,
                "group": args.group,
                "exit_code": result["exit_code"],
                "duration_seconds": result["duration_seconds"],
                "no_tests_selected": bool(result.get("no_tests_selected")),
            },
            to_stderr=args.progress_to_stderr,
        )
        if result["exit_code"] != 0 and args.stop_on_fail:
            break

    failures = [item for item in results if item["exit_code"] != 0]
    selected_files = len(test_files)
    skipped_files = sum(1 for item in results if item.get("no_tests_selected"))
    report: dict[str, Any] = {
        "schema_version": 2,
        "overall_status": "pass" if not failures else "fail",
        "group": args.group,
        "marker_expr": marker_expr,
        "test_file_count": len(discovered_test_files),
        "candidate_test_file_count": candidate_file_count,
        "selected_test_file_count": selected_files,
        "executed_test_file_count": selected_files,
        "file_prefilter": prefilter,
        "skipped_file_count": skipped_files,
        "bounded": args.max_files > 0,
        "max_files": args.max_files,
        "per_file_timeout": per_file_timeout,
        "failure_count": len(failures),
        "results": results,
        "recommended_commands": [
            "python scripts/run_test_matrix.py --group fast --json",
            "python scripts/run_test_matrix.py --group integration --json",
            "python scripts/run_test_matrix.py --group subprocess --json",
            "python scripts/run_test_matrix.py --group sandbox --json",
            "python scripts/run_test_matrix.py --group slow --json",
        ],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
