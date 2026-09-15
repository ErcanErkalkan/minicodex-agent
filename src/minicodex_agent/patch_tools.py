"""Transactional unified-diff patch preview and application tools."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .fs_tools import is_probably_binary, unified_diff
from .safety import safe_resolve, sensitive_path_reason
from .utils import truncate


@dataclass
class Hunk:
    """One unified diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    """Patch instructions for a single file."""

    old_path: str = ""
    new_path: str = ""
    hunks: list[Hunk] = field(default_factory=list)
    new_file: bool = False
    deleted_file: bool = False
    rename_from: str | None = None
    rename_to: str | None = None
    old_mode: int | None = None
    new_mode: int | None = None
    binary: bool = False

    @property
    def write_path(self) -> str:
        if self.deleted_file:
            return self.old_path
        return self.new_path or self.rename_to or self.old_path


@dataclass
class PlannedPatchOperation:
    """An already-validated patch operation."""

    file_patch: FilePatch
    old_path: Path | None
    new_path: Path | None
    rel_old: str | None
    rel_new: str | None
    before_text: str
    after_text: str | None
    before_new_text: str | None = None
    before_mode: int | None = None
    after_mode: int | None = None
    old_existed: bool = False
    new_existed: bool = False
    newline: str = "\n"


@dataclass(frozen=True)
class PatchOperationSummary:
    """Compact, serializable summary for one planned file operation."""

    operation: str
    path: str
    old_path: str | None
    new_path: str | None
    hunks: int
    old_lines: int
    new_lines: int
    additions: int
    deletions: int
    mode_change: str | None = None


