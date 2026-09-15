from __future__ import annotations

from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_policy import update_project_policy
from minicodex_agent.project_settings import update_project_config
from minicodex_agent.run_logger import RunLogger
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.tools.github import handle_prepare_github_pr


def _state(root):
    return AgentState(goal="test", project_profile=detect_project(root))


def _ctx(root, config: AgentConfig | None = None) -> ToolContext:
    cfg = config or AgentConfig(
        root=root, model="stub", provider="stub", approval="auto", log_enabled=False
    )
    return ToolContext(
        config=cfg,
        state=_state(root),
        logger=RunLogger(root, enabled=False),
        confirm_fn=lambda question, auto_approve, **kwargs: True,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_apply_project_config_applies_all_runtime_fields(tmp_path):
    update_project_config(
        tmp_path,
        {
            "scan_secrets_before_pr": False,
            "max_agent_batch_size": 2,
            "enabled_plugins": ["filesystem"],
            "policy_file": ".minicodex/custom-policy.json",
            "auto_snapshot_before_edit": False,
        },
    )

    cfg = apply_project_config(
        AgentConfig(root=tmp_path, model="stub", provider="stub"), explicit_options=set()
    )

    assert cfg.scan_secrets_before_pr is False
    assert cfg.max_agent_batch_size == 2
    assert cfg.enabled_plugins == ("filesystem",)
    assert cfg.policy_file == ".minicodex/custom-policy.json"
    assert cfg.auto_snapshot_before_edit is False


def test_runtime_enabled_plugins_from_applied_config_enforces_tools(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    update_project_config(tmp_path, {"enabled_plugins": ["filesystem"]})
    cfg = apply_project_config(
        AgentConfig(
            root=tmp_path, model="stub", provider="stub", approval="auto", log_enabled=False
        ),
        explicit_options={"provider"},
    )
    agent = MiniCodexAgent(cfg)
    state = _state(tmp_path)

    assert "hello" in agent.execute_action(state, "read_file", {"path": "hello.txt"})
    assert agent.execute_action(state, "run_tests", {}).startswith("TOOL BLOCK:")


def test_runtime_policy_file_is_used_for_write_checks(tmp_path):
    update_project_config(tmp_path, {"policy_file": ".minicodex/strict-policy.json"})
    update_project_policy(
        tmp_path,
        {"blocked_write_globs": ["blocked.txt"], "allowed_write_globs": ["**/*"]},
        policy_file=".minicodex/strict-policy.json",
    )
    cfg = apply_project_config(
        AgentConfig(
            root=tmp_path, model="stub", provider="stub", approval="auto", log_enabled=False
        ),
        explicit_options={"provider"},
    )
    agent = MiniCodexAgent(cfg)
    result = agent.execute_action(
        _state(tmp_path), "write_file", {"path": "blocked.txt", "content": "x"}
    )

    assert result.startswith("POLICY BLOCK:")
    assert "blocked_write_globs" in result


def test_scan_secrets_before_pr_blocks_high_severity_findings(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "leak.py").write_text('OPENAI_API_KEY="sk-' + "A" * 32 + '"\n', encoding="utf-8")
    ctx = _ctx(tmp_path)

    result = handle_prepare_github_pr(ctx, {"title": "t", "body": "b"})

    assert result.startswith("SECRET SCAN BEFORE PR: BLOCKED")


def test_scan_secrets_before_pr_can_be_disabled_by_runtime_config(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "leak.py").write_text('OPENAI_API_KEY="sk-' + "A" * 32 + '"\n', encoding="utf-8")
    cfg = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        log_enabled=False,
        scan_secrets_before_pr=False,
    )
    ctx = _ctx(tmp_path, cfg)

    result = handle_prepare_github_pr(ctx, {"title": "t", "body": "b"})

    assert "SECRET SCAN BEFORE PR: BLOCKED" not in result
    assert "GitHub PR hazırlığı" in result
