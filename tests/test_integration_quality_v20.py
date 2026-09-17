from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from minicodex_agent import cli
from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.interactive import run_interactive_session
from minicodex_agent.model_client import ModelCallError, ModelClient
from minicodex_agent.project_inspector import detect_project


def _agent(
    root: Path, *, approval: str = "auto", dry_run: bool = False
) -> tuple[MiniCodexAgent, AgentState]:
    config = AgentConfig(
        root=root,
        model="stub",
        provider="stub",
        approval=approval,
        safety_profile="balanced",
        show_diff=False,
        log_enabled=False,
        auto_snapshot_before_edit=False,
        project_policy_enabled=False,
        dry_run=dry_run,
    )
    return MiniCodexAgent(config), AgentState(
        goal="integration", project_profile=detect_project(root)
    )


class SequenceModelClient:
    def __init__(self, decisions: list[dict]) -> None:
        self.decisions = decisions
        self.calls = 0

    def next_action_text(self, prompt: str, *, repair_error=None, invalid_output=None) -> str:
        self.calls += 1
        return json.dumps(self.decisions.pop(0))


def test_agent_run_loop_updates_plan_runs_tool_and_finishes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        max_steps=4,
        show_diff=False,
        log_enabled=False,
        auto_snapshot_before_edit=False,
        project_policy_enabled=False,
    )
    agent = MiniCodexAgent(config)
    agent.model_client = SequenceModelClient(
        [
            {
                "thought": "plan",
                "action": "update_plan",
                "args": {"steps": ["Read README", "finish"]},
            },
            {"thought": "read", "action": "read_file", "args": {"path": "README.md"}},
            {
                "thought": "done",
                "action": "finish",
                "args": {"summary": "completed", "changed_files": [], "checks_run": []},
            },
        ]
    )  # type: ignore[assignment]

    agent.run("read the readme")

    out = capsys.readouterr().out
    assert "MiniCodex Agent" in out
    assert "Plan güncellendi" in out
    assert "hello" in out
    assert "MiniCodex Agent finished" in out


def test_agent_run_finishes_cleanly_when_model_provider_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailingModel:
        def next_action_text(self, prompt: str, *, repair_error=None, invalid_output=None) -> str:
            raise ModelCallError("rate limited")

    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        max_steps=1,
        show_diff=False,
        log_enabled=False,
    )
    agent = MiniCodexAgent(config)
    agent.model_client = FailingModel()  # type: ignore[assignment]

    agent.run("handle failure")

    assert "Model çağrısı tamamlanamadı" in capsys.readouterr().out


