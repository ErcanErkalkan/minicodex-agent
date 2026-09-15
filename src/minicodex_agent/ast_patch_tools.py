"""AST-aware and formatter-aware refactor helpers.

These helpers complement the unified-diff patch engine.  They intentionally keep
optional heavy dependencies (libcst, rope, ts-morph, javalang, Tree-sitter)
optional, while providing dependency-free semantic edit operations that are safer
than raw text replacement:

* Python uses ``ast`` + ``tokenize`` validation.
* TypeScript/Java/Go/Rust use grammar-aware token masking so strings/comments are
  not edited accidentally.
* Import organization and dead-code cleanup are preview-first and syntax checked
  where a built-in parser exists.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import keyword
import re
import shutil
import subprocess
import tokenize
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from .fs_tools import backup_file, is_probably_binary, unified_diff
from .safety import safe_resolve, sensitive_path_reason, should_skip_path
from .semantic_index import SOURCE_EXTENSIONS, build_semantic_index
from .utils import to_pretty_json, truncate

LANGUAGE_EXTENSIONS: Mapping[str, tuple[str, ...]] = SOURCE_EXTENSIONS
_EXT_TO_LANGUAGE = {ext: lang for lang, exts in LANGUAGE_EXTENSIONS.items() for ext in exts}
_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


@dataclass(frozen=True)
class AstPatchCapability:
    """One AST/refactor backend capability."""

    name: str
    language: str
    available: bool
    backend: str
    detail: str = ""


@dataclass(frozen=True)
class SemanticEditPlan:
    """Previewable semantic edit plan."""

    ok: bool
    operation: str
    language: str
    files_considered: int
    files_to_change: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    recommended_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefactorFileChange:
    """One file diff produced by an AST-aware refactor helper."""

    path: str
    occurrences: int = 0
    diff: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefactorResult:
    """Serializable result for semantic refactor tools."""

    ok: bool
    operation: str
    mode: str
    changed_files: tuple[str, ...]
    total_occurrences: int = 0
    changes: tuple[RefactorFileChange, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def render(self, *, max_chars: int = 24000) -> str:
        return truncate(to_pretty_json(asdict(self)), max_chars)


@dataclass(frozen=True)
class DeadCodeCandidate:
    """A conservative dead-code candidate."""

    name: str
    kind: str
    language: str
    path: str
    line: int
    end_line: int | None = None
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class FormatVerifyResult:
    """Formatter/type/syntax verification result."""

    ok: bool
    path: str
    formatter: str
    command: tuple[str, ...] = ()
    formatter_ran: bool = False
    syntax_ok: bool | None = None
    diff: str = ""
    stdout: str = ""
    stderr: str = ""
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _language_for_path(path: Path | str) -> str:
    return _EXT_TO_LANGUAGE.get(Path(path).suffix.lower(), "")


def _safe_rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write_text(path: Path, text: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    backup_file(path)
    path.write_text(text, encoding="utf-8")


def _iter_source_files(
    root: Path, start_path: str, language: str = "", max_files: int = 400
) -> tuple[Path, ...]:
    target = safe_resolve(root, start_path or ".")
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {start_path}")
    if target.is_file():
        candidates: Iterable[Path] = (target,)
    else:
        candidates = sorted(target.rglob("*"))
    exts = LANGUAGE_EXTENSIONS.get(language, ()) if language else tuple(_EXT_TO_LANGUAGE)
    files: list[Path] = []
    for path in candidates:
        if len(files) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        if (
            should_skip_path(path, root)
            or sensitive_path_reason(path, root)
            or is_probably_binary(path)
        ):
            continue
        files.append(path)
    return tuple(files)


def _valid_identifier(name: str, *, language: str) -> bool:
    if language == "python":
        return name.isidentifier() and not keyword.iskeyword(name)
    return bool(_IDENTIFIER_RE.fullmatch(name))


def _python_rename_tokens(text: str, old_name: str, new_name: str) -> tuple[str, int]:
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    changed = 0
    updated: list[tokenize.TokenInfo] = []
    for token in tokens:
        if token.type == tokenize.NAME and token.string == old_name:
            token = tokenize.TokenInfo(token.type, new_name, token.start, token.end, token.line)
            changed += 1
        updated.append(token)
    return tokenize.untokenize(updated), changed


def _mask_non_code(text: str) -> list[bool]:
    """Return a mask where True means code can be edited.

    This lightweight scanner masks strings and comments for JS/TS/Java/Go/Rust.
    It is conservative rather than fully parsing every grammar.
    """

    mask = [True] * len(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            start = i
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            for j in range(start, i):
                mask[j] = False
            continue
        if ch == "/" and nxt == "*":
            start = i
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            for j in range(start, i):
                mask[j] = False
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            start = i
            i += 1
            escaped = False
            while i < n:
                cur = text[i]
                if escaped:
                    escaped = False
                elif cur == "\\":
                    escaped = True
                elif cur == quote:
                    i += 1
                    break
                i += 1
            for j in range(start, i):
                mask[j] = False
            continue
        i += 1
    return mask


def _masked_identifier_rename(text: str, old_name: str, new_name: str) -> tuple[str, int]:
    mask = _mask_non_code(text)
    pieces: list[str] = []
    last = 0
    changed = 0
    for match in re.finditer(rf"(?<![A-Za-z0-9_$]){re.escape(old_name)}(?![A-Za-z0-9_$])", text):
        if not all(mask[pos] for pos in range(match.start(), match.end())):
            continue
        pieces.append(text[last : match.start()])
        pieces.append(new_name)
        last = match.end()
        changed += 1
    if changed == 0:
        return text, 0
    pieces.append(text[last:])
    return "".join(pieces), changed


def _python_syntax_errors(text: str, rel: str) -> tuple[str, ...]:
    try:
        ast.parse(text, filename=rel)
        return ()
    except SyntaxError as exc:
        return (f"Python syntax error after edit in {rel}: {exc}",)


def ast_patch_capability_report(root: Path | None = None, *, max_chars: int = 24000) -> str:
    """Report AST/refactor capabilities and optional dependency availability."""

    capabilities = [
        AstPatchCapability(
            "python-ast", "python", True, "stdlib ast", "class/function syntax and validation"
        ),
        AstPatchCapability(
            "python-tokenize",
            "python",
            True,
            "stdlib tokenize",
            "identifier rename without editing comments/strings",
        ),
        AstPatchCapability(
            "libcst",
            "python",
            importlib.util.find_spec("libcst") is not None,
            "optional",
            "lossless Python CST refactors",
        ),
        AstPatchCapability(
            "rope",
            "python",
            importlib.util.find_spec("rope") is not None,
            "optional",
            "project-aware Python rename/refactor",
        ),
        AstPatchCapability(
            "typescript-grammar-aware",
            "typescript",
            True,
            "dependency-free",
            "masked token edits; strings/comments skipped",
        ),
        AstPatchCapability(
            "ts-morph",
            "typescript",
            False,
            "optional npm",
            "available when installed in project/tooling",
        ),
        AstPatchCapability(
            "java-grammar-aware",
            "java",
            True,
            "dependency-free",
            "import organization and masked token edits",
        ),
        AstPatchCapability(
            "javalang",
            "java",
            importlib.util.find_spec("javalang") is not None,
            "optional",
            "Java parser if installed",
        ),
        AstPatchCapability(
            "go-rust-grammar-aware",
            "go/rust",
            True,
            "dependency-free",
            "masked token edits and semantic index references",
        ),
        AstPatchCapability(
            "tree-sitter",
            "multi",
            importlib.util.find_spec("tree_sitter") is not None,
            "optional",
            "future parser backend; not required",
        ),
    ]
    formatters = {
        "black": bool(shutil.which("black")),
        "ruff": bool(shutil.which("ruff")),
        "prettier": bool(shutil.which("prettier")),
        "gofmt": bool(shutil.which("gofmt")),
        "rustfmt": bool(shutil.which("rustfmt")),
        "google-java-format": bool(shutil.which("google-java-format")),
    }
    payload = {
        "summary": "AST-aware patch/refactor capability report.",
        "capabilities": [asdict(item) for item in capabilities],
        "formatters": formatters,
        "notes": [
            "Python uses real stdlib AST validation by default.",
            "libcst/rope/ts-morph/javalang/tree-sitter remain optional so the package stays lightweight.",
            "Non-Python refactors use grammar-aware token masking plus semantic-index cross-file references.",
        ],
    }
    return truncate(to_pretty_json(payload), max_chars)


def plan_semantic_edit(
    root: Path,
    *,
    operation: str,
    path: str = ".",
    language: str = "",
    symbol: str = "",
    new_name: str = "",
    max_files: int = 400,
    max_chars: int = 24000,
) -> str:
    """Plan an AST-aware edit before applying it."""

    files = _iter_source_files(root, path, language=language, max_files=max_files)
    detected_languages = sorted(
        {
            language or _language_for_path(file)
            for file in files
            if (language or _language_for_path(file))
        }
    )
    warnings: list[str] = []
    errors: list[str] = []
    recommended = [
        "build_semantic_index",
        "find_symbol_references",
        "suggest_verification_commands",
    ]

    if operation in {"rename_symbol", "semantic_rename"}:
        if not symbol or not new_name:
            errors.append("rename_symbol requires symbol and new_name.")
        lang_for_validation = language or (
            detected_languages[0] if len(detected_languages) == 1 else "typescript"
        )
        if symbol and not _valid_identifier(symbol, language=lang_for_validation):
            errors.append(f"Invalid source identifier for {lang_for_validation}: {symbol}")
        if new_name and not _valid_identifier(new_name, language=lang_for_validation):
            errors.append(f"Invalid target identifier for {lang_for_validation}: {new_name}")
        recommended.insert(0, "rename_symbol_semantic")
    elif operation == "organize_imports":
        recommended.insert(0, "organize_imports")
    elif operation in {"detect_dead_code", "cleanup_dead_code"}:
        recommended.insert(0, "detect_dead_code")
        if operation == "cleanup_dead_code":
            recommended.insert(1, "cleanup_dead_code")
            warnings.append(
                "cleanup_dead_code is conservative and primarily supports Python top-level private symbols."
            )
    elif operation in {"format", "format_and_verify"}:
        recommended.insert(0, "format_and_verify")
    else:
        warnings.append(f"Unknown semantic operation {operation!r}; returning generic plan.")

    plan = SemanticEditPlan(
        ok=not errors,
        operation=operation,
        language=language or ",".join(detected_languages) or "unknown",
        files_considered=len(files),
        files_to_change=tuple(_safe_rel(root, file) for file in files[: min(50, len(files))]),
        warnings=tuple(warnings),
        errors=tuple(errors),
        recommended_tools=tuple(dict.fromkeys(recommended)),
    )
    return truncate(to_pretty_json(asdict(plan)), max_chars)


def rename_symbol_semantic(
    root: Path,
    *,
    old_name: str,
    new_name: str,
    language: str = "",
    path: str = ".",
    max_files: int = 400,
    preview_only: bool = True,
    dry_run: bool = False,
    max_chars: int = 30000,
) -> str:
    """Rename a symbol using AST/token-aware editing instead of raw replacement."""

    lang_for_validation = language or "typescript"
    if not _valid_identifier(old_name, language=lang_for_validation):
        return RefactorResult(
            False,
            "rename_symbol_semantic",
            "preview",
            (),
            errors=(f"Invalid source identifier: {old_name}",),
        ).render(max_chars=max_chars)
    if not _valid_identifier(new_name, language=lang_for_validation):
        return RefactorResult(
            False,
            "rename_symbol_semantic",
            "preview",
            (),
            errors=(f"Invalid target identifier: {new_name}",),
        ).render(max_chars=max_chars)
    if old_name == new_name:
        return RefactorResult(
            False,
            "rename_symbol_semantic",
            "preview",
            (),
            errors=("Source and target names are identical.",),
        ).render(max_chars=max_chars)

    changes: list[RefactorFileChange] = []
    errors: list[str] = []
    warnings: list[str] = []
    total = 0
    files = _iter_source_files(root, path, language=language, max_files=max_files)
    for file in files:
        rel = _safe_rel(root, file)
        lang = language or _language_for_path(file)
        try:
            old_text = _read_text(file)
        except OSError as exc:
            warnings.append(f"Could not read {rel}: {exc}")
            continue
        try:
            if lang == "python":
                new_text, count = _python_rename_tokens(old_text, old_name, new_name)
                syntax_errors = _python_syntax_errors(new_text, rel) if count else ()
            else:
                new_text, count = _masked_identifier_rename(old_text, old_name, new_name)
                syntax_errors = ()
        except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
            warnings.append(f"Could not tokenize {rel}: {exc}")
            continue
        if count == 0:
            continue
        total += count
        diff = unified_diff(old_text, new_text, f"a/{rel}", f"b/{rel}")
        changes.append(RefactorFileChange(rel, count, diff, syntax_errors))
        if syntax_errors:
            errors.extend(syntax_errors)
            continue
        if not preview_only and not dry_run:
            _write_text(file, new_text, dry_run=False)

    if not changes:
        return RefactorResult(
            False,
            "rename_symbol_semantic",
            "preview",
            (),
            errors=(f"Symbol not found: {old_name}",),
        ).render(max_chars=max_chars)
    mode = "preview" if preview_only or dry_run else "applied"
    result = RefactorResult(
        ok=not errors,
        operation="rename_symbol_semantic",
        mode=mode,
        changed_files=tuple(change.path for change in changes),
        total_occurrences=total,
        changes=tuple(changes),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return result.render(max_chars=max_chars)


def _split_python_header(text: str) -> tuple[str, list[str], str]:
    """Return prefix, import lines, suffix for a top-level Python import block."""

    lines = text.splitlines(keepends=True)
    i = 0
    prefix: list[str] = []
    # Preserve shebang, coding cookie, blank/comment lines before module imports.
    while i < len(lines):
        stripped = lines[i].strip()
        if i < 2 and (stripped.startswith("#!") or "coding" in stripped):
            prefix.append(lines[i])
            i += 1
            continue
        if stripped == "" or stripped.startswith("#"):
            prefix.append(lines[i])
            i += 1
            continue
        break
    # Preserve module docstring if present.
    joined = "".join(lines[i:])
    try:
        module = ast.parse(joined)
        first = module.body[0] if module.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            end = getattr(first, "end_lineno", None)
            if end:
                prefix.extend(lines[i : i + end])
                i += end
                while i < len(lines) and lines[i].strip() == "":
                    prefix.append(lines[i])
                    i += 1
    except SyntaxError:
        pass
    imports: list[str] = []
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(lines[i])
            i += 1
            continue
        if stripped == "" and imports:
            imports.append(lines[i])
            i += 1
            continue
        break
    return "".join(prefix), imports, "".join(lines[i:])


def _organize_python_imports(text: str) -> tuple[str, bool]:
    prefix, imports, suffix = _split_python_header(text)
    import_lines = [line for line in imports if line.strip()]
    if not import_lines:
        return text, False
    grouped = sorted(
        set(import_lines),
        key=lambda value: (0 if value.lstrip().startswith("import ") else 1, value.lower()),
    )
    block = "".join(grouped)
    if suffix and not block.endswith("\n\n"):
        block = block.rstrip("\n") + "\n\n"
    new_text = prefix + block + suffix.lstrip("\n")
    return new_text, new_text != text


def _organize_line_imports(text: str, *, import_prefixes: tuple[str, ...]) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    imports: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if line.lstrip().startswith(import_prefixes):
            imports.append((idx, line))
    if len(imports) < 2:
        return text, False
    sorted_lines = sorted({line for _, line in imports}, key=lambda value: value.lower())
    first = imports[0][0]
    last = imports[-1][0]
    if [idx for idx, _ in imports] != list(range(first, last + 1)):
        # Do not move imports across executable code in this conservative mode.
        return text, False
    new_lines = lines[:first] + sorted_lines + lines[last + 1 :]
    new_text = "".join(new_lines)
    return new_text, new_text != text


def organize_imports(
    root: Path,
    *,
    path: str = ".",
    language: str = "",
    max_files: int = 400,
    preview_only: bool = True,
    dry_run: bool = False,
    max_chars: int = 30000,
) -> str:
    """Organize imports for Python/TS/Java/Go/Rust source files."""

    changes: list[RefactorFileChange] = []
    warnings: list[str] = []
    errors: list[str] = []
    files = _iter_source_files(root, path, language=language, max_files=max_files)
    for file in files:
        lang = language or _language_for_path(file)
        rel = _safe_rel(root, file)
        old_text = _read_text(file)
        if lang == "python":
            new_text, changed = _organize_python_imports(old_text)
            syntax_errors = _python_syntax_errors(new_text, rel) if changed else ()
        elif lang in {"typescript", "javascript"}:
            new_text, changed = _organize_line_imports(
                old_text, import_prefixes=("import ", "export ")
            )
            syntax_errors = ()
        elif lang == "java":
            new_text, changed = _organize_line_imports(old_text, import_prefixes=("import ",))
            syntax_errors = ()
        elif lang in {"go", "rust"}:
            new_text, changed = _organize_line_imports(
                old_text, import_prefixes=("use ", "import ")
            )
            syntax_errors = ()
        else:
            continue
        if not changed:
            continue
        diff = unified_diff(old_text, new_text, f"a/{rel}", f"b/{rel}")
        changes.append(RefactorFileChange(rel, 1, diff, syntax_errors))
        if syntax_errors:
            errors.extend(syntax_errors)
            continue
        if not preview_only and not dry_run:
            _write_text(file, new_text, dry_run=False)
    if not changes:
        return RefactorResult(
            False, "organize_imports", "preview", (), warnings=("No import changes found.",)
        ).render(max_chars=max_chars)
    mode = "preview" if preview_only or dry_run else "applied"
    return RefactorResult(
        ok=not errors,
        operation="organize_imports",
        mode=mode,
        changed_files=tuple(change.path for change in changes),
        total_occurrences=len(changes),
        changes=tuple(changes),
        warnings=tuple(warnings),
        errors=tuple(errors),
    ).render(max_chars=max_chars)


def detect_dead_code(
    root: Path,
    *,
    language: str = "python",
    path: str = ".",
    include_public: bool = False,
    max_files: int = 600,
    max_candidates: int = 80,
    max_chars: int = 24000,
) -> str:
    """Detect conservative dead-code candidates using semantic definitions/references."""

    index = build_semantic_index(
        root,
        max_files=max_files,
        max_symbols=4000,
        max_references_per_symbol=50,
        include_routes=False,
    )
    candidates: list[DeadCodeCandidate] = []
    symbol_ref_count: dict[tuple[str, str], int] = {}
    for ref in index.references:
        if language and ref.language != language:
            continue
        symbol_ref_count[(ref.path, ref.symbol)] = symbol_ref_count.get(
            (ref.path, ref.symbol), 0
        ) + (0 if ref.is_definition else 1)
    for symbol in index.symbols:
        if language and symbol.language != language:
            continue
        if (
            path not in {"", "."}
            and not symbol.path.startswith(path.rstrip("/") + "/")
            and symbol.path != path
        ):
            continue
        if symbol.kind not in {"function", "class", "method", "component", "type"}:
            continue
        if not include_public and not symbol.name.startswith("_"):
            continue
        if symbol.name.startswith("__") and symbol.name.endswith("__"):
            continue
        refs = symbol_ref_count.get((symbol.path, symbol.name), 0)
        if refs == 0:
            candidates.append(
                DeadCodeCandidate(
                    name=symbol.name,
                    kind=symbol.kind,
                    language=symbol.language,
                    path=symbol.path,
                    line=symbol.line,
                    end_line=symbol.end_line,
                    confidence=0.82 if symbol.language == "python" else 0.62,
                    reason="No cross-file/in-file references found in semantic index; candidate is conservative, review before removal.",
                )
            )
        if len(candidates) >= max_candidates:
            break
    payload = {
        "summary": f"Found {len(candidates)} conservative dead-code candidate(s).",
        "language": language,
        "include_public": include_public,
        "candidates": [asdict(item) for item in candidates],
        "warnings": [
            "Dead-code detection is static and conservative; dynamic imports/reflection/plugins may hide references.",
            "cleanup_dead_code only auto-removes Python candidates with exact AST line spans.",
        ],
    }
    return truncate(to_pretty_json(payload), max_chars)


def _remove_python_line_spans(text: str, spans: list[tuple[int, int]]) -> str:
    lines = text.splitlines(keepends=True)
    remove: set[int] = set()
    for start, end in spans:
        if start < 1 or end < start:
            continue
        # Include leading decorators.
        s = start
        while s > 1 and lines[s - 2].lstrip().startswith("@"):
            s -= 1
        for idx in range(s, end + 1):
            remove.add(idx)
    return "".join(line for idx, line in enumerate(lines, start=1) if idx not in remove)


def cleanup_dead_code(
    root: Path,
    *,
    names: tuple[str, ...] = (),
    path: str = ".",
    include_public: bool = False,
    max_files: int = 600,
    preview_only: bool = True,
    dry_run: bool = False,
    max_chars: int = 30000,
) -> str:
    """Remove conservative Python top-level dead-code candidates."""

    index = build_semantic_index(
        root,
        max_files=max_files,
        max_symbols=4000,
        max_references_per_symbol=50,
        include_routes=False,
    )
    ref_counts: dict[tuple[str, str], int] = {}
    for ref in index.references:
        if ref.language == "python" and not ref.is_definition:
            ref_counts[(ref.path, ref.symbol)] = ref_counts.get((ref.path, ref.symbol), 0) + 1
    spans_by_file: dict[str, list[tuple[int, int, str]]] = {}
    wanted = set(names)
    for symbol in index.symbols:
        if symbol.language != "python" or symbol.kind not in {"function", "class"}:
            continue
        if (
            path not in {"", "."}
            and not symbol.path.startswith(path.rstrip("/") + "/")
            and symbol.path != path
        ):
            continue
        if wanted and symbol.name not in wanted:
            continue
        if not wanted and not include_public and not symbol.name.startswith("_"):
            continue
        if symbol.name.startswith("__") and symbol.name.endswith("__"):
            continue
        if ref_counts.get((symbol.path, symbol.name), 0) != 0:
            continue
        if not symbol.end_line:
            continue
        spans_by_file.setdefault(symbol.path, []).append(
            (symbol.line, symbol.end_line, symbol.name)
        )
    changes: list[RefactorFileChange] = []
    errors: list[str] = []
    for rel, spans in spans_by_file.items():
        file = safe_resolve(root, rel)
        old_text = _read_text(file)
        new_text = _remove_python_line_spans(old_text, [(s, e) for s, e, _ in spans])
        if new_text == old_text:
            continue
        syntax_errors = _python_syntax_errors(new_text, rel)
        diff = unified_diff(old_text, new_text, f"a/{rel}", f"b/{rel}")
        changes.append(RefactorFileChange(rel, len(spans), diff, syntax_errors))
        if syntax_errors:
            errors.extend(syntax_errors)
            continue
        if not preview_only and not dry_run:
            _write_text(file, new_text, dry_run=False)
    if not changes:
        return RefactorResult(
            False,
            "cleanup_dead_code",
            "preview",
            (),
            warnings=("No removable Python dead-code candidates found.",),
        ).render(max_chars=max_chars)
    mode = "preview" if preview_only or dry_run else "applied"
    return RefactorResult(
        ok=not errors,
        operation="cleanup_dead_code",
        mode=mode,
        changed_files=tuple(change.path for change in changes),
        total_occurrences=sum(change.occurrences for change in changes),
        changes=tuple(changes),
        warnings=(
            "Review static dead-code cleanup before applying to dynamic/plugin-heavy projects.",
        ),
        errors=tuple(errors),
    ).render(max_chars=max_chars)


def _formatter_command(path: Path, formatter: str) -> tuple[str, ...]:
    suffix = path.suffix.lower()
    if formatter == "auto":
        if suffix in {".py", ".pyi"}:
            if shutil.which("ruff"):
                return ("ruff", "format", str(path))
            if shutil.which("black"):
                return ("black", str(path))
            return ()
        if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"} and shutil.which("prettier"):
            return ("prettier", "--write", str(path))
        if suffix == ".go" and shutil.which("gofmt"):
            return ("gofmt", "-w", str(path))
        if suffix == ".rs" and shutil.which("rustfmt"):
            return ("rustfmt", str(path))
        if suffix == ".java" and shutil.which("google-java-format"):
            return ("google-java-format", "-i", str(path))
        return ()
    explicit = {
        "ruff": ("ruff", "format", str(path)),
        "black": ("black", str(path)),
        "prettier": ("prettier", "--write", str(path)),
        "gofmt": ("gofmt", "-w", str(path)),
        "rustfmt": ("rustfmt", str(path)),
        "google-java-format": ("google-java-format", "-i", str(path)),
    }
    cmd = explicit.get(formatter, ())
    return cmd if cmd and shutil.which(cmd[0]) else ()


def format_and_verify(
    root: Path,
    *,
    path: str,
    formatter: str = "auto",
    run_formatter: bool = False,
    verify_syntax: bool = True,
    timeout: int = 60,
    dry_run: bool = False,
    max_chars: int = 24000,
) -> str:
    """Run formatter when requested and verify resulting diff/syntax."""

    target = safe_resolve(root, path)
    if not target.exists() or not target.is_file():
        result = FormatVerifyResult(False, path, formatter, errors=(f"File not found: {path}",))
        return truncate(to_pretty_json(asdict(result)), max_chars)
    if sensitive_path_reason(target, root) or should_skip_path(target, root):
        result = FormatVerifyResult(
            False, path, formatter, errors=(f"Refusing to format protected path: {path}",)
        )
        return truncate(to_pretty_json(asdict(result)), max_chars)
    before = _read_text(target)
    syntax_ok: bool | None = None
    warnings: list[str] = []
    errors: list[str] = []
    stdout = ""
    stderr = ""
    cmd = _formatter_command(target, formatter)
    formatter_ran = False
    if run_formatter and cmd and not dry_run:
        proc = subprocess.run(
            cmd,
            cwd=root,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        formatter_ran = True
        stdout = truncate(proc.stdout, 4000)
        stderr = truncate(proc.stderr, 4000)
        if proc.returncode != 0:
            errors.append(f"Formatter exited with code {proc.returncode}: {' '.join(cmd)}")
    elif run_formatter and not cmd:
        warnings.append(
            f"Formatter {formatter!r} is not available for {path}; no formatter was run."
        )
    elif dry_run or not run_formatter:
        warnings.append("Formatter not run; this is a plan/verification-only result.")
    after = _read_text(target)
    diff = unified_diff(before, after, f"a/{path}", f"b/{path}") if before != after else ""
    if verify_syntax and target.suffix.lower() in {".py", ".pyi"}:
        syntax_errors = _python_syntax_errors(after, path)
        syntax_ok = not syntax_errors
        errors.extend(syntax_errors)
    result = FormatVerifyResult(
        ok=not errors,
        path=path,
        formatter=formatter,
        command=cmd,
        formatter_ran=formatter_ran,
        syntax_ok=syntax_ok,
        diff=diff,
        stdout=stdout,
        stderr=stderr,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return truncate(to_pretty_json(asdict(result)), max_chars)
