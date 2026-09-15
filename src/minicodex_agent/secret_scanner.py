"""Secret scanning helpers for MiniCodex.

This scanner is intentionally lightweight and dependency-free. It is designed
as a pre-flight safety net before the agent prints diffs, prepares commits, or
builds PR/issue text. It does not replace dedicated tools such as gitleaks or
trufflehog, but it catches common high-risk patterns in local workspaces while
trying to avoid noisy findings from examples, placeholders, and normal code.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .fs_tools import is_probably_binary
from .safety import safe_resolve, should_skip_path
from .utils import truncate

DEFAULT_MAX_FILES = 1000
DEFAULT_MAX_BYTES_PER_FILE = 600_000
Severity = Literal["low", "medium", "high", "critical"]

SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


@dataclass(frozen=True)
class SecretFinding:
    """One possible secret occurrence."""

    path: str
    line: int
    rule: str
    severity: Severity
    preview: str


@dataclass(frozen=True)
class SecretPattern:
    """A direct regex-based secret rule."""

    rule: str
    pattern: re.Pattern[str]
    severity: Severity


SECRET_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern(
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----"),
        "critical",
    ),
    SecretPattern(
        "openai_api_key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{20,}\b"), "critical"
    ),
    SecretPattern("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"), "critical"),
    SecretPattern("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "critical"),
    SecretPattern("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "critical"),
    SecretPattern("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{20,}\b"), "critical"),
)

SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|[_.\-])(?:api[_-]?key|secret|token|password|passwd|pwd|client[_-]?secret|auth)(?:$|[_.\-])"
)
ASSIGNMENT_RE = re.compile(
    r"^\s*[\"']?(?P<key>[A-Za-z_][A-Za-z0-9_.\-]*)[\"']?\s*(?:=|:|:=)\s*(?P<value>.+?)\s*,?\s*(?:#.*)?$"
)
PLACEHOLDER_RE = re.compile(
    r"(?ix)"
    r"^(?:"
    r"$|"
    r"none|null|nil|false|true|"
    r"your[_\- ]?(?:api[_\- ]?)?key(?:[_\- ]?here)?|"
    r"your[_\- ]?token(?:[_\- ]?here)?|"
    r"your[_\- ]?secret(?:[_\- ]?here)?|"
    r"example(?:[_\- ]?(?:key|token|secret|password))?|"
    r"dummy(?:[_\- ]?(?:key|token|secret|password))?|"
    r"sample(?:[_\- ]?(?:key|token|secret|password))?|"
    r"placeholder|replace[_\- ]?me|changeme|change[_\- ]?me|"
    r"insert[_\- ]?(?:key|token|secret|password)(?:[_\- ]?here)?|"
    r"todo|tbd|test|testing|"
    r"x{6,}|\*{6,}|<[^>]+>|\$\{[^}]+\}|%[^%]+%"
    r")$"
)
CODE_CONTEXT_RE = re.compile(
    r"^\s*(?:from\s+\S+\s+import|import\s+|def\s+|class\s+|return\s+|if\s+|elif\s+|for\s+|while\s+|with\s+|assert\s+)"
)
TOML_SECTION_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
TOKEN_RE = re.compile(r"[A-Za-z0-9_\-+/=.]{24,}")
TYPE_ANNOTATION_PREFIXES = (
    "tuple[",
    "dict[",
    "list[",
    "set[",
    "frozenset[",
    "str",
    "bool",
    "int",
    "float",
    "Path",
    "Literal[",
)
EXAMPLE_PATH_PARTS = {"tests", "test", "examples", "example", "docs", "doc"}
SECURITY_FIXTURE_MARKERS = (
    "minicodex-security-test-fixture",
    "minicodex-security-ignore",
)
SECURITY_TEST_FIXTURE_PARTS = ("tests", "fixtures", "unsafe_examples")


def _is_security_test_fixture_file(path: Path, root: Path) -> bool:
    """Return True for intentionally unsafe test fixture files."""

    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    parts = tuple(part.lower() for part in rel.parts)
    if (
        len(parts) >= len(SECURITY_TEST_FIXTURE_PARTS)
        and parts[: len(SECURITY_TEST_FIXTURE_PARTS)] == SECURITY_TEST_FIXTURE_PARTS
    ):
        return True
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2048].lower()
    except OSError:
        return False
    return any(marker in head for marker in SECURITY_FIXTURE_MARKERS)


def _line_has_security_fixture_marker(line: str) -> bool:
    """Return True when a line intentionally contains fake secret fixture text."""

    lowered = line.lower()
    return any(marker in lowered for marker in SECURITY_FIXTURE_MARKERS)


@dataclass(frozen=True)
class AssignmentContext:
    """Parsed assignment-like source line."""

    key: str
    value: str
    normalized_value: str
    is_sensitive_key: bool


def _entropy(value: str) -> float:
    """Return Shannon entropy for one string."""

    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def _strip_inline_comment(value: str) -> str:
    """Remove common inline comments without trying to fully parse every language."""

    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return value[:index]
        if char == "/" and not in_single and not in_double and value[index : index + 2] == "//":
            return value[:index]
    return value


def _normalize_assignment_value(value: str) -> str:
    """Normalize an assignment RHS for placeholder and entropy checks."""

    cleaned = _strip_inline_comment(value).strip().rstrip(",;")
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def _is_placeholder_value(value: str) -> bool:
    """Return True when a value is clearly documentation/example placeholder text."""

    normalized = value.strip().strip("'\"").strip()
    if PLACEHOLDER_RE.fullmatch(normalized):
        return True
    lowered = normalized.lower()
    if any(
        word in lowered
        for word in ("your_", "replace", "placeholder", "example", "dummy", "sample")
    ):
        return True
    if normalized.startswith(
        ("os.getenv(", "getenv(", "process.env.", "settings.", "config.", "self.", "state.")
    ):
        return True
    if re.fullmatch(r"[A-Z0-9_]+", normalized) and any(
        marker in normalized for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")
    ):
        return True
    return False


def _is_sensitive_key_name(key: str) -> bool:
    """Return True for keys that are likely to directly store a secret value."""

    normalized = key.strip("'\"").lower().replace("-", "_").replace(".", "_")
    if normalized.startswith(("not_a_", "no_", "has_")):
        return False
    if normalized.startswith(("secret_scan", "secrets_scan", "scan_secret")):
        return False
    if normalized in {"requires_api_key", "needs_api_key", "has_api_key"}:
        return False
    return bool(SENSITIVE_KEY_RE.search(normalized))


def _line_is_noise_context(line: str) -> bool:
    """Skip obvious code/metadata contexts that are not value assignments."""

    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "//", "*")):
        return True
    if TOML_SECTION_RE.match(stripped):
        return True
    if CODE_CONTEXT_RE.match(stripped):
        return True
    return False


def _parse_assignment_context(line: str) -> AssignmentContext | None:
    """Extract a simple key/value assignment if the line looks like one."""

    if _line_is_noise_context(line):
        return None
    match = ASSIGNMENT_RE.match(line)
    if not match:
        return None
    key = match.group("key")
    raw_value = match.group("value")
    normalized_value = _normalize_assignment_value(raw_value)
    if not normalized_value:
        return None
    # Values that are obviously expressions, object literals, references, or function calls are not raw secrets.
    if normalized_value.startswith(("{", "[", "(", "lambda ")):
        return None
    if normalized_value.startswith(TYPE_ANNOTATION_PREFIXES):
        return None
    if re.match(r"^[A-Za-z_][A-Za-z0-9_\.]*\(.*\)$", normalized_value):
        return None
    if re.match(r"^(?:self|state|config|settings|project_profile)\.", normalized_value):
        return None
    return AssignmentContext(
        key=key,
        value=raw_value,
        normalized_value=normalized_value,
        is_sensitive_key=_is_sensitive_key_name(key),
    )


def _looks_like_high_entropy_token(value: str) -> bool:
    """Heuristic for long random-looking tokens."""

    if len(value) < 24 or len(value) > 200:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_\-+/=.]+", value):
        return False
    if _is_placeholder_value(value):
        return False
    # Require mixed character classes so normal identifiers and words do not trigger.
    classes = sum(
        bool(re.search(pattern, value)) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[_\-+/=]")
    )
    if classes < 3:
        return False
    return _entropy(value) >= 3.7


def _sensitive_assignment_severity(context: AssignmentContext) -> Severity | None:
    """Classify a sensitive-looking assignment, or suppress placeholders/examples."""

    value = context.normalized_value
    if not context.is_sensitive_key:
        return None
    if value in {"bool", "str", "int", "float", "Path", "None", "True", "False"}:
        return None
    if _is_placeholder_value(value):
        return None
    # Environment variable names and references should not be treated as stored secrets.
    if re.fullmatch(r"[A-Z][A-Z0-9_]{5,}", value):
        return None
    if len(value) < 8:
        return "low"
    if _looks_like_high_entropy_token(value):
        return "high"
    # Literal passwords/secrets under sensitive keys are still worth review, but lower confidence than provider tokens.
    return "medium"


def _mask_secret_value(value: str, *, keep_start: int = 4, keep_end: int = 4) -> str:
    """Mask one secret-like value without losing all debugging context."""

    if len(value) <= keep_start + keep_end:
        return "*" * len(value)
    return value[:keep_start] + "…REDACTED…" + value[-keep_end:]


def redact_secret(text: str, *, keep_start: int = 4, keep_end: int = 4) -> str:
    """Redact likely secret material while keeping enough context for review.

    Redaction is applied line-by-line for assignment-style secrets so multi-line
    command output, observations, logs, and diffs do not leak values such as
    ``PASSWORD=...`` that are embedded in otherwise ordinary text.
    """

    def replace_match(match: re.Match[str]) -> str:
        return _mask_secret_value(match.group(0), keep_start=keep_start, keep_end=keep_end)

    def redact_line(line: str) -> str:
        redacted_line = line
        for secret_pattern in SECRET_PATTERNS:
            redacted_line = secret_pattern.pattern.sub(replace_match, redacted_line)

        context = _parse_assignment_context(redacted_line)
        if context is None:
            return redacted_line

        value = context.normalized_value
        if context.is_sensitive_key and not _is_placeholder_value(value) and len(value) >= 8:
            redacted_value = _mask_secret_value(value, keep_start=keep_start, keep_end=keep_end)
            return redacted_line.replace(value, redacted_value, 1)

        for token in TOKEN_RE.findall(context.value):
            if _looks_like_high_entropy_token(token):
                redacted_line = redacted_line.replace(
                    token,
                    _mask_secret_value(token, keep_start=keep_start, keep_end=keep_end),
                    1,
                )
        return redacted_line

    return "".join(redact_line(line) for line in text.splitlines(keepends=True))


def _iter_candidate_files(root: Path, start_path: str, max_files: int) -> Iterable[Path]:
    target = safe_resolve(root, start_path)
    yielded = 0
    if target.is_file():
        yield target
        return
    if not target.exists():
        return
    for path in sorted(target.rglob("*")):
        if yielded >= max_files:
            break
        if not path.is_file() or should_skip_path(path, root, allow_sensitive=True):
            continue
        if _is_security_test_fixture_file(path, root):
            continue
        yielded += 1
        yield path


def _finding_allowed(severity: Severity, minimum_severity: Severity) -> bool:
    return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[minimum_severity]


def _downgrade_contextual_severity(rel: str, rule: str, severity: Severity) -> Severity:
    """Lower confidence for generic test/example fixtures while preserving direct token rules."""

    if rule not in {"sensitive_assignment", "high_entropy_token"}:
        return severity
    parts = {part.lower() for part in Path(rel).parts}
    if parts & EXAMPLE_PATH_PARTS and SEVERITY_ORDER[severity] > SEVERITY_ORDER["medium"]:
        return "medium"
    return severity


def _scan_line(
    rel: str, line_number: int, line: str, minimum_severity: Severity
) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    direct_rule_seen = False

    if _line_has_security_fixture_marker(line):
        return findings

    for secret_pattern in SECRET_PATTERNS:
        if secret_pattern.pattern.search(line):
            direct_rule_seen = True
            if _finding_allowed(secret_pattern.severity, minimum_severity):
                findings.append(
                    SecretFinding(
                        path=rel,
                        line=line_number,
                        rule=secret_pattern.rule,
                        severity=secret_pattern.severity,
                        preview=truncate(redact_secret(line.strip()), 300),
                    )
                )

    context = _parse_assignment_context(line)
    if context is None:
        return findings

    assignment_severity = _sensitive_assignment_severity(context)
    if assignment_severity is not None:
        assignment_severity = _downgrade_contextual_severity(
            rel, "sensitive_assignment", assignment_severity
        )
    if assignment_severity is not None and _finding_allowed(assignment_severity, minimum_severity):
        findings.append(
            SecretFinding(
                path=rel,
                line=line_number,
                rule="sensitive_assignment",
                severity=assignment_severity,
                preview=truncate(redact_secret(line.strip()), 300),
            )
        )

    # High-entropy token checks are intentionally limited to assignment/value context.
    # This avoids false positives in Python attributes, TOML headings, imports, and normal code symbols.
    if direct_rule_seen:
        return findings
    for token in TOKEN_RE.findall(context.normalized_value):
        if _looks_like_high_entropy_token(token):
            severity: Severity = "high" if context.is_sensitive_key else "medium"
            severity = _downgrade_contextual_severity(rel, "high_entropy_token", severity)
            if _finding_allowed(severity, minimum_severity):
                findings.append(
                    SecretFinding(
                        path=rel,
                        line=line_number,
                        rule="high_entropy_token",
                        severity=severity,
                        preview=truncate(redact_secret(line.strip()), 300),
                    )
                )
    return findings


def scan_secret_findings(
    root: Path,
    *,
    start_path: str = ".",
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes_per_file: int = DEFAULT_MAX_BYTES_PER_FILE,
    max_findings: int = 100,
    minimum_severity: Severity = "low",
) -> tuple[list[SecretFinding], int, int]:
    """Return raw secret findings plus scanned/skipped counts."""

    root = root.resolve()
    findings: list[SecretFinding] = []
    scanned = 0
    skipped = 0

    for path in _iter_candidate_files(root, start_path, max_files):
        try:
            size = path.stat().st_size
        except OSError:
            skipped += 1
            continue
        if size > max_bytes_per_file or is_probably_binary(path):
            skipped += 1
            continue
        scanned += 1
        rel = str(path.relative_to(root))
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            skipped += 1
            continue
        for line_number, line in enumerate(lines, start=1):
            findings.extend(_scan_line(rel, line_number, line, minimum_severity))
            if len(findings) >= max_findings:
                break
        if len(findings) >= max_findings:
            break
    return findings, scanned, skipped


def count_findings_by_severity(findings: Iterable[SecretFinding]) -> dict[str, int]:
    """Return a stable severity summary."""

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def has_blocking_secret_findings(findings: Iterable[SecretFinding]) -> bool:
    """Return True when findings should block PR/release readiness by default."""

    return any(finding.severity in {"critical", "high"} for finding in findings)


def scan_secrets(
    root: Path,
    *,
    start_path: str = ".",
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes_per_file: int = DEFAULT_MAX_BYTES_PER_FILE,
    max_findings: int = 100,
    minimum_severity: Severity = "low",
    max_chars: int = 12000,
) -> str:
    """Scan a workspace path for common secret patterns."""

    findings, scanned, skipped = scan_secret_findings(
        root,
        start_path=start_path,
        max_files=max_files,
        max_bytes_per_file=max_bytes_per_file,
        max_findings=max_findings,
        minimum_severity=minimum_severity,
    )

    if not findings:
        return (
            f"Secret scan complete. Files scanned: {scanned}. Skipped: {skipped}. "
            f"No likely secrets found at or above severity '{minimum_severity}'."
        )

    counts = count_findings_by_severity(findings)
    blocking = has_blocking_secret_findings(findings)
    rows = [
        "Secret scan found possible sensitive values.",
        f"Files scanned: {scanned}. Skipped: {skipped}. Findings shown: {len(findings)}.",
        "Severity counts: "
        + ", ".join(f"{name}={counts[name]}" for name in ("critical", "high", "medium", "low")),
        f"PR/release blocker: {'yes' if blocking else 'no'}; only high/critical findings block by default.",
        "Review these before committing or sharing diffs:",
    ]
    for finding in findings:
        rows.append(
            f"- {finding.path}:{finding.line} | {finding.severity} | {finding.rule} | {finding.preview}"
        )
    return truncate("\n".join(rows), max_chars)
