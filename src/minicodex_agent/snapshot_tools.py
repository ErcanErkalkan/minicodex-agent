"""Filesystem snapshot and rollback helpers for MiniCodex.

Snapshots are intentionally conservative: they copy text-like project files into
``.minicodex/snapshots`` while skipping common dependency/build/cache folders.
They are not a replacement for Git, but they help rollback local agent edits in
small and medium projects.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .fs_tools import is_probably_binary
from .safety import safe_resolve, sensitive_path_reason, should_skip_path
from .utils import truncate

SNAPSHOT_ROOT = ".minicodex/snapshots"
SNAPSHOT_IGNORE_FILE = ".minicodex/snapshot_ignore"
DEFAULT_MAX_FILES = 1000
DEFAULT_MAX_BYTES_PER_FILE = 500_000


def _load_snapshot_ignore(root: Path) -> list[str]:
    ignore_path = root / SNAPSHOT_IGNORE_FILE
    if not ignore_path.exists():
        return []
    try:
        return [
            line.strip()
            for line in ignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except OSError:
        return []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skip_reason(path: Path, root: Path, ignore_globs: list[str] | None = None) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return "outside workspace"
    if rel.parts and rel.parts[0] == ".minicodex":
        return "MiniCodex internal state"
    for pattern in ignore_globs or []:
        if fnmatch.fnmatch(str(rel), pattern):
            return "snapshot_ignore"
    sensitive_reason = sensitive_path_reason(path, root)
    if sensitive_reason:
        return sensitive_reason
    if should_skip_path(path, root):
        return "excluded path or unsupported file type"
    return None


def _skip(path: Path, root: Path, ignore_globs: list[str] | None = None) -> bool:
    return _skip_reason(path, root, ignore_globs) is not None


def _snapshot_dir(root: Path, snapshot_id: str) -> Path:
    return root / SNAPSHOT_ROOT / snapshot_id


def create_snapshot(
    root: Path,
    *,
    label: str = "manual",
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes_per_file: int = DEFAULT_MAX_BYTES_PER_FILE,
    dry_run: bool = False,
) -> str:
    """Create a local snapshot of text-like project files."""

    root = root.resolve()
    safe_label = (
        "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label.strip()[:40]).strip("-")
        or "snapshot"
    )
    snapshot_id = time.strftime("%Y%m%d_%H%M%S") + "_" + safe_label + "_" + uuid.uuid4().hex[:8]
    target = _snapshot_dir(root, snapshot_id)
    files_dir = target / "files"

    ignore_globs = _load_snapshot_ignore(root)
    manifest: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "label": label,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "snapshot_schema_version": 2,
        "ignore_file": SNAPSHOT_IGNORE_FILE,
        "ignore_globs": ignore_globs,
        "preserves_file_metadata": True,
        "files": [],
        "skipped": [],
    }

    copied = 0
    for path in sorted(root.rglob("*")):
        if copied >= max_files:
            manifest["skipped"].append({"path": "...", "reason": "max_files reached"})
            break
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        skip_reason = _skip_reason(path, root, ignore_globs)
        if skip_reason:
            manifest["skipped"].append({"path": str(rel), "reason": skip_reason})
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_bytes_per_file:
            manifest["skipped"].append({"path": str(rel), "reason": "too large"})
            continue
        if is_probably_binary(path):
            manifest["skipped"].append({"path": str(rel), "reason": "binary"})
            continue
        stat = path.stat()
        manifest["files"].append(
            {
                "path": str(rel),
                "size": size,
                "mode": oct(stat.st_mode & 0o777),
                "mtime": stat.st_mtime,
                "sha256": _sha256(path),
            }
        )
        copied += 1

    if dry_run:
        shown = "\n".join(f"- {item['path']}" for item in manifest["files"][:80])
        if len(manifest["files"]) > 80:
            shown += f"\n... {len(manifest['files']) - 80} more"
        return truncate(
            f"DRY-RUN: snapshot not created: {snapshot_id}\n"
            f"Files that would be copied: {copied}\n"
            f"Skipped: {len(manifest['skipped'])}\n"
            + (shown if shown else "No files would be copied."),
            12000,
        )

    files_dir.mkdir(parents=True, exist_ok=False)
    for item in manifest["files"]:
        rel = Path(str(item["path"]))
        src = root / rel
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return (
        f"Snapshot created: {snapshot_id}\n"
        f"Files copied: {copied}\n"
        f"Manifest: {(target / 'manifest.json').relative_to(root)}"
    )


def list_snapshots(root: Path, limit: int = 20) -> str:
    """List available local snapshots."""

    base = root / SNAPSHOT_ROOT
    if not base.exists():
        return "No snapshots found."

    manifests = sorted(base.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
    if not manifests:
        return "No snapshots found."

    selected = manifests[-max(1, limit) :]
    lines = [f"Showing {len(selected)} snapshot(s):"]
    for manifest_path in selected:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        lines.append(
            f"- {data.get('snapshot_id', manifest_path.parent.name)} | "
            f"label={data.get('label', '-')} | "
            f"created={data.get('created_at', '-')} | "
            f"files={len(data.get('files', []))}"
        )
    return "\n".join(lines)


def restore_snapshot(
    root: Path, snapshot_id: str, *, dry_run: bool = False, create_restore_backup: bool = True
) -> str:
    """Restore files from a local snapshot.

    The restore only writes files listed in the snapshot manifest. It does not
    delete files that were created after the snapshot.
    """

    root = root.resolve()
    target = _snapshot_dir(root, snapshot_id)
    manifest_path = target / "manifest.json"
    files_dir = target / "files"

    if not manifest_path.exists() or not files_dir.exists():
        return f"Snapshot not found or invalid: {snapshot_id}"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"Snapshot manifest is invalid: {exc}"

    restore_backup_note = ""
    if not dry_run and create_restore_backup:
        restore_backup_note = create_snapshot(
            root,
            label="pre-restore",
            max_files=DEFAULT_MAX_FILES,
            max_bytes_per_file=DEFAULT_MAX_BYTES_PER_FILE,
        )

    restored: list[str] = []
    for item in manifest.get("files", []):
        rel = str(item.get("path", ""))
        if not rel:
            continue
        src = files_dir / rel
        dest = safe_resolve(root, rel)
        if not src.exists():
            continue
        restored.append(rel)
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            mode = str(item.get("mode", ""))
            if mode.startswith("0o"):
                try:
                    dest.chmod(int(mode, 8))
                except OSError:
                    pass

    prefix = "DRY-RUN: would restore" if dry_run else "Restored"
    details = "\n".join(f"- {path}" for path in restored[:200])
    if len(restored) > 200:
        details += f"\n... {len(restored) - 200} more"
    note = f"{prefix} {len(restored)} file(s) from snapshot {snapshot_id}.\n{details}"
    if restore_backup_note:
        note += "\n\nPre-restore safety snapshot:\n" + restore_backup_note
    return truncate(note, 12000)
