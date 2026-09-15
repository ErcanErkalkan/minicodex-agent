import json

from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig
from minicodex_agent.fs_tools import glob_file_search, list_dir, read_file_range
from minicodex_agent.index_tools import rg_search
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.tool_result import infer_tool_result


def _load_tool_result(rendered: str) -> dict:
    assert rendered.startswith("TOOL_RESULT_JSON:")
    return json.loads(rendered.split("TOOL_RESULT_JSON:\n", 1)[1])


def test_agent_wraps_observation_in_structured_tool_result(tmp_path):
    (tmp_path / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    config = AgentConfig(
        root=tmp_path, model="gpt-5.5", provider="stub", approval="auto", log_enabled=False
    )
    agent = MiniCodexAgent(config)
    state = AgentState(goal="read", project_profile=detect_project(tmp_path))

    result = agent.execute_action(state, "read_file", {"path": "hello.py"})
    # execute_action remains the low-level dispatch path for compatibility.
    assert "print('hello')" in result

    structured = infer_tool_result(action="read_file", text=result, args={"path": "hello.py"})
    assert structured.ok is True
    assert structured.files_read == ("hello.py",)
    assert "print('hello')" in structured.content


def test_new_navigation_tools_are_targeted_and_line_numbered(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.py").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    (src / "beta.txt").write_text("token here\n", encoding="utf-8")

    listing = list_dir(tmp_path, "src")
    assert "alpha.py" in listing
    assert "beta.txt" in listing

    globbed = glob_file_search(tmp_path, "*.py", "src")
    assert "src/alpha.py" in globbed
    assert "beta.txt" not in globbed

    ranged = read_file_range(tmp_path, "src/alpha.py", start_line=2, end_line=3)
    assert "src/alpha.py:2-3" in ranged
    assert "2 | two" in ranged
    assert "3 | three" in ranged
    assert "four" not in ranged


def test_rg_search_supports_regex_without_shell(tmp_path):
    (tmp_path / "main.py").write_text("alpha\nBeta42\ngamma\n", encoding="utf-8")

    out = rg_search(tmp_path, r"beta\d+")

    assert "main.py:2" in out
    assert "Beta42" in out


def test_structured_tool_result_detects_failed_command_and_truncation():
    text = "Execution: restricted subprocess, shell=False\nExit code: 2\n\nSTDERR:\nfailed" + (
        "x" * 200
    )

    result = infer_tool_result(
        action="run_command", text=text, args={"command": "pytest"}, max_content_chars=80
    )

    assert result.ok is False
    assert result.status == "failed"
    assert result.commands_run == ("pytest",)
    assert result.truncated is True
    assert result.errors