def test_filesystem_tool_dispatch_realistic_workflow(tmp_path: Path) -> None:
    agent, state = _agent(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main():\n    return 'old'\n", encoding="utf-8")

    assert "src/app.py" in agent.execute_action(state, "list_files", {"path": "."})
    assert "return 'old'" in agent.execute_action(state, "read_file", {"path": "src/app.py"})
    assert "src/app.py" in agent.execute_action(state, "read_many_files", {"paths": ["src/app.py"]})
    assert "app.py" in agent.execute_action(state, "search_text", {"query": "old", "path": "."})
    assert (
        "python"
        in agent.execute_action(
            state, "index_project", {"path": ".", "max_files": 10, "save": False}
        ).lower()
    )
    assert "--- a/src/app.py" in agent.execute_action(
        state,
        "preview_replace_in_file",
        {"path": "src/app.py", "old": "old", "new": "new"},
    )
    assert "Dosya güncellendi" in agent.execute_action(
        state,
        "replace_in_file",
        {"path": "src/app.py", "old": "old", "new": "new"},
    )
    assert "return 'new'" in (tmp_path / "src" / "app.py").read_text(encoding="utf-8")
    assert "Dosya oluşturuldu" in agent.execute_action(
        state,
        "write_file",
        {"path": "notes/todo.txt", "content": "one\n"},
    )
    patch = """diff --git a/notes/todo.txt b/notes/todo.txt
--- a/notes/todo.txt
+++ b/notes/todo.txt
@@ -1 +1,2 @@
 one
+two
"""
    assert "Patch uygulandı" in agent.execute_action(state, "apply_patch", {"patch": patch})
    assert (tmp_path / "notes" / "todo.txt").read_text(encoding="utf-8") == "one\ntwo\n"


def test_shell_and_terminal_security_regressions(tmp_path: Path) -> None:
    agent, state = _agent(tmp_path)
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    run_result = agent.execute_action(
        state, "run_command", {"command": "python -m pytest -q", "timeout": 30}
    )
    assert "Exit code: 0" in run_result

    tests_result = agent.execute_action(
        state, "run_tests", {"command": "python -m pytest -q", "timeout": 30}
    )
    assert "Exit code: 0" in tests_result

    session_output = agent.execute_action(
        state, "run_terminal_session", {"commands": ["python -m pytest -q", "echo unsafe"]}
    )
    assert "Terminal session logged" in session_output

    strict_agent = MiniCodexAgent(
        AgentConfig(
            root=tmp_path,
            model="stub",
            provider="stub",
            approval="auto",
            safety_profile="strict",
            show_diff=False,
            log_enabled=False,
            project_policy_enabled=False,
        )
    )
    blocked = strict_agent.execute_action(
        state, "run_terminal_session", {"commands": ["echo unsafe"]}
    )
    assert blocked.startswith("COMMAND BLOCK")

    injected = agent.execute_action(
        state, "run_command", {"command": "python -m pytest -q && echo injected"}
    )
    assert injected.startswith("COMMAND BLOCK:")


def test_project_memory_git_github_and_security_tools_are_dispatchable(tmp_path: Path) -> None:
    agent, state = _agent(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "module.py").write_text("class Service:\n    pass\n", encoding="utf-8")

    # Project/config/plugin helpers.
    assert "MiniCodex setup" in agent.execute_action(
        state, "run_setup_wizard", {"overwrite": False}
    )
    assert (
        "project health"
        in agent.execute_action(state, "project_health_report", {"max_chars": 2000}).lower()
    )
    assert (
        "release checklist"
        in agent.execute_action(state, "release_checklist", {"version": "2.0.0"}).lower()
    )
    assert "provider" in agent.execute_action(state, "list_providers", {}).lower()
    assert "plugin" in agent.execute_action(state, "list_plugins", {}).lower()
    assert "enabled" in agent.execute_action(state, "enabled_tools", {}).lower()
    assert "write_file" in agent.execute_action(state, "tool_help", {"tool": "write_file"})
    assert (
        "valid"
        in agent.execute_action(state, "validate_config", {"path": "pyproject.toml"}).lower()
    )
    assert "ProjectProfile" in agent.execute_action(
        state, "inspect_project", {}
    ) or "project_types" in agent.execute_action(state, "inspect_project", {})
    assert "allowed" in agent.execute_action(
        state, "check_project_policy", {"kind": "write_path", "value": "README.md"}
    )

    # Python/project analysis helpers.
    assert "Service" in agent.execute_action(state, "inspect_python_ast", {"path": "module.py"})
    assert "Service" in agent.execute_action(state, "find_python_symbol", {"symbol": "Service"})
    assert "Service" in agent.execute_action(state, "search_code", {"query": "Service"})
    assert "AccountService" in agent.execute_action(
        state,
        "rename_python_symbol",
        {"old_name": "Service", "new_name": "AccountService", "preview_only": True},
    )
    assert (
        "code map"
        in agent.execute_action(state, "build_code_map", {"path": ".", "max_files": 20}).lower()
    )
    assert (
        "steps"
        in agent.execute_action(
            state, "decompose_task", {"goal": "improve tests", "max_steps": 3}
        ).lower()
    )
    assert (
        "planner"
        in agent.execute_action(
            state, "plan_multi_agent_work", {"goal": "improve tests", "max_agents": 3}
        ).lower()
    )

    # Memory/queue helpers.
    assert (
        "snapshot" in agent.execute_action(state, "create_snapshot", {"label": "quality"}).lower()
    )
    snapshots = agent.execute_action(state, "list_snapshots", {"limit": 5})
    assert "quality" in snapshots
    assert (
        "task memory"
        in agent.execute_action(state, "save_task_memory", {"summary": "done"}).lower()
    )
    assert "done" in agent.execute_action(state, "read_task_memory", {"limit": 5})
    queued = agent.execute_action(
        state, "enqueue_task", {"title": "Add CLI tests", "priority": "high"}
    )
    assert "queued" in queued.lower() or "task" in queued.lower()
    queue = agent.execute_action(state, "list_task_queue", {"limit": 5})
    assert "Add CLI tests" in queue
    next_task = agent.execute_action(state, "dequeue_next_task", {})
    assert "doing" in next_task.lower() or "Add CLI tests" in next_task
    assert (
        "blocked"
        in agent.execute_action(
            state, "update_task_status", {"task_id": "missing", "status": "blocked"}
        ).lower()
        or "not found"
        in agent.execute_action(
            state, "update_task_status", {"task_id": "missing", "status": "blocked"}
        ).lower()
    )
    assert (
        "commit"
        in agent.execute_action(state, "generate_commit_message", {"goal": "quality"}).lower()
    )

    # Git/GitHub/security helpers remain safe without a real git repo.
    assert (
        ".git" in agent.execute_action(state, "git_status", {})
        or "not" in agent.execute_action(state, "git_status", {}).lower()
    )
    assert (
        ".git" in agent.execute_action(state, "git_diff", {})
        or "diff" in agent.execute_action(state, "git_diff", {}).lower()
    )
    assert (
        "approval"
        in agent.execute_action(state, "record_change_approval", {"decision": "approved"}).lower()
    )
    assert "Git repo" in agent.execute_action(
        state, "prepare_github_pr", {"title": "Quality", "body": "Tests"}
    ) or "gh pr create" in agent.execute_action(
        state, "prepare_github_pr", {"title": "Quality", "body": "Tests"}
    )
    assert "gh issue create" in agent.execute_action(
        state, "prepare_github_issue", {"title": "Bug", "body": "Details", "labels": ["bug"]}
    )
    assert "No likely secrets" in agent.execute_action(
        state, "scan_secrets", {"minimum_severity": "high"}
    )
    assert "rollback" in agent.execute_action(state, "check_rollback_policy", {}).lower()


def test_cli_setup_create_demo_missing_goal_and_bad_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["minicodex", "--root", str(tmp_path), "--setup"])
    cli.main()
    assert (tmp_path / ".minicodex" / "config.json").exists()
    assert ".env.example" in capsys.readouterr().out

    monkeypatch.setattr(
        sys, "argv", ["minicodex", "--root", str(tmp_path), "--create-demo", "demo"]
    )
    cli.main()
    assert (tmp_path / "demo" / "pyproject.toml").exists()

    monkeypatch.setattr(
        sys, "argv", ["minicodex", "--root", str(tmp_path), "--provider", "stub", "--no-log"]
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1
    assert "goal is required" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["minicodex", "--root", str(tmp_path / "missing"), "goal"])
    with pytest.raises(SystemExit) as excinfo2:
        cli.main()
    assert excinfo2.value.code == 1
    assert "folder not found" in capsys.readouterr().out


