"""Filesystem tools exposed to the agent."""

from __future__ import annotations

import difflib
import shutil
import time
import uuid
from pathlib import Path

from .safety import EXCLUDED_FILE_SUFFIXES, safe_resolve, sensitive_path_reason, should_skip_path
from .utils import truncate

DEFAULT_DIFF_CHARS = 10000


def is_probably_binary(path: Path) -> bool:
    """Heuristic binary-file detection."""

    if path.suffix.lower() in EXCLUDED_FILE_SUFFIXES:
        return True

    try:
        with path.open("rb") as file:
            chunk = file.read(2048)
    except OSError:
        return True

    return b"\0" in chunk


def backup_file(path: Path) -> Path | None:
    """Create a timestamped backup before overwriting a file."""

    if not path.exists():
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak_{timestamp}_{uuid.uuid4().hex[:12]}")
    shutil.copy2(path, backup)
    return backup


def unified_diff(
    old: str, new: str, fromfile: str, tofile: str, max_chars: int = DEFAULT_DIFF_CHARS
) -> str:
    """Return a unified text diff."""

    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
    )
    return truncate("".join(diff), max_chars)


def list_files(root: Path, start_path: str = ".", max_files: int = 200) -> str:
    """List visible files under a workspace path."""

    target = safe_resolve(root, start_path)

    if not target.exists():
        return f"Path bulunamadı: {start_path}"

    if should_skip_path(target, root):
        reason = sensitive_path_reason(target, root)
        if reason:
            return f"Hassas dosya gizlendi: {start_path} ({reason})"
        return f"Path gizlendi veya desteklenmiyor: {start_path}"

    if target.is_file():
        return target.relative_to(root).as_posix()

    rows: list[str] = []
    count = 0

    for path in sorted(target.rglob("*")):
        if count >= max_files:
            rows.append(f"... {max_files} girdiden sonra kesildi")
            break

        if should_skip_path(path, root):
            continue

        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            rows.append(f"[DIR]  {rel}")
        else:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            rows.append(f"[FILE] {rel} ({size} bytes)")
        count += 1

    return "\n".join(rows) if rows else "Görünen dosya bulunamadı."


def read_file(root: Path, user_path: str, max_chars: int) -> str:
    """Read a text file from the workspace."""

    path = safe_resolve(root, user_path)

    if not path.exists():
        return f"Dosya bulunamadı: {user_path}"
    if not path.is_file():
        return f"Dosya değil: {user_path}"
    reason = sensitive_path_reason(path, root)
    if reason:
        return f"Hassas dosya okuma engellendi: {user_path} ({reason})"
    if is_probably_binary(path):
        return f"Binary veya desteklenmeyen dosya atlandı: {user_path}"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Dosya okunamadı {user_path}: {exc}"

    return truncate(text, max_chars)


def preview_write_file(
    root: Path, user_path: str, content: str, max_chars: int = DEFAULT_DIFF_CHARS
) -> str:
    """Preview the diff that would be produced by writing a file."""

    path = safe_resolve(root, user_path)
    old = ""
    if path.exists() and path.is_file():
        reason = sensitive_path_reason(path, root)
        if reason:
            return f"Hassas dosya önizleme engellendi: {user_path} ({reason})"
        if not is_probably_binary(path):
            old = path.read_text(encoding="utf-8", errors="replace")
    return unified_diff(
        old, content, fromfile=f"a/{user_path}", tofile=f"b/{user_path}", max_chars=max_chars
    )


def write_file(root: Path, user_path: str, content: str, dry_run: bool = False) -> str:
    """Create or overwrite a text file inside the workspace."""

    path = safe_resolve(root, user_path)

    if ".git" in path.parts:
        raise ValueError(".git klasörü içine yazmayı reddediyorum.")
    reason = sensitive_path_reason(path, root)
    if reason:
        return f"Hassas dosya yazma engellendi: {user_path} ({reason})"

    diff = preview_write_file(root, user_path, content)
    if dry_run:
        return f"DRY-RUN: dosya yazılmadı: {user_path}\n\nDiff önizleme:\n{diff}"

    path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_file(path)
    path.write_text(content, encoding="utf-8")

    if backup:
        return (
            f"Dosya yazıldı: {user_path}\n"
            f"Yedek oluşturuldu: {backup.relative_to(root)}\n\nDiff:\n{diff}"
        )
    return f"Dosya oluşturuldu: {user_path}\n\nDiff:\n{diff}"


def preview_replace_in_file(
    root: Path,
    user_path: str,
    old: str,
    new: str,
    count: int = 1,
    max_chars: int = DEFAULT_DIFF_CHARS,
) -> str:
    """Preview the diff for an exact text replacement."""

    path = safe_resolve(root, user_path)
    if not path.exists():
        return f"Dosya bulunamadı: {user_path}"
    if not path.is_file():
        return f"Dosya değil: {user_path}"
    reason = sensitive_path_reason(path, root)
    if reason:
        return f"Hassas dosya okuma engellendi: {user_path} ({reason})"
    if is_probably_binary(path):
        return f"Binary veya desteklenmeyen dosya atlandı: {user_path}"

    text = path.read_text(encoding="utf-8", errors="replace")
    occurrences = text.count(old)
    if occurrences == 0:
        return f"Eski metin dosyada bulunamadı: {user_path}"
    if count <= 0:
        count = occurrences
    updated = text.replace(old, new, count)
    diff = unified_diff(text, updated, f"a/{user_path}", f"b/{user_path}", max_chars=max_chars)
    return f"Bulunan eşleşme: {occurrences}\nDeğişecek eşleşme: {min(count, occurrences)}\n\n{diff}"


