"""Sandbox execution planning for MiniCodex command tools.

The restricted backend is intentionally a guarded local subprocess. Container
backends (Docker/Podman) run commands in a disposable workspace copy so command
side effects do not mutate the user's project tree. Secret-bearing files and
MiniCodex internals are excluded from the copied workspace.
"""

from __future__ import annotations

import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .safety import sensitive_path_reason, should_skip_path

SUPPORTED_SANDBOX_MODES = {"restricted", "docker", "podman"}
SUPPORTED_SANDBOX_NETWORKS = {"none", "default", "bridge", "host"}


@dataclass(frozen=True)
class SandboxOptions:
    """Runtime options controlling command sandbox execution."""

    mode: str = "restricted"
    image: str = "python:3.12-slim"
    network: str = "none"
    cpus: str = "1"
    memory: str = "1g"
    pids_limit: int = 256
    workspace_mode: str = "copy"  # copy | mount
    keep_workspace: bool = False
    max_file_bytes: int = 2_000_000


@dataclass(frozen=True)
class SandboxPlan:
    """Concrete command execution plan."""

    argv: list[str]
    cwd: Path
    note: str
    mode: str
    workspace: Path | None = None
    cleanup: Callable[[], None] | None = None
    blocked_reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None


def _safe_workspace_name() -> str:
    return time.strftime("run_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def sandbox_base_dir(root: Path) -> Path:
    """Return the MiniCodex sandbox workspace directory."""

    return root / ".minicodex" / "sandboxes"


def _should_ignore(root: Path, max_file_bytes: int, directory: str, names: list[str]) -> set[str]:
    """copytree ignore callback that skips caches, secrets, and oversized files."""

    ignored: set[str] = set()
    directory_path = Path(directory)
    for name in names:
        candidate = directory_path / name
        if candidate.is_symlink():
            ignored.add(name)
            continue
        try:
            rel_candidate = candidate.resolve().relative_to(root.resolve())
        except ValueError:
            ignored.add(name)
            continue
        if rel_candidate.parts and rel_candidate.parts[0] == ".minicodex":
            ignored.add(name)
            continue
        if should_skip_path(candidate, root):
            ignored.add(name)
            continue
        if candidate.is_file():
            try:
                if candidate.stat().st_size > max_file_bytes:
                    ignored.add(name)
            except OSError:
                ignored.add(name)
        elif candidate.is_dir() and sensitive_path_reason(candidate, root):
            ignored.add(name)
    return ignored


def create_workspace_copy(root: Path, *, max_file_bytes: int = 2_000_000) -> Path:
    """Create a disposable, secret-filtered copy of the project workspace."""

    root = root.resolve()
    base = sandbox_base_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    destination = base / _safe_workspace_name() / "workspace"
    destination.parent.mkdir(parents=True, exist_ok=False)
    shutil.copytree(
        root,
        destination,
        ignore=lambda directory, names: _should_ignore(root, max_file_bytes, directory, names),
        symlinks=False,
        dirs_exist_ok=False,
    )
    return destination


def cleanup_workspace(workspace: Path | None) -> None:
    """Remove a sandbox workspace directory if it is under .minicodex/sandboxes."""

    if workspace is None:
        return
    marker = workspace.parent.parent.name if workspace.parent.parent else ""
    if marker != "sandboxes":
        return
    shutil.rmtree(workspace.parent, ignore_errors=True)


def _container_runtime_command(
    runtime: str,
    workspace: Path,
    argv: list[str],
    *,
    image: str,
    network: str,
    cpus: str,
    memory: str,
    pids_limit: int,
    allow_network: bool,
) -> list[str]:
    """Build a Docker/Podman command with bounded resources and no inherited secrets."""

    effective_network = network if allow_network and network != "none" else "none"
    command = [runtime, "run", "--rm"]
    if effective_network == "none":
        command += ["--network=none"]
    elif runtime == "docker":
        command += ["--network", effective_network]
    else:
        command += ["--network", effective_network]
    if cpus:
        command += ["--cpus", str(cpus)]
    if memory:
        command += ["--memory", str(memory)]
    if pids_limit > 0:
        command += ["--pids-limit", str(pids_limit)]
    command += ["--security-opt", "no-new-privileges"]
    command += ["-v", f"{workspace.resolve()}:/workspace:rw", "-w", "/workspace"]
    command += [image, *argv]
    return command


def build_sandbox_plan(
    root: Path,
    argv: list[str],
    *,
    options: SandboxOptions,
    allow_network: bool = False,
) -> SandboxPlan:
    """Return an execution plan for argv under the requested sandbox backend."""

    mode = options.mode.strip().lower()
    if mode not in SUPPORTED_SANDBOX_MODES:
        return SandboxPlan(
            argv=[],
            cwd=root,
            note="",
            mode=mode,
            blocked_reason=(
                f"unsupported sandbox_mode={options.mode!r}. Use restricted, docker, or podman."
            ),
        )
    if options.network not in SUPPORTED_SANDBOX_NETWORKS:
        return SandboxPlan(
            argv=[],
            cwd=root,
            note="",
            mode=mode,
            blocked_reason=(
                f"unsupported sandbox_network={options.network!r}. "
                "Use none, default, bridge, or host."
            ),
        )

    if mode == "restricted":
        return SandboxPlan(
            argv=argv,
            cwd=root,
            note="Execution: restricted local subprocess, shell=False, workspace=project-root",
            mode=mode,
        )

    runtime = mode
    if shutil.which(runtime) is None:
        return SandboxPlan(
            argv=[],
            cwd=root,
            note="",
            mode=mode,
            blocked_reason=f"{runtime} sandbox requested but {runtime} is not installed or not on PATH.",
        )

    if options.workspace_mode == "mount":
        workspace = root.resolve()
        cleanup = None
        workspace_note = "project-root bind mount"
    elif options.workspace_mode == "copy":
        workspace = create_workspace_copy(root, max_file_bytes=options.max_file_bytes)
        cleanup = None if options.keep_workspace else lambda: cleanup_workspace(workspace)
        workspace_note = "isolated filtered copy"
    else:
        return SandboxPlan(
            argv=[],
            cwd=root,
            note="",
            mode=mode,
            blocked_reason=(
                f"unsupported sandbox_workspace_mode={options.workspace_mode!r}. Use copy or mount."
            ),
        )

    container_argv = _container_runtime_command(
        runtime,
        workspace,
        argv,
        image=options.image,
        network=options.network,
        cpus=options.cpus,
        memory=options.memory,
        pids_limit=options.pids_limit,
        allow_network=allow_network,
    )
    effective_network = options.network if allow_network and options.network != "none" else "none"
    note = (
        f"Execution: {runtime} container sandbox, shell=False, network={effective_network}, "
        f"cpus={options.cpus}, memory={options.memory}, pids_limit={options.pids_limit}, "
        f"workspace={workspace_note}"
    )
    return SandboxPlan(
        argv=container_argv,
        cwd=root,
        note=note,
        mode=mode,
        workspace=workspace,
        cleanup=cleanup,
    )


def render_sandbox_config(options: SandboxOptions) -> str:
    """Return a readable one-line sandbox configuration."""

    return (
        f"mode={options.mode}, image={options.image}, network={options.network}, "
        f"cpus={options.cpus}, memory={options.memory}, pids_limit={options.pids_limit}, "
        f"workspace_mode={options.workspace_mode}, keep_workspace={options.keep_workspace}, "
        f"max_file_bytes={options.max_file_bytes}"
    )