@dataclass(frozen=True)
class PatchPlanSummary:
    """Serializable patch plan used by preview/diagnostic tools."""

    ok: bool
    files: tuple[PatchOperationSummary, ...]
    total_files: int
    total_hunks: int
    total_additions: int
    total_deletions: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_json(self) -> str:
        """Return stable JSON for the model/tool output."""

        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class PatchVerification:
    """Post-apply verification result."""

    ok: bool
    checked_files: tuple[str, ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def render(self) -> str:
        status = "ok" if self.ok else "failed"
        lines = [f"Patch verification: {status}"]
        if self.checked_files:
            lines.append("Checked files: " + ", ".join(self.checked_files))
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {item}" for item in self.warnings)
        if self.errors:
            lines.append("Errors:")
            lines.extend(f"- {item}" for item in self.errors)
        return "\n".join(lines)


HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DIFF_GIT_RE = re.compile(r"^diff --git\s+(\S+)\s+(\S+)")
MODE_RE = re.compile(r"^(?:old mode|new mode|deleted file mode|new file mode)\s+([0-7]{6})")


def _normalize_patch_path(path: str) -> str:
    path = path.strip()
    if path == "/dev/null":
        return path
    # Remove optional timestamp after file path in classic unified diff.
    path = path.split("\t", 1)[0].split("  ", 1)[0]
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _mode_from_line(line: str) -> int | None:
    match = MODE_RE.match(line)
    if not match:
        return None
    return int(match.group(1), 8)


def parse_unified_patch(patch_text: str) -> list[FilePatch]:
    """Parse a unified/git diff into file patches.

    Supported text operations include create, modify, delete, rename/move, and
    mode changes. Git binary patches are detected but intentionally rejected by
    the apply phase because MiniCodex only edits text safely.
    """

    lines = patch_text.splitlines(keepends=True)
    patches: list[FilePatch] = []
    current: FilePatch | None = None
    current_hunk: Hunk | None = None
    pending_old_path: str | None = None

    def ensure_current() -> FilePatch:
        nonlocal current
        if current is None:
            current = FilePatch()
            patches.append(current)
        return current

    for line in lines:
        stripped = line.rstrip("\r\n")

        git_match = DIFF_GIT_RE.match(stripped)
        if git_match:
            current = FilePatch(
                old_path=_normalize_patch_path(git_match.group(1)),
                new_path=_normalize_patch_path(git_match.group(2)),
            )
            patches.append(current)
            current_hunk = None
            pending_old_path = None
            continue

        if stripped.startswith("new file mode "):
            patch = ensure_current()
            patch.new_file = True
            patch.new_mode = _mode_from_line(stripped)
            continue

        if stripped.startswith("deleted file mode "):
            patch = ensure_current()
            patch.deleted_file = True
            patch.old_mode = _mode_from_line(stripped)
            continue

        if stripped.startswith("old mode "):
            ensure_current().old_mode = _mode_from_line(stripped)
            continue

        if stripped.startswith("new mode "):
            ensure_current().new_mode = _mode_from_line(stripped)
            continue

        if stripped.startswith("rename from "):
            patch = ensure_current()
            patch.rename_from = _normalize_patch_path(stripped[len("rename from ") :])
            patch.old_path = patch.rename_from
            continue

        if stripped.startswith("rename to "):
            patch = ensure_current()
            patch.rename_to = _normalize_patch_path(stripped[len("rename to ") :])
            patch.new_path = patch.rename_to
            continue

        if stripped.startswith("Binary files ") or stripped == "GIT binary patch":
            ensure_current().binary = True
            current_hunk = None
            continue

        if line.startswith("--- "):
            pending_old_path = _normalize_patch_path(line[4:].strip())
            # Classic multi-file unified diffs do not always include
            # `diff --git`; a new --- line after hunks starts a new file patch.
            if current is None or current.hunks or current_hunk is not None:
                current = FilePatch()
                patches.append(current)
            patch = ensure_current()
            patch.old_path = pending_old_path
            patch.deleted_file = pending_old_path != "/dev/null" and patch.deleted_file
            current_hunk = None
            continue

        if line.startswith("+++ "):
            if pending_old_path is None and current is None:
                raise ValueError("Patch içinde +++ satırından önce --- satırı yok.")
            new_path = _normalize_patch_path(line[4:].strip())
            patch = ensure_current()
            patch.new_path = new_path
            patch.new_file = patch.old_path == "/dev/null" or patch.new_file
            patch.deleted_file = new_path == "/dev/null" or patch.deleted_file
            current_hunk = None
            continue

        match = HUNK_HEADER_RE.match(line)
        if match:
            patch = ensure_current()
            old_count = int(match.group(2) or "1")
            new_count = int(match.group(4) or "1")
            current_hunk = Hunk(
                old_start=int(match.group(1)),
                old_count=old_count,
                new_start=int(match.group(3)),
                new_count=new_count,
            )
            patch.hunks.append(current_hunk)
            continue

        if current_hunk is not None:
            if line.startswith((" ", "+", "-")) or line.startswith("\\ No newline"):
                current_hunk.lines.append(line)
            elif line.strip() == "":
                # A truly blank line in a hunk is normally represented as ' \n' or '+\n'.
                current_hunk.lines.append(line)

    return [
        patch
        for patch in patches
        if patch.old_path or patch.new_path or patch.hunks or patch.binary
    ]


def _assert_text_line_matches(actual: str, expected: str, file_path: str, line_index: int) -> None:
    if actual == expected:
        return
    if actual.rstrip("\r\n") == expected.rstrip("\r\n"):
        return
    raise ValueError(
        f"Patch uygulanamadı: {file_path}:{line_index + 1} beklenen satır eşleşmedi.\n"
        f"Beklenen: {expected.rstrip()}\n"
        f"Bulunan: {actual.rstrip()}"
    )


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def _adapt_added_line(content: str, newline: str) -> str:
    if content.endswith("\r\n"):
        body = content[:-2]
        return body + newline
    if content.endswith("\n"):
        body = content[:-1]
        return body + newline
    if content.endswith("\r"):
        body = content[:-1]
        return body + newline
    return content


def _apply_file_patch_to_text(original: str, file_patch: FilePatch, *, fuzzy: bool = False) -> str:
    old_lines = original.splitlines(keepends=True)
    result: list[str] = []
    source_index = 0
    newline = _detect_newline(original)

    for hunk in file_patch.hunks:
        target_index = max(hunk.old_start - 1, 0)
        if target_index < source_index:
            raise ValueError(f"Patch hunk sırası hatalı: {file_patch.write_path}")

        if fuzzy and target_index < len(old_lines) and hunk.lines:
            target_index = _find_fuzzy_hunk_start(old_lines, hunk.lines, target_index, source_index)

        result.extend(old_lines[source_index:target_index])
        source_index = target_index

        for raw_line in hunk.lines:
            if raw_line.startswith("\\ No newline"):
                continue
            if not raw_line:
                continue
            marker = raw_line[0]
            content = raw_line[1:]

            if marker == " ":
                if source_index >= len(old_lines):
                    raise ValueError(f"Patch context dosya sonunu aştı: {file_patch.write_path}")
                _assert_text_line_matches(
                    old_lines[source_index], content, file_patch.write_path, source_index
                )
                result.append(old_lines[source_index])
                source_index += 1
            elif marker == "-":
                if source_index >= len(old_lines):
                    raise ValueError(
                        f"Patch silme satırı dosya sonunu aştı: {file_patch.write_path}"
                    )
                _assert_text_line_matches(
                    old_lines[source_index], content, file_patch.write_path, source_index
                )
                source_index += 1
            elif marker == "+":
                result.append(_adapt_added_line(content, newline))
            else:
                raise ValueError(f"Desteklenmeyen patch satırı: {raw_line!r}")

    result.extend(old_lines[source_index:])
    return "".join(result)


def _find_fuzzy_hunk_start(
    old_lines: list[str], hunk_lines: list[str], preferred: int, min_index: int
) -> int:
    """Find a nearby hunk start using context/deletion lines.

    This is intentionally conservative: it only shifts when all context and
    deletion lines match exactly ignoring newline style.
    """

    pattern = [line[1:] for line in hunk_lines if line.startswith((" ", "-"))]
    if not pattern:
        return preferred

    def matches(start: int) -> bool:
        if start < min_index or start + len(pattern) > len(old_lines):
            return False
        for offset, expected in enumerate(pattern):
            if old_lines[start + offset].rstrip("\r\n") != expected.rstrip("\r\n"):
                return False
        return True

    if matches(preferred):
        return preferred

    for radius in range(1, 6):
        for candidate in (preferred - radius, preferred + radius):
            if matches(candidate):
                return candidate
    return preferred


def _read_text(path: Path) -> str:
    # newline="" preserves CRLF/CR line endings so added hunk lines can follow
    # the existing file style instead of silently normalizing to LF.
    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        return file.read()


def _write_text(path: Path, content: str) -> None:
    """Write text without platform newline translation."""

    path.write_text(content, encoding="utf-8", newline="")


def _chmod_from_git_mode(path: Path, git_mode: int | None) -> None:
    if git_mode is None or not path.exists():
        return
    # Git modes such as 100644 / 100755 include object type bits; chmod only wants permissions.
    permissions = git_mode & 0o777
    try:
        os.chmod(path, permissions)
    except OSError as exc:
        raise OSError(f"Permission mode değiştirilemedi: {path}: {exc}") from exc


def _safe_patch_path(root: Path, rel: str | None) -> Path | None:
    if not rel or rel == "/dev/null":
        return None
    path = safe_resolve(root, rel)
    if ".git" in path.parts:
        raise ValueError(".git klasörü içinde patch uygulamayı reddediyorum.")
    reason = sensitive_path_reason(path, root)
    if reason:
        raise ValueError(f"Hassas dosyaya patch uygulanamaz: {rel} ({reason})")
    return path


def _mode(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    return stat.S_IMODE(path.stat().st_mode)


def _backup_file_uuid(path: Path) -> Path | None:
    """Create a collision-resistant backup before overwriting/deleting a file."""

    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + f".bak_{uuid.uuid4().hex[:12]}")
    shutil.copy2(path, backup)
    return backup


def _plan_file_patch(
    root: Path, file_patch: FilePatch, *, fuzzy: bool = False
) -> PlannedPatchOperation:
    if file_patch.binary:
        raise ValueError(
            f"Binary patch desteklenmiyor: {file_patch.write_path or file_patch.old_path}"
        )

    rel_old = (
        None
        if file_patch.old_path == "/dev/null"
        else (file_patch.rename_from or file_patch.old_path or None)
    )
    rel_new = (
        None
        if file_patch.new_path == "/dev/null"
        else (file_patch.rename_to or file_patch.new_path or None)
    )
    old_path = _safe_patch_path(root, rel_old)
    new_path = _safe_patch_path(root, rel_new)

    if old_path is not None and old_path.exists() and is_probably_binary(old_path):
        raise ValueError(f"Binary veya desteklenmeyen dosyaya patch uygulanamaz: {rel_old}")
    if new_path is not None and new_path.exists() and is_probably_binary(new_path):
        raise ValueError(f"Binary veya desteklenmeyen dosyaya patch uygulanamaz: {rel_new}")

    old_existed = bool(old_path and old_path.exists())
    new_existed = bool(new_path and new_path.exists())
    before_text = _read_text(old_path) if old_path and old_path.exists() else ""
    before_new_text = _read_text(new_path) if new_path and new_path.exists() else None
    before_mode = _mode(old_path) if old_path else _mode(new_path)
    after_mode = file_patch.new_mode

    if file_patch.deleted_file or file_patch.new_path == "/dev/null":
        if old_path is None or not old_path.exists():
            raise ValueError(f"Patch silme işlemi uygulanamadı, dosya yok: {rel_old}")
        after_text = (
            _apply_file_patch_to_text(before_text, file_patch, fuzzy=fuzzy)
            if file_patch.hunks
            else ""
        )
        if after_text.strip():
            raise ValueError(f"Delete patch sonrasında dosya boş kalmadı: {rel_old}")
        return PlannedPatchOperation(
            file_patch=file_patch,
            old_path=old_path,
            new_path=None,
            rel_old=rel_old,
            rel_new=None,
            before_text=before_text,
            after_text=None,
            before_new_text=before_new_text,
            before_mode=before_mode,
            after_mode=None,
            old_existed=old_existed,
            new_existed=False,
            newline=_detect_newline(before_text),
        )

    if file_patch.rename_from or file_patch.rename_to:
        if old_path is None or new_path is None:
            raise ValueError("Rename patch hem kaynak hem hedef dosya gerektirir.")
        if not old_path.exists():
            raise ValueError(f"Rename kaynak dosyası yok: {rel_old}")
        if new_path.exists() and old_path.resolve() != new_path.resolve():
            raise ValueError(f"Rename hedefi zaten var: {rel_new}")
        after_text = (
            _apply_file_patch_to_text(before_text, file_patch, fuzzy=fuzzy)
            if file_patch.hunks
            else before_text
        )
        return PlannedPatchOperation(
            file_patch=file_patch,
            old_path=old_path,
            new_path=new_path,
            rel_old=rel_old,
            rel_new=rel_new,
            before_text=before_text,
            after_text=after_text,
            before_new_text=before_new_text,
            before_mode=before_mode,
            after_mode=after_mode,
            old_existed=old_existed,
            new_existed=new_existed,
            newline=_detect_newline(before_text),
        )

    if file_patch.old_path == "/dev/null" or file_patch.new_file:
        if new_path is None:
            raise ValueError("Create patch hedef dosya gerektirir.")
        if new_path.exists():
            # Git patches for new files should not overwrite an existing file.
            raise ValueError(f"Create patch hedefi zaten var: {rel_new}")
        after_text = _apply_file_patch_to_text("", file_patch, fuzzy=fuzzy)
        return PlannedPatchOperation(
            file_patch=file_patch,
            old_path=None,
            new_path=new_path,
            rel_old=None,
            rel_new=rel_new,
            before_text="",
            after_text=after_text,
            before_new_text=None,
            before_mode=None,
            after_mode=after_mode,
            old_existed=False,
            new_existed=False,
        )

    if new_path is None:
        raise ValueError(f"Patch hedef dosyası belirlenemedi: {file_patch}")
    if not new_path.exists():
        raise ValueError(f"Patch uygulanamadı, dosya yok: {rel_new}")
    original = _read_text(new_path)
    after_text = (
        _apply_file_patch_to_text(original, file_patch, fuzzy=fuzzy)
        if file_patch.hunks
        else original
    )
    return PlannedPatchOperation(
        file_patch=file_patch,
        old_path=new_path,
        new_path=new_path,
        rel_old=rel_new,
        rel_new=rel_new,
        before_text=original,
        after_text=after_text,
        before_new_text=before_new_text,
        before_mode=_mode(new_path),
        after_mode=after_mode,
        old_existed=True,
        new_existed=True,
        newline=_detect_newline(original),
    )


def _plan_patch(root: Path, patch_text: str, *, fuzzy: bool = False) -> list[PlannedPatchOperation]:
    patches = parse_unified_patch(patch_text)
    if not patches:
        raise ValueError("Patch içinde uygulanabilir dosya değişikliği bulunamadı.")
    return [_plan_file_patch(root, patch, fuzzy=fuzzy) for patch in patches]


def _operation_kind(operation: PlannedPatchOperation) -> str:
    patch = operation.file_patch
    if patch.deleted_file or patch.new_path == "/dev/null":
        return "delete"
    if patch.rename_from or patch.rename_to:
        return "rename"
    if patch.old_path == "/dev/null" or patch.new_file or not operation.old_existed:
        return "create"
    if patch.old_mode is not None or patch.new_mode is not None:
        return "mode+modify" if patch.hunks else "mode"
    return "modify"


def _line_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _count_hunk_changes(operation: PlannedPatchOperation) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for hunk in operation.file_patch.hunks:
        for line in hunk.lines:
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1
    return additions, deletions


def _summarize_operation(operation: PlannedPatchOperation) -> PatchOperationSummary:
    additions, deletions = _count_hunk_changes(operation)
    mode_change = None
    if operation.before_mode is not None or operation.after_mode is not None:
        if operation.after_mode is not None and operation.before_mode != (
            operation.after_mode & 0o777
        ):
            mode_change = f"{oct(operation.before_mode) if operation.before_mode is not None else 'none'} -> {oct(operation.after_mode & 0o777)}"
    return PatchOperationSummary(
        operation=_operation_kind(operation),
        path=operation.rel_new or operation.rel_old or "<unknown>",
        old_path=operation.rel_old,
        new_path=operation.rel_new,
        hunks=len(operation.file_patch.hunks),
        old_lines=_line_count(operation.before_text),
        new_lines=_line_count(operation.after_text),
        additions=additions,
        deletions=deletions,
        mode_change=mode_change,
    )


def build_patch_plan_summary(
    root: Path, patch_text: str, *, fuzzy: bool = False
) -> PatchPlanSummary:
    """Build a machine-readable patch plan without writing files."""

    planned = _plan_patch(root, patch_text, fuzzy=fuzzy)
    files = tuple(_summarize_operation(operation) for operation in planned)
    warnings: list[str] = []
    total_additions = sum(item.additions for item in files)
    total_deletions = sum(item.deletions for item in files)
    if len(files) > 8:
        warnings.append("large patch touches more than 8 files; prefer smaller reviewable patches")
    if total_additions + total_deletions > 500:
        warnings.append("large patch changes more than 500 lines; verify with focused tests")
    if any(item.operation == "delete" for item in files):
        warnings.append("patch deletes files; ensure rollback/snapshot is available")
    return PatchPlanSummary(
        ok=True,
        files=files,
        total_files=len(files),
        total_hunks=sum(item.hunks for item in files),
        total_additions=total_additions,
        total_deletions=total_deletions,
        warnings=tuple(warnings),
    )


def render_patch_plan(
    root: Path, patch_text: str, *, fuzzy: bool = False, max_chars: int = 16000
) -> str:
    """Render a patch plan plus diff preview without writing."""

    planned = _plan_patch(root, patch_text, fuzzy=fuzzy)
    summary = build_patch_plan_summary(root, patch_text, fuzzy=fuzzy)
    preview = _render_plan_preview(planned, max_chars=max_chars)
    return truncate(
        "Patch plan JSON:\n" + summary.to_json() + "\n\nPreview:\n" + preview, max_chars
    )


def validate_unified_patch(
    root: Path, patch_text: str, *, fuzzy: bool = False, max_chars: int = 16000
) -> str:
    """Validate a patch and return a preview without writing."""

    return render_patch_plan(root, patch_text, fuzzy=fuzzy, max_chars=max_chars)


def _render_plan_preview(planned: list[PlannedPatchOperation], *, max_chars: int) -> str:
    outputs: list[str] = []
    for operation in planned:
        rel = operation.rel_new or operation.rel_old or "<unknown>"
        patch = operation.file_patch
        if patch.deleted_file or patch.new_path == "/dev/null":
            diff = unified_diff(
                operation.before_text, "", f"a/{rel}", "/dev/null", max_chars=max_chars
            )
            outputs.append(f"===== delete {rel} =====\n{diff}")
        elif patch.rename_from or patch.rename_to:
            header = f"rename {operation.rel_old} -> {operation.rel_new}"
            diff = unified_diff(
                operation.before_text,
                operation.after_text or "",
                f"a/{operation.rel_old}",
                f"b/{operation.rel_new}",
                max_chars=max_chars,
            )
            outputs.append(f"===== {header} =====\n{diff}")
        else:
            before = "" if not operation.old_existed else operation.before_text
            after = operation.after_text or ""
            diff = unified_diff(before, after, f"a/{rel}", f"b/{rel}", max_chars=max_chars)
            mode_note = ""
            if operation.after_mode is not None:
                mode_note = f"\nmode -> {oct(operation.after_mode)}"
            outputs.append(f"===== {rel} ====={mode_note}\n{diff}")
    return truncate("\n\n".join(outputs), max_chars)


def _rollback(
    rollback_records: list[tuple[Path, bool, str | None, int | None]], created_dirs: list[Path]
) -> None:
    for path, existed, content, mode in reversed(rollback_records):
        try:
            if existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_text(path, content or "")
                if mode is not None:
                    os.chmod(path, mode)
            elif path.exists():
                path.unlink()
        except OSError:
            # Continue best-effort rollback for the remaining files.
            pass
    for directory in reversed(created_dirs):
        try:
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            pass


def _record_state(
    path: Path | None, records: list[tuple[Path, bool, str | None, int | None]], seen: set[Path]
) -> None:
    if path is None or path in seen:
        return
    seen.add(path)
    if path.exists():
        content = _read_text(path)
        records.append((path, True, content, _mode(path)))
    else:
        records.append((path, False, None, None))


def _ensure_parent(path: Path, created_dirs: list[Path]) -> None:
    parent = path.parent
    missing: list[Path] = []
    cursor = parent
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    parent.mkdir(parents=True, exist_ok=True)
    created_dirs.extend(missing)


def _compile_python_text(path: str, text: str) -> str | None:
    try:
        ast.parse(text, filename=path)
    except SyntaxError as exc:
        return f"{path}:{exc.lineno}:{exc.offset}: Python syntax error: {exc.msg}"
    return None


def verify_planned_operations(
    root: Path,
    planned: list[PlannedPatchOperation],
    *,
    verify_python_syntax: bool = False,
) -> PatchVerification:
    """Verify that the workspace exactly matches the planned post-patch state."""

    errors: list[str] = []
    warnings: list[str] = []
    checked: list[str] = []

    for operation in planned:
        rel = operation.rel_new or operation.rel_old or "<unknown>"
        checked.append(rel)
        patch = operation.file_patch
        if patch.deleted_file or patch.new_path == "/dev/null":
            if operation.old_path is not None and operation.old_path.exists():
                errors.append(f"{rel}: expected deleted, but file still exists")
            continue

        if operation.new_path is None:
            errors.append(f"{rel}: verification missing target path")
            continue
        if not operation.new_path.exists():
            errors.append(f"{rel}: expected file to exist after patch")
            continue
        if operation.after_text is None:
            errors.append(f"{rel}: verification missing expected text")
            continue

        actual = _read_text(operation.new_path)
        if actual != operation.after_text:
            errors.append(f"{rel}: post-apply content does not match planned content")
        expected_mode = operation.file_patch.new_mode
        if expected_mode is not None:
            actual_mode = _mode(operation.new_path)
            if os.name == "nt":
                warnings.append(f"{rel}: executable permission bits are not enforceable on Windows")
            elif actual_mode != (expected_mode & 0o777):
                errors.append(
                    f"{rel}: mode {oct(actual_mode or 0)} != expected {oct(expected_mode & 0o777)}"
                )
        if verify_python_syntax and str(rel).endswith(".py"):
            syntax_error = _compile_python_text(str(rel), actual)
            if syntax_error:
                errors.append(syntax_error)

    if verify_python_syntax and not any(str(item).endswith(".py") for item in checked):
        warnings.append("Python syntax verification requested but no .py files were touched")

    return PatchVerification(
        ok=not errors,
        checked_files=tuple(dict.fromkeys(checked)),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _expected_added_deleted_lines(file_patch: FilePatch) -> tuple[list[str], list[str]]:
    added: list[str] = []
    deleted: list[str] = []
    for hunk in file_patch.hunks:
        for raw_line in hunk.lines:
            if raw_line.startswith("+"):
                added.append(raw_line[1:].rstrip("\r\n"))
            elif raw_line.startswith("-"):
                deleted.append(raw_line[1:].rstrip("\r\n"))
    return added, deleted


def _verify_patch_already_applied(
    root: Path, patch_text: str, *, verify_python_syntax: bool = False
) -> PatchVerification:
    """Best-effort verification for patches that no longer apply because they already landed."""

    errors: list[str] = []
    warnings: list[str] = [
        "Patch no longer applies cleanly; checked whether the desired state appears already present."
    ]
    checked: list[str] = []
    for file_patch in parse_unified_patch(patch_text):
        rel = file_patch.new_path if file_patch.new_path != "/dev/null" else file_patch.old_path
        rel = file_patch.rename_to or rel
        if not rel or rel == "/dev/null":
            continue
        checked.append(rel)
        path = _safe_patch_path(root, rel)
        if file_patch.deleted_file or file_patch.new_path == "/dev/null":
            if path is not None and path.exists():
                errors.append(f"{rel}: delete patch target still exists")
            continue
        if path is None or not path.exists():
            errors.append(f"{rel}: expected patched target to exist")
            continue
        text = _read_text(path)
        current_lines = {line.rstrip("\r\n") for line in text.splitlines(keepends=True)}
        added, deleted = _expected_added_deleted_lines(file_patch)
        missing_added = [line for line in added if line not in current_lines]
        still_deleted = [line for line in deleted if line in current_lines and line not in added]
        if missing_added:
            errors.append(f"{rel}: expected added lines missing: {missing_added[:3]}")
        if still_deleted:
            errors.append(f"{rel}: deleted lines still present: {still_deleted[:3]}")
        if verify_python_syntax and rel.endswith(".py"):
            syntax_error = _compile_python_text(rel, text)
            if syntax_error:
                errors.append(syntax_error)
    return PatchVerification(
        ok=not errors,
        checked_files=tuple(dict.fromkeys(checked)),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def verify_unified_patch(
    root: Path,
    patch_text: str,
    *,
    fuzzy: bool = False,
    verify_python_syntax: bool = False,
) -> str:
    """Verify a patch against the current workspace without writing.

    If the patch still applies, this reports whether the current workspace already
    matches the planned post-state. If it no longer applies, MiniCodex performs a
    conservative already-applied check based on added/deleted lines.
    """

    try:
        planned = _plan_patch(root, patch_text, fuzzy=fuzzy)
    except ValueError:
        verification = _verify_patch_already_applied(
            root, patch_text, verify_python_syntax=verify_python_syntax
        )
        return verification.render()
    verification = verify_planned_operations(
        root, planned, verify_python_syntax=verify_python_syntax
    )
    return verification.render()


def _apply_planned_operations(root: Path, planned: list[PlannedPatchOperation]) -> list[str]:
    written: list[str] = []
    rollback_records: list[tuple[Path, bool, str | None, int | None]] = []
    seen: set[Path] = set()
    created_dirs: list[Path] = []

    for operation in planned:
        _record_state(operation.old_path, rollback_records, seen)
        _record_state(operation.new_path, rollback_records, seen)

    try:
        for operation in planned:
            patch = operation.file_patch
            if patch.deleted_file or patch.new_path == "/dev/null":
                if operation.old_path is None:
                    raise ValueError("Delete operation missing old_path")
                backup = _backup_file_uuid(operation.old_path)
                operation.old_path.unlink()
                backup_msg = f"; yedek: {backup.relative_to(root)}" if backup else ""
                written.append(f"{operation.rel_old} silindi{backup_msg}")
                continue

            if patch.rename_from or patch.rename_to:
                if (
                    operation.old_path is None
                    or operation.new_path is None
                    or operation.after_text is None
                ):
                    raise ValueError("Rename operation incomplete")
                _ensure_parent(operation.new_path, created_dirs)
                backup = _backup_file_uuid(operation.old_path)
                if operation.old_path.resolve() != operation.new_path.resolve():
                    operation.old_path.rename(operation.new_path)
                _write_text(operation.new_path, operation.after_text)
                _chmod_from_git_mode(operation.new_path, operation.file_patch.new_mode)
                backup_msg = f"; yedek: {backup.relative_to(root)}" if backup else ""
                written.append(f"{operation.rel_old} -> {operation.rel_new} taşındı{backup_msg}")
                continue

            if operation.new_path is None or operation.after_text is None:
                raise ValueError("Write operation incomplete")
            _ensure_parent(operation.new_path, created_dirs)
            backup = _backup_file_uuid(operation.new_path)
            _write_text(operation.new_path, operation.after_text)
            _chmod_from_git_mode(operation.new_path, operation.file_patch.new_mode)
            if backup:
                written.append(f"{operation.rel_new} (yedek: {backup.relative_to(root)})")
            else:
                written.append(f"{operation.rel_new} (yeni dosya)")
    except Exception:
        _rollback(rollback_records, created_dirs)
        raise

    return written


def apply_unified_patch(
    root: Path,
    patch_text: str,
    dry_run: bool = False,
    max_chars: int = 16000,
    fuzzy: bool = False,
    verify: bool = True,
    verify_python_syntax: bool = False,
) -> str:
    """Apply a unified diff patch inside the workspace transactionally.

    The whole patch is parsed and validated before any filesystem mutation. When
    writing starts, all touched files are recorded for rollback. If any write,
    delete, rename, chmod, or directory operation fails, MiniCodex restores the
    pre-patch state on a best-effort basis. After a successful write, MiniCodex
    verifies that touched files exactly match the planned post-patch state.
    """

    try:
        planned = _plan_patch(root, patch_text, fuzzy=fuzzy)
    except ValueError as exc:
        return str(exc)

    plan = build_patch_plan_summary(root, patch_text, fuzzy=fuzzy)
    preview = _render_plan_preview(planned, max_chars=max_chars)
    plan_text = "Patch plan JSON:\n" + plan.to_json()
    if dry_run:
        return "DRY-RUN: patch uygulanmadı. Önizleme:\n\n" + truncate(
            plan_text + "\n\nPreview:\n" + preview, max_chars
        )

    try:
        written = _apply_planned_operations(root, planned)
    except Exception as exc:  # noqa: BLE001 - rollback path should surface concise failure
        return f"PATCH ROLLBACK: patch uygulanamadı ve rollback denendi. Hata: {type(exc).__name__}: {exc}"

    verification_text = ""
    if verify:
        verification = verify_planned_operations(
            root, planned, verify_python_syntax=verify_python_syntax
        )
        verification_text = "\n\n" + verification.render()
        if not verification.ok:
            _rollback(
                [
                    (op.old_path, op.old_existed, op.before_text, op.before_mode)
                    for op in planned
                    if op.old_path is not None
                ]
                + [
                    (op.new_path, op.new_existed, op.before_new_text, op.before_mode)
                    for op in planned
                    if op.new_path is not None and op.new_path != op.old_path
                ],
                [],
            )
            return (
                "PATCH VERIFY FAILED: patch uygulandı ama doğrulama başarısız oldu; rollback denendi.\n"
                + verification.render()
            )

    return (
        "Patch uygulandı transaction olarak:\n"
        + "\n".join(f"- {item}" for item in written)
        + verification_text
        + "\n\n"
        + truncate(plan_text + "\n\nDiff:\n" + preview, max_chars)
    )
