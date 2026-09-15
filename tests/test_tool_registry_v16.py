from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tool_registry import (
    ToolSpec,
    dispatch_tool,
    get_tool_registry,
    render_runtime_tool_reference,
)
from minicodex_agent.tools.context import ToolContext


def test_runtime_registry_covers_every_action_schema():
    registry = get_tool_registry()
    assert set(registry) == set(ACTION_SPECS)
    assert all(isinstance(spec, ToolSpec) for spec in registry.values())
    assert all(registry[name].schema is ACTION_SPECS[name] for name in registry)


def test_runtime_tool_reference_is_generated_from_tool_specs():
    reference = render_runtime_tool_reference()
    assert "write_file" in reference
    assert "required=[path, content]" in reference
    assert "approval=True" in reference


def test_runtime_tool_reference_can_filter_actions():
    reference = render_runtime_tool_reference(["finish", "read_file"])

    assert "- finish " in reference
    assert "- read_file " in reference
    assert "- run_command " not in reference


def test_agent_execute_action_uses_registry_dispatch(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    config = AgentConfig(
        root=tmp_path, model="gpt-5.5", provider="stub", approval="auto", log_enabled=False
    )
    agent = MiniCodexAgent(config)
    state = AgentState(goal="read", project_profile=detect_project(tmp_path))

    result = agent.execute_action(state, "read_file", {"path": "hello.txt"})

    assert "hello" in result


def test_dispatch_keeps_plugin_enforcement(tmp_path):
    (tmp_path / ".minicodex").mkdir()
    (tmp_path / ".minicodex" / "config.json").write_text(
        '{"enabled_plugins": ["filesystem"]}', encoding="utf-8"
    )
    config = AgentConfig(
        root=tmp_path, model="gpt-5.5", provider="stub", approval="auto", log_enabled=False
    )
    state = AgentState(goal="test", project_profile=detect_project(tmp_path))
    ctx = ToolContext(
        config=config,
        state=state,
        logger=agent_logger_stub(),
        confirm_fn=lambda question, auto_approve, **kwargs: True,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )

    assert dispatch_tool(ctx, "run_tests", {}).startswith("TOOL BLOCK")


class agent_logger_stub:
    def write_plan(self, plan):
        pass
