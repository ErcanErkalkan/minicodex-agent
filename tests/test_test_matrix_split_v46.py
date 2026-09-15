from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from minicodex_agent.quality_gate import build_test_matrix_plan, check_test_matrix_result


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _body(text: str) -> dict[str, object]:
    return json.loads(text.split("\n", 1)[1])


def test_test_matrix_plan_exposes_marker_groups() -> None:
    plan = build_test_matrix_plan(_repo_root(), group="fast", per_file_timeout=20)
    assert plan["schema_version"] == 1
    assert plan["selected_group"] == "fast"
    assert "integration" in plan["groups"]
    assert "subprocess" in plan["groups"]
    assert "sandbox" in plan["groups"]
    assert "slow" in plan["groups"]
    assert "--group fast" in "\n".join(plan["recommended_ci_commands"])


def test_check_test_matrix_result_runs_fast_bounded_group() -> None:
    result = check_test_matrix_result(
        _repo_root(),
        run_matrix=True,
        per_file_timeout=20,
        max_files=1,
        timeout=45,
        group="fast",
    )
    assert result.status == "pass"
    assert result.details["group"] == "fast"
    assert result.details["matrix_summary"]["group"] == "fast"


def test_run_test_matrix_lists_groups() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_test_matrix.py", "--list-groups"],
        cwd=_repo_root(),
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    payload = json.loads(completed.stdout)
    assert payload["groups"]["fast"] == "unit and not slow and not subprocess and not sandbox"
    assert "slow" in payload["default_timeouts"]


def test_run_test_matrix_writes_jsonl_progress(tmp_path: Path) -> None:
    root = tmp_path / "project"
    tests = root / "tests"
    scripts = root / "scripts"
    tests.mkdir(parents=True)
    scripts.mkdir()
    (tests / "test_demo.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    # Copy the runner only; no package imports are needed for the temporary fixture.
    runner = _repo_root() / "scripts" / "run_test_matrix.py"
    (scripts / "run_test_matrix.py").write_text(
        runner.read_text(encoding="utf-8"), encoding="utf-8"
    )
    progress = tmp_path / "progress.jsonl"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_test_matrix.py",
            "--root",
            str(root),
            "--group",
            "all",
            "--json",
            "--jsonl-progress",
            str(progress),
            "--timeout",
            "20",
        ],
        cwd=root,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
    )
    payload = json.loads(completed.stdout)
    assert payload["overall_status"] == "pass"
    events = [json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()]
    assert any(event["event"] == "started" for event in events)
    assert any(event["event"] == "finished" for event in events)
    assert not list(root.rglob("__pycache__"))
    assert not (root / ".pytest_cache").exists()
