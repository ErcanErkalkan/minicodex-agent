"""Command execution tools exposed to the agent.

Commands are never executed through a shell. They are parsed into argv and run
with subprocess.run(..., shell=False). This prevents shell-injection primitives
such as pipes, redirection, command substitution, and chained commands.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .safety import assess_command_safety
from .sandbox import SandboxOptions, build_sandbox_plan, render_sandbox_config
from .utils import subprocess_text, truncate


def run_command(
    root: Path,
    command: str,
    timeout: int,
    max_chars: int,
    profile: str = "strict",
    *,
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
    """Run a guarded command inside the workspace.

    sandbox_mode="restricted" runs the parsed argv directly with shell=False.
    sandbox_mode="docker" or "podman" runs it in a bounded container. By default
    container modes execute against a disposable filtered workspace copy, not a
    direct bind mount of the user project.
    """

    decision = assess_command_safety(command, profile=profile, allow_network=allow_network)
    if not decision.allowed:
        return "COMMAND BLOCK: " + decision.render()

    timeout = min(max(timeout, 1), 300)
    options = SandboxOptions(
        mode=sandbox_mode,
        image=sandbox_image,
        network=sandbox_network,
        cpus=str(sandbox_cpus),
        memory=str(sandbox_memory),
        pids_limit=int(sandbox_pids_limit),
        workspace_mode=sandbox_workspace_mode,
        keep_workspace=bool(sandbox_keep_workspace),
        max_file_bytes=int(sandbox_max_file_bytes),
    )
    plan = build_sandbox_plan(root, decision.argv, options=options, allow_network=allow_network)
    if plan.blocked:
        return "SANDBOX BLOCK: " + str(plan.blocked_reason)
    argv = plan.argv
    execution_note = plan.note

    child_env = os.environ.copy()
    child_env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if argv and (
        Path(argv[0]).name.startswith("pytest")
        or (
            len(argv) >= 3
            and Path(argv[0]).name.startswith("python")
            and argv[1:3] == ["-m", "pytest"]
        )
    ):
        child_env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    try:
        completed = subprocess.run(
            argv,
            cwd=str(plan.cwd),
            stdin=subprocess.DEVNULL,
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = subprocess_text(exc.stdout)
        stderr = subprocess_text(exc.stderr)
        return truncate(
            f"{execution_note}\n"
            f"Safety: {decision.render()}\n"
            f"Sandbox: {render_sandbox_config(options)}\n"
            f"Command timed out after {timeout}s.\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}",
            max_chars,
        )
    except OSError as exc:
        return f"{execution_note}\nSafety: {decision.render()}\nSandbox: {render_sandbox_config(options)}\nCommand failed to start: {exc}"
    finally:
        if plan.cleanup is not None:
            plan.cleanup()

    output = (
        f"{execution_note}\n"
        f"Safety: {decision.render()}\n"
        f"Sandbox: {render_sandbox_config(options)}\n"
        f"Exit code: {completed.returncode}\n\n"
        f"STDOUT:\n{completed.stdout}\n\n"
        f"STDERR:\n{completed.stderr}"
    )
    return truncate(output, max_chars)


def git_diff(root: Path, max_chars: int, profile: str = "strict") -> str:
    """Return git diff when the workspace is a git repository."""

    if not (root / ".git").exists():
        return "Bu klasörde .git bulunamadı; diff gösterilemiyor."

    return run_command(root, "git diff -- .", timeout=60, max_chars=max_chars, profile=profile)
