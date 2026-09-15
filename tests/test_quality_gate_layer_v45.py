from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS, check_tool_access
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.quality_gate import (
    build_test_matrix_plan,
    final_readiness_report,
    release_package_manifest,
)
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class LoggerStub:
    def write_plan(self, plan):
        pass


def _ctx(root: Path) -> ToolContext:
    config = AgentConfig(
        root=root, model="stub", provider="stub", approval="auto", log_enabled=False
    )
    return ToolContext(
        config=config,
        state=AgentState(goal="final readiness", project_profile=detect_project(root)),
        logger=LoggerStub(),
        confirm_fn=lambda question, auto_approve, **kwargs: True,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def _minimal_project(root: Path) -> None:
    (root / "src" / "minicodex_agent").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "minicodex_agent" / "__init__.py").write_text(
        '__version__ = "4.4.0"\n', encoding="utf-8"
    )
    (root / "pyproject.toml").write_text('[project]\nversion = "4.4.0"\n', encoding="utf-8")
    (root / "CHANGELOG.md").write_text("## 4.4.0\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "tests" / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "run_test_matrix.py").write_text(
        "import json\n"
        'print(json.dumps({"overall_status":"pass","test_file_count":1,"executed_test_file_count":1,"failure_count":0,"results":[]}))\n',
        encoding="utf-8",
    )


def _payload(rendered: str) -> dict:
    return json.loads(rendered.split("\n", 1)[1])


def test_quality_gate_actions_are_registered() -> None:
    for name in ["final_readiness_report", "test_matrix_plan", "release_package_manifest"]:
        assert name in ACTION_SPECS
        assert name in get_tool_registry()
        validate_action({"thought": "x", "action": name, "args": {}})


def test_final_readiness_report_checks_version_and_syntax(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    report = _payload(final_readiness_report(tmp_path, include_cli_smoke=False, max_chars=20000))
    assert report["version"] == "4.4.0"
    check_names = {check["name"] for check in report["checks"]}
    assert "version_alignment" in check_names
    assert "python_syntax" in check_names
    assert "test_matrix_plan" in report


def test_test_matrix_plan_lists_test_files(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    plan = build_test_matrix_plan(tmp_path, per_file_timeout=33)
    matrix = [item for item in plan["commands"] if item["name"] == "pytest-file-matrix"][0]
    assert matrix["timeout_seconds_each"] == 33
    assert "tests/test_demo.py" in matrix["test_files"]


def test_release_package_manifest_reports_generated_artifacts(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    (tmp_path / "src" / "minicodex_agent" / "__pycache__").mkdir()
    (tmp_path / "src" / "minicodex_agent" / "__pycache__" / "x.pyc").write_bytes(b"x")
    manifest = _payload(release_package_manifest(tmp_path))
    assert manifest["version"] == "4.4.0"
    assert manifest["generated_artifact_count"] == 1


def test_quality_tools_dispatch_and_plugin_access(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    ctx = _ctx(tmp_path)
    rendered = dispatch_tool(ctx, "test_matrix_plan", {"per_file_timeout": 12})
    assert "TEST_MATRIX_PLAN_JSON" in rendered
    plugins = {plugin.name: plugin for plugin in BUILTIN_PLUGINS}
    assert "quality-gates" in plugins
    assert check_tool_access(
        tmp_path, "final_readiness_report", configured_plugins=("quality-gates",)
    ).allowed


def test_final_readiness_includes_security_verification_and_test_result(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    report = _payload(
        final_readiness_report(
            tmp_path,
            include_cli_smoke=False,
            test_matrix_max_files=1,
            test_matrix_timeout=20,
            max_chars=80000,
        )
    )
    check_names = {check["name"] for check in report["checks"]}
    assert "security_audit_gate" in check_names
    assert "verification_tools_gate" in check_names
    assert "test_matrix_result_gate" in check_names
    test_gate = next(
        check for check in report["checks"] if check["name"] == "test_matrix_result_gate"
    )
    assert test_gate["details"]["matrix_summary"]["executed_test_file_count"] == 1


def test_final_readiness_small_max_chars_still_returns_valid_json(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    # Create enough files to force the structural compacting path.
    cache = tmp_path / "src" / "minicodex_agent" / "__pycache__"
    cache.mkdir()
    for index in range(30):
        (cache / f"x{index}.pyc").write_bytes(b"x")
    rendered = final_readiness_report(
        tmp_path,
        include_cli_smoke=False,
        include_test_matrix=False,
        include_security_audit=False,
        max_chars=1500,
    )
    payload = _payload(rendered)
    assert payload["truncated"] is True
    assert payload["overall_status"] in {"pass", "warn", "fail"}
    assert "checks" in payload


def test_release_manifest_small_max_chars_still_returns_valid_json(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    for index in range(100):
        (tmp_path / f"doc_{index}.md").write_text("x", encoding="utf-8")
    rendered = release_package_manifest(tmp_path, max_chars=1400)
    payload = _payload(rendered)
    assert payload["truncated"] is True
    assert payload["version"] == "4.4.0"


def test_test_matrix_tool_small_max_chars_still_returns_valid_json(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    ctx = _ctx(tmp_path)
    rendered = dispatch_tool(ctx, "test_matrix_plan", {"max_chars": 1200})
    assert rendered.startswith("TEST_MATRIX_PLAN_JSON\n")
    payload = _payload(rendered)
    assert payload["schema_version"] == 1


def test_final_readiness_cleans_python_bytecode_artifacts(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    cache = tmp_path / "src" / "minicodex_agent" / "__pycache__"
    cache.mkdir()
    (cache / "demo.cpython-312.pyc").write_bytes(b"bytecode")
    pytest_cache = tmp_path / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "README.md").write_text("cache", encoding="utf-8")
    assert cache.exists()
    assert pytest_cache.exists()

    rendered = final_readiness_report(
        tmp_path,
        include_cli_smoke=False,
        include_test_matrix=False,
        include_security_audit=False,
        max_chars=20000,
    )
    payload = _payload(rendered)

    assert not cache.exists()
    assert not pytest_cache.exists()
    assert payload["bytecode_cleanup"]["before_checks"]["removed_dirs"] >= 2


def test_test_matrix_syntax_check_does_not_create_pycache(tmp_path: Path) -> None:
    _minimal_project(tmp_path)
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "run_test_matrix.py"
    spec = importlib.util.spec_from_file_location("run_test_matrix", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.syntax_check(tmp_path)

    assert result["exit_code"] == 0
    assert not list(tmp_path.rglob("__pycache__"))