def replace_in_file(
    root: Path,
    user_path: str,
    old: str,
    new: str,
    count: int = 1,
    dry_run: bool = False,
) -> str:
    """Replace exact text inside a file."""

    path = safe_resolve(root, user_path)

    if not path.exists():
        return f"Dosya bulunamadı: {user_path}"
    if not path.is_file():
        return f"Dosya değil: {user_path}"
    reason = sensitive_path_reason(path, root)
    if reason:
        return f"Hassas dosya okuma engellendi: {user_path} ({reason})"
    if is_probably_binary(path):
        return f"Binary veya desteklenmeyen dosya atlandı: {user_path}"

    text = path.read_text(encoding="utf-8", errors="replace")
    occurrences = text.count(old)

    if occurrences == 0:
        return f"Eski metin dosyada bulunamadı: {user_path}"

    if count <= 0:
        count = occurrences

    updated = text.replace(old, new, count)
    diff = unified_diff(text, updated, f"a/{user_path}", f"b/{user_path}")
    if dry_run:
        return f"DRY-RUN: dosya güncellenmedi: {user_path}\n\n{diff}"

    backup = backup_file(path)
    path.write_text(updated, encoding="utf-8")

    backup_msg = f"\nYedek oluşturuldu: {backup.relative_to(root)}" if backup else ""
    return (
        f"Dosya güncellendi: {user_path}\n"
        f"Bulunan eşleşme: {occurrences}\n"
        f"Değiştirilen eşleşme: {min(count, occurrences)}"
        f"{backup_msg}\n\nDiff:\n{diff}"
    )


def list_dir(root: Path, user_path: str = ".", max_entries: int = 200) -> str:
    """List only the immediate entries under a directory.

    This is cheaper and more predictable than recursive list_files for large
    repositories, so models can inspect a repo layer by layer.
    """

    target = safe_resolve(root, user_path)
    if not target.exists():
        return f"Path bulunamadı: {user_path}"
    if should_skip_path(target, root):
        reason = sensitive_path_reason(target, root)
        if reason:
            return f"Hassas path gizlendi: {user_path} ({reason})"
        return f"Path gizlendi veya desteklenmiyor: {user_path}"
    if target.is_file():
        try:
            size = target.stat().st_size
        except OSError:
            size = 0
        return f"[FILE] {target.relative_to(root).as_posix()} ({size} bytes)"

    rows: list[str] = []
    entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    for idx, path in enumerate(entries):
        if idx >= max_entries:
            rows.append(f"... {max_entries} girdiden sonra kesildi")
            break
        if should_skip_path(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            rows.append(f"[DIR]  {rel}/")
        else:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            rows.append(f"[FILE] {rel} ({size} bytes)")
    return "\n".join(rows) if rows else "Görünen dosya bulunamadı."


def glob_file_search(
    root: Path, pattern: str, start_path: str = ".", max_matches: int = 200
) -> str:
    """Find visible files matching a glob pattern relative to a start path."""

    if not pattern.strip():
        return "Glob pattern boş olamaz."
    target = safe_resolve(root, start_path)
    if not target.exists():
        return f"Path bulunamadı: {start_path}"
    if should_skip_path(target, root):
        reason = sensitive_path_reason(target, root)
        if reason:
            return f"Hassas path gizlendi: {start_path} ({reason})"
        return f"Path gizlendi veya desteklenmiyor: {start_path}"

    candidates = [target] if target.is_file() else sorted(target.rglob("*"))
    matches: list[str] = []
    for path in candidates:
        if len(matches) >= max_matches:
            break
        if path.is_dir() or should_skip_path(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        local_rel = path.relative_to(target).as_posix() if target.is_dir() else path.name
        if Path(rel).match(pattern) or Path(local_rel).match(pattern) or path.match(pattern):
            matches.append(rel)

    if not matches:
        return f"Glob eşleşmesi bulunamadı: {pattern}"
    suffix = "" if len(matches) < max_matches else f"\n... ilk {max_matches} eşleşme gösterildi"
    return "\n".join(matches) + suffix


def read_file_range(
    root: Path,
    user_path: str,
    start_line: int = 1,
    end_line: int | None = None,
    max_chars: int = 12000,
) -> str:
    """Read a bounded, line-numbered range from a text file."""

    path = safe_resolve(root, user_path)
    if not path.exists():
        return f"Dosya bulunamadı: {user_path}"
    if not path.is_file():
        return f"Dosya değil: {user_path}"
    reason = sensitive_path_reason(path, root)
    if reason:
        return f"Hassas dosya okuma engellendi: {user_path} ({reason})"
    if is_probably_binary(path):
        return f"Binary veya desteklenmeyen dosya atlandı: {user_path}"

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"Dosya okunamadı {user_path}: {exc}"

    start_line = max(1, int(start_line))
    if end_line is None or int(end_line) <= 0:
        end_line = min(len(lines), start_line + 120 - 1)
    end_line = min(len(lines), max(start_line, int(end_line)))
    width = len(str(end_line))
    selected = [f"{idx:>{width}} | {lines[idx - 1]}" for idx in range(start_line, end_line + 1)]
    header = f"{user_path}:{start_line}-{end_line} of {len(lines)} lines"
    return truncate(header + "\n" + "\n".join(selected), max_chars)
