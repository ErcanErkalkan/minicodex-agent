from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from minicodex_agent.action_schema import (
    ActionValidationError,
    ArgSpec,
    build_model_action_json_schema,
    render_action_reference,
    validate_action,
)
from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.config_tools import validate_config_file
from minicodex_agent.fs_tools import list_files, preview_write_file, read_file, write_file
from minicodex_agent.model_client import response_to_text
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.shell_tools import run_command
from minicodex_agent.utils import extract_json, to_pretty_json, truncate


def _agent(root: Path) -> tuple[MiniCodexAgent, AgentState]:
    config = AgentConfig(
        root=root,
        model="stub",
        provider="stub",
        approval="auto",
        safety_profile="balanced",
        show_diff=False,
        log_enabled=False,
        auto_snapshot_before_edit=False,
        project_policy_enabled=False,
    )
    return MiniCodexAgent(config), AgentState(goal="coverage", project_profile=detect_project(root))


def test_action_schema_arg_spec_error_branches_and_reference() -> None:
    ArgSpec("any").validate("x", "a", object())
    with pytest.raises(ActionValidationError):
        ArgSpec("string").validate("x", "a", 1)
    with pytest.raises(ActionValidationError):
        ArgSpec("integer").validate("x", "a", True)
    with pytest.raises(ActionValidationError):
        ArgSpec("number").validate("x", "a", False)
    with pytest.raises(ActionValidationError):
        ArgSpec("boolean").validate("x", "a", "yes")
    with pytest.raises(ActionValidationError):
        ArgSpec("object").validate("x", "a", [])
    with pytest.raises(ActionValidationError):
        ArgSpec("array").validate("x", "a", {})
    with pytest.raises(ActionValidationError):
        ArgSpec("array_string").validate("x", "a", ["ok", 1])
    with pytest.raises(ActionValidationError):
        ArgSpec("array_object").validate("x", "a", [{}, "bad"])
    with pytest.raises(ActionValidationError):
        ArgSpec("string", enum=("a", "b")).validate("x", "choice", "c")
    with pytest.raises(ActionValidationError):
        ArgSpec("mystery").validate("x", "a", "value")

    assert ArgSpec("array_object").to_json_schema()["items"]["type"] == "object"
    assert ArgSpec("array").to_json_schema()["type"] == "array"
    assert (
        ArgSpec("string", enum=("a",), description="desc").to_json_schema()["description"] == "desc"
    )
    assert build_model_action_json_schema()["oneOf"]
    assert "write_file" in render_action_reference()


def test_action_schema_validation_failure_branches() -> None:
    bad_cases = [
        [],
        {"action": "finish", "args": {}, "extra": True},
        {"thought": "x", "action": "", "args": {}},
        {"thought": "x", "action": "does_not_exist", "args": {}},
        {"thought": 123, "action": "finish", "args": {}},
        {"thought": "x", "action": "finish", "args": []},
        {"thought": "x", "action": "read_file", "args": {}},
        {"thought": "x", "action": "read_file", "args": {"path": "a", "bad": 1}},
    ]
    for case in bad_cases:
        with pytest.raises(ActionValidationError):
            validate_action(case)  # type: ignore[arg-type]
    assert validate_action({"thought": "x", "action": "finish", "args": None})["args"] == {}


