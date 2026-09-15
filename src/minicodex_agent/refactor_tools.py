"""Safe Python refactor helpers."""

from __future__ import annotations

import io
import keyword
import tokenize
from dataclasses import dataclass
from pathlib import Path

from .fs_tools import backup_file, is_probably_binary, unified_diff
from .safety import safe_resolve, should_skip_path
from .utils import truncate


@dataclass(frozen=True)
class RenameChange:
    """A file changed by a token-based rename."""

    path: str
    occurrences: int
    diff: str


def _is_valid_identifier(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name)


def _python_files(root: Path, start_path: str, max_files: int) -> list[Path]:
    target = safe_resolve(root, start_path)
    if not target.exists():
        raise FileNotFoundError(f"Path bulunamadı: {start_path}")
    candidates = [target] if target.is_file() else sorted(target.rglob("*.py"))
    files: list[Path] = []
    for path in candidates:
        if len(files) >= max_files:
            break
        if path.is_file() and path.suffix == ".py" and not should_skip_path(path, root):
            files.append(path)
    return files


def _rename_tokens(text: str, old_name: str, new_name: str) -> tuple[str, int]:
    reader = io.StringIO(text).readline
    tokens = list(tokenize.generate_tokens(reader))
    changed = 0
    updated_tokens: list[tokenize.TokenInfo] = []

    for token in tokens:
        if token.type == tokenize.NAME and token.string == old_name:
            token = tokenize.TokenInfo(token.type, new_name, token.start, token.end, token.line)
            changed += 1
        updated_tokens.append(token)

    return tokenize.untokenize(updated_tokens), changed


def rename_python_symbol(
    root: Path,
    old_name: str,
    new_name: str,
    start_path: str = ".",
    max_files: int = 200,
    preview_only: bool = False,
    dry_run: bool = False,
    max_chars: int = 20000,
) -> str:
    """Rename a Python identifier across visible .py files using tokenize.

    This intentionally avoids changing comments and strings. It is safer than a
    raw text replacement, but it is not a full type-aware refactor. The result
    should still be reviewed with git diff and tests.
    """

    if not _is_valid_identifier(old_name):
        return f"Geçersiz eski Python identifier: {old_name}"
    if not _is_valid_identifier(new_name):
        return f"Geçersiz yeni Python identifier: {new_name}"
    if old_name == new_name:
        return "Eski ve yeni sembol aynı; değişiklik yapılmadı."

    changes: list[RenameChange] = []
    for path in _python_files(root, start_path, max_files):
        if is_probably_binary(path):
            continue
        try:
            old_text = path.read_text(encoding="utf-8", errors="replace")
            new_text, occurrences = _rename_tokens(old_text, old_name, new_name)
        except (OSError, tokenize.TokenError) as exc:
            rel_path = path.relative_to(root)
            changes.append(RenameChange(str(rel_path), 0, f"Tokenize hatası: {exc}"))
            continue
        if occurrences == 0:
            continue
        rel = str(path.relative_to(root))
        diff = unified_diff(old_text, new_text, f"a/{rel}", f"b/{rel}")
        changes.append(RenameChange(rel, occurrences, diff))
        if not preview_only and not dry_run:
            backup_file(path)
            path.write_text(new_text, encoding="utf-8")

    if not changes:
        return f"Python sembolü bulunamadı: {old_name}"

    mode = "ÖNİZLEME" if preview_only or dry_run else "UYGULANDI"
    total = sum(change.occurrences for change in changes)
    rows = [
        f"Python rename {mode}: {old_name} -> {new_name}",
        f"Etkilenen dosya: {len([c for c in changes if c.occurrences > 0])}",
        f"Toplam token değişimi: {total}",
        "",
    ]
    for change in changes:
        rows.append(f"## {change.path} ({change.occurrences} occurrence)")
        rows.append(change.diff)
        rows.append("")
    if not preview_only and not dry_run:
        rows.append("Not: Değişen dosyalar için timestamp'li .bak yedekleri oluşturuldu.")
    else:
        rows.append("Not: Dosya değiştirilmedi; bu sadece önizlemedir.")
    return truncate("\n".join(rows).rstrip(), max_chars)
