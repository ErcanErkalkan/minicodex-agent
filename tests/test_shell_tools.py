from __future__ import annotations

import sys

from minicodex_agent.shell_tools import run_command


def test_run_command_uses_restricted_shell_false(tmp_path):
    result = run_command(
        tmp_path,
        f"{sys.executable} -m pytest --version",
        timeout=30,
        max_chars=4000,
        profile="balanced",
    )

    assert "shell=False" in result
    assert "Exit code: 0" in result


def test_run_command_blocks_shell_operator_even_balanced(tmp_path):
    result = run_command(
        tmp_path,
        "echo safe && echo unsafe",
        timeout=30,
        max_chars=4000,
        profile="balanced",
    )

    assert result.startswith("COMMAND BLOCK:")
    assert "shell control" in result


def test_run_command_blocks_network_install_without_permission(tmp_path):
    result = run_command(
        tmp_path,
        "pip install requests",
        timeout=30,
        max_chars=4000,
        profile="balanced",
    )

    assert result.startswith("COMMAND BLOCK:")
    assert "network/install" in result