def test_interactive_repl_dispatches_goal_and_exits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []

    class FakeAgent:
        def __init__(self, config: AgentConfig) -> None:
            self.config = config

        def run(self, goal: str) -> None:
            seen.append(goal)

    inputs = iter(["first task", ":exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("minicodex_agent.interactive.MiniCodexAgent", FakeAgent)

    run_interactive_session(AgentConfig(root=tmp_path, model="stub", provider="stub"))

    assert seen == ["first task"]
    assert "Interactive mode closed" in capsys.readouterr().out


def test_model_client_retries_then_succeeds() -> None:
    class FlakyResponses:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary")

            class Response:
                output_text = json.dumps(
                    {"thought": "ok", "action": "finish", "args": {"summary": "done"}}
                )
                usage = {"input_tokens": 1, "output_tokens": 2}

            return Response()

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FlakyResponses()

    client = ModelClient("test", provider="stub", max_retries=1, retry_backoff_seconds=0)
    fake = FakeClient()
    client.provider = "openai"
    client.client = fake

    result = client.next_action("{}")

    assert result["action"] == "finish"
    assert fake.responses.calls == 2
    assert client.usage.calls == 2


def test_package_build_metadata_is_valid_for_ci_build_step() -> None:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    project_root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["build-system"]["build-backend"] == "setuptools.build_meta"
    assert any(req.startswith("setuptools>=") for req in data["build-system"]["requires"])
    assert data["project"]["name"] == "minicodex-agent"
    package_init = (project_root / "src" / "minicodex_agent" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert f'__version__ = "{data["project"]["version"]}"' in package_init
    assert data["project"]["version"] in (project_root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert data["project"]["scripts"]["minicodex"] == "minicodex_agent.cli:main"
