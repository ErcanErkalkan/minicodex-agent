import json

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.test_ci import (
    classify_failure_output,
    detect_flaky_tests,
    plan_tests,
    summarize_ci_log,
)
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class _Logger:
    def write_tool_call(self, *_args, **_kwargs):
        pass

    def write_observation(self, *_args, **_kwargs):
        pass


def _ctx(root, *, dry_run=True):
    config = AgentConfig(
        root=root,
        model="stub",
        provider="stub",
        approval="auto",
        dry_run=dry_run,
        log_enabled=False,
        project_config_enabled=False,
    )
    state = AgentState(goal="test", project_profile=detect_project(root))
    return ToolContext(
        config=config,
        state=state,
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_test_ci_actions_are_registered():
    registry = get_tool_registry()
    for action in [
        "plan_tests",
        "run_targeted_tests",
        "classify_test_failure",
        "summarize_ci_log",
        "detect_flaky_tests",
    ]:
        assert action in ACTION_SPECS
        assert action in registry


def test_plan_tests_prefers_exact_pytest_failure_node(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_math.py").write_text("def test_add():\n    assert 1 == 2\n", encoding="utf-8")
    output = "FAILED tests/test_math.py::test_add - AssertionError\nExit code: 1"

    plan = plan_tests(tmp_path, detect_project(tmp_path), failure_output=output)

    assert plan.commands
    assert plan.commands[0].command == "pytest -q tests/test_math.py::test_add"
    assert plan.failed_tests == ("tests/test_math.py::test_add",)


def test_plan_tests_maps_changed_python_source_to_matching_test(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "calculator.py").write_text("def add(a,b): return a+b\n", encoding="utf-8")
    (tests / "test_calculator.py").write_text("def test_add(): pass\n", encoding="utf-8")

    plan = plan_tests(tmp_path, detect_project(tmp_path), changed_files=["src/calculator.py"])
    commands = [item.command for item in plan.commands]

    assert "pytest -q tests/test_calculator.py" in commands
    assert "pytest -q" in commands


def test_classify_failure_extracts_category_locations_and_actions(tmp_path):
    app = tmp_path / "app.py"
    app.write_text("def f():\n    return 1\n", encoding="utf-8")
    output = 'Traceback (most recent call last):\n  File "app.py", line 2, in f\nAssertionError: expected 2\nFAILED tests/test_app.py::test_f\n'

    classification = classify_failure_output(tmp_path, output)

    assert classification.category == "assertion"
    assert classification.failed_tests == ("tests/test_app.py::test_f",)
    assert classification.locations[0]["path"] == "app.py"
    assert classification.recommended_next_actions


def test_summarize_ci_log_detects_ci_and_failing_steps(tmp_path):
    output = "GitHub Actions workflow\nRun pytest -q\n##[error]Process completed with exit code 1\nFAILED tests/test_api.py::test_get\n"

    summary = summarize_ci_log(tmp_path, output)

    assert summary["ci_detected"] is True
    assert summary["category"] in {"test", "assertion", "unknown"}
    assert summary["failed_tests"] == ("tests/test_api.py::test_get",)
    assert summary["failing_steps"]


def test_detect_flaky_tests_uses_keywords_and_inconsistent_reruns():
    first = "FAILED tests/test_api.py::test_slow - timeout\nflaky rerun requested"
    second = "PASSED tests/test_api.py::test_slow"

    result = detect_flaky_tests(first, prior_outputs=[second])

    assert result["likely_flaky"] is True
    assert "tests/test_api.py::test_slow" in result["inconsistent_tests"]


def test_plan_tests_tool_returns_json(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text("def test_core(): pass\n", encoding="utf-8")

    out = dispatch_tool(_ctx(tmp_path), "plan_tests", {"changed_files": ["tests/test_core.py"]})
    data = json.loads(out)

    assert data["summary"].startswith("Planned")
    assert data["plan"]["commands"][0]["command"] == "pytest -q tests/test_core.py"


def test_run_targeted_tests_respects_dry_run(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text("def test_core(): pass\n", encoding="utf-8")

    out = dispatch_tool(
        _ctx(tmp_path, dry_run=True),
        "run_targeted_tests",
        {"changed_files": ["tests/test_core.py"], "max_commands": 1},
    )
    data = json.loads(out)

    assert data["results"][0]["ok"] is True
    assert data["results"][0]["output"].startswith("DRY-RUN:")
