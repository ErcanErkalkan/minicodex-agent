"""Agent-level isolated workspace support.

This layer is deliberately separate from command sandboxing. Command sandboxing
controls how subprocesses run; agent workspace isolation controls where *all*
agent file reads/writes/patches happen during a run. In isolated mode the agent
operates on a filtered copy and exports a diff/manifest that can be reviewed or
applied to the original tree after the run.
"""

from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .safety import sensitive_path_reason, should_skip_path
from .sandbox import cleanup_workspace, create_workspace_copy
from .utils import to_pretty_json, truncate

SUPPORTED_AGENT_WORKSPACE_MODES = {"direct", "isolated"}
SUPPORTED_AGENT_WORKSPACE_APPLY = {"never", "ask", "auto"}
_TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".rst",
    ".ini",
    ".cfg",
    ".css",
    ".html",
    ".xml",
    ".sh",
    ".bat",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".sql",
    ".env.example",
}
_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".minicodex",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
}


@dataclass(frozen=True)
class WorkspaceChange:
    """One changed file between original root and isolated workspace."""

    path: str
    change_type: (
        str  # created | modified | deleted | binary_modified | binary_created | binary_deleted
    )
    binary: bool = False


@dataclass
class AgentWorkspaceSession:
    """State for one agent-level workspace isolation session."""

    mode: str
    original_root: Path
    active_root: Path
    workspace_id: str = ""
    artifact_dir: Path | None = None
    keep_workspace: bool = False
    changes: list[WorkspaceChange] = field(default_factory=list)
    diff_text: str = ""
    manifest_path: Path | None = None
    diff_path: Path | None = None
    applied: bool = False
    apply_warnings: list[str] = field(default_factory=list)

    @property
    def isolated(self) -> bool:
        return self.mode == "isolated"


def _is_binary_file(path: Path, *, sample_size: int = 8192) -> bool:
    """Return True when a file appears to be binary."""

    try:
        sample = path.read_bytes()[:sample_size]
    except OSError:
        return True
    return b"\x00" in sample


def _safe_rel_paths(root: Path) -> set[str]:
    """Return comparable non-sensitive file paths under root."""

    root = root.resolve()
    result: set[str] = set()
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        try:
            rel = path.resolve().relative_to(root)
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            continue
        if should_skip_path(path, root) or sensitive_path_reason(path, root):
            continue
        result.add(rel.as_posix())
    return result


def _read_text_for_diff(path: Path) -> list[str] | None:
    """Read a text file as lines for unified diff; return None for binary/unreadable."""

    if path.suffix not in _TEXT_SUFFIXES and _is_binary_file(path):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return None


def _change_type(original: Path, active: Path) -> tuple[str, bool]:
    """Classify a changed path."""

    if not original.exists() and active.exists():
        binary = _is_binary_file(active)
        return ("binary_created" if binary else "created", binary)
    if original.exists() and not active.exists():
        binary = _is_binary_file(original)
        return ("binary_deleted" if binary else "deleted", binary)
    binary = _is_binary_file(original) or _is_binary_file(active)
    return ("binary_modified" if binary else "modified", binary)


def compute_workspace_changes(
    original_root: Path, active_root: Path, *, max_diff_chars: int = 24000
) -> tuple[list[WorkspaceChange], str]:
    """Compute changed files and a reviewable unified diff."""

    original_root = original_root.resolve()
    active_root = active_root.resolve()
    original_paths = _safe_rel_paths(original_root)
    active_paths = _safe_rel_paths(active_root)
    all_paths = sorted(original_paths | active_paths)
    changes: list[WorkspaceChange] = []
    diff_parts: list[str] = []
    diff_budget = max(0, max_diff_chars)

    for rel in all_paths:
        original = original_root / rel
        active = active_root / rel
        if original.exists() and active.exists():
            try:
                if original.read_bytes() == active.read_bytes():
                    continue
            except OSError:
                continue
        kind, binary = _change_type(original, active)
        changes.append(WorkspaceChange(path=rel, change_type=kind, binary=binary))
        if binary:
            diff_parts.append(f"Binary file changed: {rel} ({kind})\n")
            continue
        old_lines = _read_text_for_diff(original) if original.exists() else []
        new_lines = _read_text_for_diff(active) if active.exists() else []
        if old_lines is None or new_lines is None:
            diff_parts.append(f"Binary or unreadable file changed: {rel} ({kind})\n")
            continue
        old_name = f"a/{rel}" if original.exists() else "/dev/null"
        new_name = f"b/{rel}" if active.exists() else "/dev/null"
        diff_parts.extend(
            difflib.unified_diff(old_lines, new_lines, fromfile=old_name, tofile=new_name)
        )
        current_len = sum(len(part) for part in diff_parts)
        if diff_budget and current_len > diff_budget:
            diff_parts.append("\n...[DIFF TRUNCATED BY AGENT_WORKSPACE_DIFF_MAX_CHARS]...\n")
            break
    return changes, "".join(diff_parts)


