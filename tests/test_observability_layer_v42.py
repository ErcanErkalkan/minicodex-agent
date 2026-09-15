from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS, validate_action
from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.plugin_registry import BUILTIN_PLUGINS, check_tool_access
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_settings import (
    init_project_config,
    read_project_config,
    update_project_config,
)
from minicodex_agent.telemetry import (
    TelemetryRecorder,
    compare_telemetry_runs,
    export_telemetry_bundle,
    list_telemetry_runs,
    read_telemetry_run,
    summarize_telemetry,
)
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class _Logger:
    def log_event(self, *_args, **_kwargs):
        pass


def _ctx(root: Path, *, dry_run: bool = False) -> ToolContext:
    return ToolContext(
        config=AgentConfig(
            root=root,
            model="stub",
            provider="stub",
            approval="auto",
            dry_run=dry_run,
            log_enabled=False,
        ),
        state=AgentState(goal="telemetry", project_profile=detect_project(root)),
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_observability_actions_are_registered() -> None:
    registry = get_tool_registry()
    actions = [
        "list_telemetry_runs",
        "read_telemetry_run",
        "telemetry_summary",
        "compare_telemetry_runs",
        "export_telemetry_bundle",
    ]
    for action in actions:
        assert action in ACTION_SPECS
        assert action in registry
    validate_action(
        {"thought": "x", "action": "read_telemetry_run", "args": {"run_id": "trace-abc"}}
    )
    plugin = next(p for p in BUILTIN_PLUGINS if p.name == "observability")
    assert all(action in plugin.tools for action in actions)


def test_telemetry_recorder_writes_redacted_trace(tmp_path: Path) -> None:
    recorder = TelemetryRecorder(tmp_path, run_id="trace-test", enabled=True, dry_run=False)
    span = recorder.start_span("tool.read_file", "tool", {"path": ".env"})
    recorder.finish_span(span, status="blocked", metadata={"reason": "secret"})
    recorder.record_tool_call(
        action="read_file",
        args={"path": ".env"},
        observation="POLICY BLOCK: OPENAI_API_KEY=sk-secret",
        outcome_status="policy_blocked",
        exit_code=20,
        duration_ms=3,
    )
    payload = recorder.finalize(status="policy_blocked", result={"summary": "done"})
    trace = tmp_path / ".minicodex" / "telemetry" / "runs" / "trace-test" / "trace.json"
    assert trace.exists()
    text = trace.read_text(encoding="utf-8")
    assert "sk-secret" not in text
    assert "policy_blocked" in text
    assert payload["counters"]["blocked_tools"] == 1


def test_telemetry_dry_run_does_not_write(tmp_path: Path) -> None:
    recorder = TelemetryRecorder(tmp_path, run_id="trace-dry", enabled=True, dry_run=True)
    recorder.finalize(status="success")
    assert not (tmp_path / ".minicodex" / "telemetry").exists()


def test_telemetry_listing_read_summary_compare_and_bundle(tmp_path: Path) -> None:
    first = TelemetryRecorder(tmp_path, run_id="trace-a", enabled=True, dry_run=False)
    first.record_model_call(
        step=1,
        prompt_chars=100,
        usage_before=None,
        usage_after={
            "calls": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "estimated_cost_usd": 0.001,
        },
    )
    first.finalize(status="success")
    second = TelemetryRecorder(tmp_path, run_id="trace-b", enabled=True, dry_run=False)
    second.record_model_call(
        step=1,
        prompt_chars=200,
        usage_before=None,
        usage_after={
            "calls": 2,
            "input_tokens": 20,
            "output_tokens": 9,
            "estimated_cost_usd": 0.002,
        },
    )
    second.finalize(status="success")

    runs = list_telemetry_runs(tmp_path)
    assert {run["run_id"] for run in runs} >= {"trace-a", "trace-b"}
    assert "trace-a" in read_telemetry_run(tmp_path, "trace-a")
    assert "model_calls" in summarize_telemetry(tmp_path)
    assert "delta_candidate_minus_baseline" in compare_telemetry_runs(
        tmp_path, "trace-a", "trace-b"
    )
    bundle = export_telemetry_bundle(tmp_path, run_id="trace-a")
    assert "Telemetry bundle written" in bundle


def test_agent_stub_run_creates_telemetry_trace(tmp_path: Path) -> None:
    cfg = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        max_steps=1,
        show_diff=False,
        log_enabled=False,
        telemetry_run_id="trace-agent",
    )
    result = MiniCodexAgent(cfg).run("smoke")
    assert int(result.exit_code) == 0
    trace = tmp_path / ".minicodex" / "telemetry" / "runs" / "trace-agent" / "trace.json"
    assert trace.exists()
    data = json.loads(trace.read_text(encoding="utf-8"))
    assert data["counters"]["tool_calls"] >= 1
    assert data["prompt_version"]


def test_telemetry_project_config_and_plugin_access(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    cfg = read_project_config(tmp_path)
    assert cfg["telemetry_enabled"] is True
    update_project_config(tmp_path, {"telemetry_enabled": False, "telemetry_max_event_chars": 777})
    applied = apply_project_config(
        AgentConfig(root=tmp_path, model="stub", provider="stub"), explicit_options=set()
    )
    assert applied.telemetry_enabled is False
    assert applied.telemetry_max_event_chars == 1000
    assert check_tool_access(
        tmp_path, "telemetry_summary", configured_plugins=("observability",)
    ).allowed


def test_telemetry_tools_dispatch(tmp_path: Path) -> None:
    rec = TelemetryRecorder(tmp_path, run_id="trace-tool", enabled=True, dry_run=False)
    rec.finalize(status="success")
    ctx = _ctx(tmp_path)
    assert "trace-tool" in dispatch_tool(ctx, "list_telemetry_runs", {})
    assert "Telemetry run" in dispatch_tool(ctx, "read_telemetry_run", {"run_id": "trace-tool"})
    assert "MiniCodex telemetry summary" in dispatch_tool(ctx, "telemetry_summary", {})
