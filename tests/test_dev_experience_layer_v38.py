from __future__ import annotations

import json
import subprocess
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.dev_experience import (
    create_review_bundle,
    export_ide_bridge,
    list_review_bundles,
    read_review_bundle,
    record_review_decision,
    render_run_summary,
    render_tui_panel,
)
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS, check_tool_access
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_settings import (
    init_project_config,
    read_project_config,
    update_project_config,
)
from minicodex_agent.run_logger import RunLogger
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class logger_stub:
    def write_plan(self, plan):
        pass


def _ctx(tmp_path: Path, *, dry_run: bool = False) -> ToolContext:
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        dry_run=dry_run,
        log_enabled=False,
    )
    state = AgentState(goal="review changes", project_profile=detect_project(tmp_path))
    return ToolContext(
        config=config,
        state=state,
        logger=logger_stub(),
        confirm_fn=lambda question, auto_approve, **kwargs: True,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def _init_git_repo(root: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    (root / "app.py").write_text("print('old')\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "app.py"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
    )
    (root / "app.py").write_text("print('new')\n", encoding="utf-8")


def test_dev_experience_actions_are_registered() -> None:
    for name in [
        "render_tui_panel",
        "create_review_bundle",
        "list_review_bundles",
        "read_review_bundle",
        "record_review_decision",
        "run_summary",
        "export_ide_bridge",
    ]:
        assert name in ACTION_SPECS
        assert name in get_tool_registry()
        args = (
            {"bundle_id": "rb-test", "decision": "approved"}
            if name == "record_review_decision"
            else {}
        )
        validate_action({"thought": "x", "action": name, "args": args})


def test_review_bundle_lifecycle(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    created = create_review_bundle(tmp_path, title="Review", goal="check diff", max_diff_chars=4000)
    data = json.loads(created.split("\n", 1)[1])
    bundle_id = data["bundle"]["bundle_id"]

    assert (tmp_path / data["path"]).exists()
    assert "app.py" in data["bundle"]["status_short"]

    listed = json.loads(list_review_bundles(tmp_path).split("\n", 1)[1])
    assert listed["bundles"][0]["bundle_id"] == bundle_id

    read = read_review_bundle(tmp_path, bundle_id=bundle_id)
    assert "REVIEW_BUNDLE_JSON" in read
    assert "print('new')" in read

    decision = json.loads(
        record_review_decision(
            tmp_path, bundle_id=bundle_id, decision="approved", note="looks good"
        ).split("\n", 1)[1]
    )
    assert decision["decision"]["decision"] == "approved"
    updated = json.loads((tmp_path / data["path"]).read_text(encoding="utf-8"))
    assert updated["review_state"] == "approved"


def test_dry_run_review_bundle_and_ide_bridge_do_not_write(tmp_path: Path) -> None:
    dry = create_review_bundle(tmp_path, goal="dry", dry_run=True)
    assert dry.startswith("DRY-RUN REVIEW_BUNDLE_JSON")
    assert not (tmp_path / ".minicodex" / "review_bundles").exists()

    bridge = export_ide_bridge(tmp_path, dry_run=True)
    assert bridge.startswith("DRY-RUN IDE_BRIDGE_JSON")
    assert not (tmp_path / ".minicodex" / "ide" / "bridge.json").exists()


def test_export_ide_bridge_writes_descriptor(tmp_path: Path) -> None:
    rendered = export_ide_bridge(tmp_path)
    data = json.loads(rendered.split("\n", 1)[1])
    path = tmp_path / data["path"]
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "developer_panel" in payload["commands"]


def test_run_summary_reads_latest_run(tmp_path: Path) -> None:
    logger = RunLogger(tmp_path / ".minicodex" / "runs", enabled=True)
    logger.write_metadata({"goal": "test goal", "provider": "stub", "model": "stub"})
    logger.log_event(
        {
            "type": "step",
            "step": 1,
            "action": "read_file",
            "outcome_status": "success",
            "exit_code": 0,
        }
    )
    logger.write_final({"summary": "done", "changed_files": ["app.py"], "checks_run": ["pytest"]})

    rendered = render_run_summary(tmp_path)
    data = json.loads(rendered.split("\n", 1)[1])
    assert data["goal"] == "test goal"
    assert data["step_count"] == 1
    assert data["changed_files"] == ["app.py"]


def test_render_tui_panel_is_dependency_free(tmp_path: Path) -> None:
    panel = render_tui_panel(tmp_path, goal="inspect")
    assert "MiniCodex Developer Panel" in panel
    assert "Goal: inspect" in panel


def test_tools_dispatch_and_plugin_access(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    ctx = _ctx(tmp_path)
    panel = dispatch_tool(ctx, "render_tui_panel", {"goal": "review"})
    bundle = dispatch_tool(ctx, "create_review_bundle", {"goal": "review", "max_diff_chars": 4000})
    summary = dispatch_tool(ctx, "list_review_bundles", {})

    assert "MiniCodex Developer Panel" in panel
    assert "REVIEW_BUNDLE_JSON" in bundle
    assert "REVIEW_BUNDLES_JSON" in summary
    plugins = {plugin.name: plugin for plugin in BUILTIN_PLUGINS}
    assert "developer-ux" in plugins
    assert check_tool_access(
        tmp_path, "render_tui_panel", configured_plugins=("developer-ux",)
    ).allowed


def test_project_config_applies_dev_experience_fields(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    cfg = read_project_config(tmp_path)
    assert cfg["developer_ux_enabled"] is True
    update_project_config(tmp_path, {"review_after_run": True, "review_bundle_max_diff_chars": 777})
    applied = apply_project_config(
        AgentConfig(root=tmp_path, model="stub", provider="stub"), explicit_options=set()
    )
    assert applied.review_after_run is True
    assert applied.review_bundle_max_diff_chars == 1000