def create_agent_workspace(
    root: Path, *, mode: str, keep_workspace: bool, max_file_bytes: int
) -> AgentWorkspaceSession:
    """Create an agent workspace session according to mode."""

    mode = mode.strip().lower()
    if mode not in SUPPORTED_AGENT_WORKSPACE_MODES:
        raise ValueError(f"unsupported agent_workspace_mode={mode!r}; use direct or isolated")
    root = root.resolve()
    if mode == "direct":
        return AgentWorkspaceSession(mode="direct", original_root=root, active_root=root)
    workspace = create_workspace_copy(root, max_file_bytes=max_file_bytes)
    workspace_id = workspace.parent.name
    artifact_dir = root / ".minicodex" / "agent_workspaces" / workspace_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return AgentWorkspaceSession(
        mode="isolated",
        original_root=root,
        active_root=workspace,
        workspace_id=workspace_id,
        artifact_dir=artifact_dir,
        keep_workspace=keep_workspace,
    )


def finalize_agent_workspace(
    session: AgentWorkspaceSession, *, max_diff_chars: int = 24000, dry_run: bool = False
) -> AgentWorkspaceSession:
    """Compute and persist isolated workspace diff/manifest."""

    if not session.isolated:
        return session
    changes, diff_text = compute_workspace_changes(
        session.original_root, session.active_root, max_diff_chars=max_diff_chars
    )
    session.changes = changes
    session.diff_text = diff_text
    if session.artifact_dir is not None and not dry_run:
        session.artifact_dir.mkdir(parents=True, exist_ok=True)
        diff_path = session.artifact_dir / "changes.diff"
        manifest_path = session.artifact_dir / "manifest.json"
        diff_path.write_text(diff_text, encoding="utf-8")
        manifest = {
            "workspace_id": session.workspace_id,
            "mode": session.mode,
            "original_root": str(session.original_root),
            "active_root": str(session.active_root),
            "change_count": len(changes),
            "changes": [change.__dict__ for change in changes],
            "diff_path": str(diff_path),
            "kept_workspace": session.keep_workspace,
        }
        manifest_path.write_text(to_pretty_json(manifest), encoding="utf-8")
        session.diff_path = diff_path
        session.manifest_path = manifest_path
    return session


def render_workspace_summary(session: AgentWorkspaceSession, *, max_chars: int = 12000) -> str:
    """Render a human-readable workspace isolation summary."""

    if not session.isolated:
        return "Agent workspace: direct project-root mode; no isolated diff was produced."
    payload = {
        "agent_workspace": {
            "mode": session.mode,
            "workspace_id": session.workspace_id,
            "original_root": str(session.original_root),
            "active_root": str(session.active_root),
            "change_count": len(session.changes),
            "changes": [change.__dict__ for change in session.changes],
            "diff_path": str(session.diff_path) if session.diff_path else "",
            "manifest_path": str(session.manifest_path) if session.manifest_path else "",
            "applied_to_original": session.applied,
            "apply_warnings": session.apply_warnings,
        },
        "diff_preview": session.diff_text,
    }
    return truncate(to_pretty_json(payload), max_chars)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def apply_workspace_changes(session: AgentWorkspaceSession, *, dry_run: bool = False) -> str:
    """Apply isolated workspace changes back to the original root by file sync.

    This is intentionally path-based rather than shelling out to patch. Sensitive
    paths are never applied, and all paths come from the diff comparator's safe
    path set.
    """

    if not session.isolated:
        return "Agent workspace apply skipped: direct mode."
    if not session.changes:
        finalize_agent_workspace(session, dry_run=dry_run)
    applied: list[str] = []
    skipped: list[str] = []
    for change in session.changes:
        rel = Path(change.path)
        source = session.active_root / rel
        target = session.original_root / rel
        if should_skip_path(target, session.original_root) or sensitive_path_reason(
            target, session.original_root
        ):
            skipped.append(f"{change.path}: sensitive path blocked")
            continue
        if dry_run:
            applied.append(f"DRY-RUN {change.change_type} {change.path}")
            continue
        if change.change_type.endswith("deleted") or change.change_type == "deleted":
            if target.exists() and target.is_file():
                target.unlink()
                applied.append(f"deleted {change.path}")
            continue
        if not source.exists() or not source.is_file():
            skipped.append(f"{change.path}: source missing or not file")
            continue
        _ensure_parent(target)
        shutil.copy2(source, target)
        applied.append(f"{change.change_type} {change.path}")
    session.applied = bool(applied) and not dry_run
    session.apply_warnings.extend(skipped)
    return to_pretty_json({"applied": applied, "skipped": skipped, "dry_run": dry_run})


def cleanup_agent_workspace(session: AgentWorkspaceSession) -> None:
    """Remove the temporary workspace copy unless the user requested to keep it."""

    if session.isolated and not session.keep_workspace:
        cleanup_workspace(session.active_root)
