"""Scripted terminal-session helpers.

This is intentionally non-interactive and bounded. It gives the agent a safer
way to run a short sequence of related commands while preserving one combined
session log under .minicodex/terminal_sessions.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .safety import assess_command_safety
from .shell_tools import run_command
from .utils import to_pretty_json, truncate


def _session_dir(root: Path, *, create: bool = True) -> Path:
    path = root / ".minicodex" / "terminal_sessions"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def run_terminal_session(
    root: Path,
    commands: list[str],
    *,
    profile: str = "strict",
    timeout_each: int = 60,
    max_commands: int = 8,
    dry_run: bool = False,
    max_chars: int = 16000,
    allow_network: bool = False,
    sandbox_mode: str = "restricted",
    sandbox_image: str = "python:3.12-slim",
    sandbox_network: str = "none",
    sandbox_cpus: str = "1",
    sandbox_memory: str = "1g",
    sandbox_pids_limit: int = 256,
    sandbox_workspace_mode: str = "copy",
    sandbox_keep_workspace: bool = False,
    sandbox_max_file_bytes: int = 2_000_000,
) -> str:
    """Run a bounded sequence of shell-free commands and write a JSON session log."""

    if not isinstance(commands, list) or not all(isinstance(command, str) for command in commands):
        return "commands must be a list of strings."
    selected = [command.strip() for command in commands if command.strip()][:max_commands]
    if not selected:
        return "No commands supplied."

    session_id = time.strftime("session_%Y%m%d_%H%M%S")
    results: list[dict[str, Any]] = []
    for command in selected:
        decision = assess_command_safety(command, profile=profile, allow_network=allow_network)
        if dry_run:
            results.append(
                {
                    "command": command,
                    "safety": decision.render(),
                    "dry_run": True,
                    "output": "not executed",
                }
            )
            continue
        if not decision.allowed:
            results.append(
                {
                    "command": command,
                    "safety": decision.render(),
                    "blocked": True,
                    "output": decision.render(),
                }
            )
            break
        if decision.requires_manual_approval:
            results.append(
                {
                    "command": command,
                    "safety": decision.render(),
                    "blocked": True,
                    "output": "manual approval required; terminal sessions do not auto-run high-risk commands",
                }
            )
            break
        output = run_command(
            root,
            command,
            timeout=timeout_each,
            max_chars=max_chars,
            profile=profile,
            allow_network=allow_network,
            sandbox_mode=sandbox_mode,
            sandbox_image=sandbox_image,
            sandbox_network=sandbox_network,
            sandbox_cpus=sandbox_cpus,
            sandbox_memory=sandbox_memory,
            sandbox_pids_limit=sandbox_pids_limit,
            sandbox_workspace_mode=sandbox_workspace_mode,
            sandbox_keep_workspace=sandbox_keep_workspace,
            sandbox_max_file_bytes=sandbox_max_file_bytes,
        )
        results.append({"command": command, "safety": decision.render(), "output": output})
        first_lines = "\n".join(output.splitlines()[:3])
        if "Exit code: 0" not in first_lines:
            break

    payload = {
        "session_id": session_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": results,
    }
    if dry_run:
        return truncate(
            "DRY-RUN: terminal session not logged.\n\n" + to_pretty_json(payload), max_chars
        )
    log_path = _session_dir(root) / f"{session_id}.json"
    log_path.write_text(to_pretty_json(payload) + "\n", encoding="utf-8")
    return truncate(
        f"Terminal session logged to {log_path.relative_to(root)}\n\n" + to_pretty_json(payload),
        max_chars,
    )


def list_terminal_sessions(root: Path, limit: int = 10) -> str:
    """List recent scripted terminal session logs."""

    directory = _session_dir(root, create=False)
    if not directory.exists():
        return "No terminal sessions found."
    files = sorted(directory.glob("session_*.json"), reverse=True)[:limit]
    if not files:
        return "No terminal sessions found."
    rows = []
    for path in files:
        rows.append(str(path.relative_to(root)))
    return "Recent terminal sessions:\n" + "\n".join(rows)
