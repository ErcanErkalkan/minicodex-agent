from minicodex_agent.terminal_session import list_terminal_sessions, run_terminal_session


def test_terminal_session_dry_run(tmp_path):
    result = run_terminal_session(tmp_path, ["python --version"], dry_run=True)
    assert "DRY-RUN: terminal session not logged" in result
    assert "not executed" in result
    assert "No terminal sessions found" in list_terminal_sessions(tmp_path)
    assert not (tmp_path / ".minicodex" / "terminal_sessions").exists()


def test_terminal_session_blocks_dangerous_command(tmp_path):
    result = run_terminal_session(tmp_path, ["rm -rf /"], profile="balanced")
    assert "blocked" in result or "tehlikeli" in result