def test_config_validation_formats_and_error_paths(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "ok.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "GOOD=1\nBAD LINE\nGOOD=2\nBAD KEY=3\n=empty\n", encoding="utf-8"
    )
    (tmp_path / "bad.yaml").write_text("root:\n   child\n\tbad: true\n", encoding="utf-8")
    (tmp_path / "unknown.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "dir").mkdir()
    (tmp_path / "bin.png").write_bytes(b"\x00\x01")

    assert "JSON parse" in validate_config_file(tmp_path, "bad.json")
    assert "PASS" in validate_config_file(tmp_path, "ok.json")
    assert "tekrar eden" in validate_config_file(tmp_path, ".env.example")
    assert "YAML" in validate_config_file(tmp_path, "bad.yaml")
    assert "Destek sınırlı" in validate_config_file(tmp_path, "unknown.txt")
    assert "Dosya bulunamadı" in validate_config_file(tmp_path, "missing.json")
    assert "Dosya değil" in validate_config_file(tmp_path, "dir")
    assert "Binary" in validate_config_file(tmp_path, "bin.png")


def test_fs_edge_cases_and_utils(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "hidden.pyc").write_bytes(b"compiled")
    assert "visible.txt" in list_files(tmp_path, ".", max_files=10)
    assert "kesildi" in list_files(tmp_path, ".", max_files=1)
    assert "Path bulunamadı" in list_files(tmp_path, "missing")
    assert "visible.txt" == list_files(tmp_path, "visible.txt")
    assert "Binary" in read_file(tmp_path, "nested/hidden.pyc", 100)
    assert "Dosya bulunamadı" in read_file(tmp_path, "missing.txt", 100)
    assert "Dosya değil" in read_file(tmp_path, "nested", 100)
    assert "--- a/new.txt" in preview_write_file(tmp_path, "new.txt", "content")
    assert "DRY-RUN" in write_file(tmp_path, "new.txt", "content", dry_run=True)

    assert truncate("abc", 10) == "abc"
    assert "TRUNCATED" in truncate("abcdef", 3)
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('prefix {"b": 2} suffix') == {"b": 2}
    with pytest.raises(ValueError):
        extract_json("not json")
    assert to_pretty_json({"b": 2, "a": 1}).startswith("{")


def test_project_tool_negative_and_write_paths(tmp_path: Path) -> None:
    agent, state = _agent(tmp_path)

    assert "Release notes" in agent.execute_action(
        state, "write_release_notes", {"version": "2.0.0"}
    )
    assert (tmp_path / "RELEASE_NOTES.md").exists()
    assert (
        "config" in agent.execute_action(state, "init_project_config", {"overwrite": True}).lower()
    )
    assert "provider" in agent.execute_action(state, "read_project_config", {}).lower()
    assert (
        "updated"
        in agent.execute_action(
            state, "update_project_config", {"updates": {"max_steps": 7}}
        ).lower()
    )
    assert (
        "policy" in agent.execute_action(state, "init_project_policy", {"overwrite": True}).lower()
    )
    assert "blocked_write_globs" in agent.execute_action(state, "read_project_policy", {})
    assert (
        "updated"
        in agent.execute_action(
            state, "update_project_policy", {"updates": {"blocked_write_globs": ["secret.txt"]}}
        ).lower()
    )
    assert "plugin" in agent.execute_action(state, "validate_plugins", {}).lower()
    assert (
        "not found"
        in agent.execute_action(state, "inspect_plugin", {"name": "missing-plugin"}).lower()
    )
    assert "unknown" in agent.execute_action(state, "tool_help", {"tool": "missing_tool"}).lower()
    assert (
        "task batch"
        in agent.execute_action(
            state, "run_task_batch", {"tasks": ["a", "b"], "dry_run": True}
        ).lower()
    )
    assert "agent batch" in agent.execute_action(state, "list_agent_batches", {"limit": 5}).lower()


def test_shell_model_and_response_edge_cases(tmp_path: Path) -> None:
    assert "SANDBOX BLOCK" in run_command(
        tmp_path, "python -m pytest -q", 1, 1000, "balanced", sandbox_mode="not-a-mode"
    )
    assert "Command failed to start" in run_command(
        tmp_path, "definitely_missing_executable_xyz", 1, 1000, "balanced"
    )

    timeout_result = run_command(
        tmp_path,
        "python -c 'import time; time.sleep(2)'",
        timeout=1,
        max_chars=1000,
        profile="balanced",
    )
    assert "timed out" in timeout_result

    response = SimpleNamespace(output=[SimpleNamespace(content=[SimpleNamespace(text="hello")])])
    assert response_to_text(response) == "hello"
    assert "namespace" in response_to_text(SimpleNamespace(output=[]))
