"""Safety checks for local command execution and workspace paths.

MiniCodex does not claim to be a complete sandbox. This module provides
predictable guardrails: shell metacharacters are rejected, commands are parsed
into argv lists, strict mode is allow-list based, and network/install commands
need an explicit runtime permission.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\brm\s+-rf\s+\*",
    r"\brm\s+-rf\s+\.",
    r"\bsudo\s+rm\b",
    r"\bmkfs\b",
    r"\bformat\s+[a-z]:",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bdel\s+/s\b",
    r"\brd\s+/s\b",
    r"\breg\s+delete\b",
    r":\(\)\s*\{\s*:\|:",
    r"\bcurl\b.*\|\s*(sh|bash|python|python3|pwsh|powershell)\b",
    r"\bwget\b.*\|\s*(sh|bash|python|python3|pwsh|powershell)\b",
    r"\binvoke-expression\b",
    r"\biex\b",
    r"\bchmod\s+-r\s+777\s+/",
    r"\bchown\s+-r\b",
    r"\bdd\s+if=.*\bof=/dev/",
]

STRICT_ALLOWED_COMMAND_PATTERNS = [
    r"^git\s+(status|diff|log|show|branch)(\s|$)",
    r"^pytest(\s|$)",
    r"^python\s+-m\s+pytest(\s|$)",
    r"^python3\s+-m\s+pytest(\s|$)",
    r"^ruff\s+check(\s|$)",
    r"^mypy(\s|$)",
    r"^npm\s+(test|run\s+(test|build|lint))(\s|$)",
    r"^pnpm\s+(test|run\s+(test|build|lint))(\s|$)",
    r"^yarn\s+(test|build|lint)(\s|$)",
    r"^mvn\s+test(\s|$)",
    r"^(./)?gradlew\s+test(\s|$)",
    r"^gradle\s+test(\s|$)",
    r"^cargo\s+test(\s|$)",
    r"^go\s+test(\s|$)",
    r"^make\s+(test|check|lint|build)(\s|$)",
]

NETWORK_OR_INSTALL_PATTERNS = [
    r"\bpip\s+install\b",
    r"\buv\s+pip\s+install\b",
    r"\bpoetry\s+add\b",
    r"\bnpm\s+install\b",
    r"\bnpm\s+i\b",
    r"\bpnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\bcargo\s+install\b",
    r"\bapt(-get)?\s+install\b",
    r"\bbrew\s+install\b",
    r"\bcurl\b",
    r"\bwget\b",
]

# Unsupported in command strings because MiniCodex now calls subprocess with
# shell=False. Pipelines/redirection/chaining must be expressed as separate
# bounded tool calls instead of one shell script.
SHELL_CONTROL_TOKENS = {";", "&&", "||", "|", ">", ">>", "<", "<<", "`"}
SHELL_CONTROL_PATTERNS = [r"\$\(", r"`", r"\n", r"\r"]

EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    ".turbo",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".minicodex",
}


SENSITIVE_FILE_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
    "credentials.json",
    "secrets.json",
    "secret.json",
    "service-account.json",
    "service_account.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

SENSITIVE_FILE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}

SENSITIVE_DIR_NAMES = {
    ".aws",
    ".ssh",
    ".gnupg",
}

ENV_EXAMPLE_NAMES = {
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.example.local.sample",
}

EXCLUDED_FILE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".pyc",
    ".pyd",
    ".db",
    ".sqlite",
    ".sqlite3",
}


@dataclass(frozen=True)
class CommandSafetyDecision:
    """Parsed command plus policy-like safety metadata."""

    allowed: bool
    reason: str
    argv: list[str]
    risk: str = "unknown: review carefully"
    requires_explicit_permission: bool = False
    requires_manual_approval: bool = False

    def render(self) -> str:
        """Return a readable one-line decision."""

        status = "allowed" if self.allowed else "blocked"
        flags: list[str] = []
        if self.requires_explicit_permission:
            flags.append("explicit permission required")
        if self.requires_manual_approval:
            flags.append("manual approval required")
        suffix = f"; {'; '.join(flags)}" if flags else ""
        return f"{status}: {self.reason}; risk={self.risk}{suffix}"


def _is_network_or_install(command: str) -> bool:
    normalized = command.strip().lower()
    return any(re.search(pattern, normalized) for pattern in NETWORK_OR_INSTALL_PATTERNS)


def has_shell_control(command: str) -> bool:
    """Return True when the command contains shell-only control syntax."""

    tokens = command.replace("&&", " && ").replace("||", " || ").split()
    if any(token in SHELL_CONTROL_TOKENS for token in tokens):
        return True
    return any(re.search(pattern, command) for pattern in SHELL_CONTROL_PATTERNS)


def parse_command_argv(command: str) -> tuple[list[str], str | None]:
    """Parse a user command into argv for subprocess.run(shell=False)."""

    stripped = command.strip()
    if not stripped:
        return [], "empty command"
    if has_shell_control(stripped):
        return [], "shell control syntax is not supported; use separate bounded commands"
    try:
        argv = shlex.split(stripped, posix=os.name != "nt")
    except ValueError as exc:
        return [], f"could not parse command safely: {exc}"
    if os.name == "nt":
        argv = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}
            else token
            for token in argv
        ]
    if not argv:
        return [], "empty command"
    return argv, None


def assess_command_safety(
    command: str,
    *,
    profile: str = "strict",
    allow_network: bool = False,
) -> CommandSafetyDecision:
    """Return a deterministic safety decision for command execution."""

    normalized = command.strip().lower()
    risk = command_risk_label(command)
    argv, parse_error = parse_command_argv(command)
    if parse_error:
        return CommandSafetyDecision(False, parse_error, [], risk=risk)

    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, normalized):
            return CommandSafetyDecision(
                False, f"command matches dangerous pattern: {pattern}", argv, risk=risk
            )

    is_network = _is_network_or_install(command)
    if is_network and not allow_network:
        return CommandSafetyDecision(
            False,
            "network/install command requires --allow-network-commands or project config permission",
            argv,
            risk=risk,
            requires_explicit_permission=True,
            requires_manual_approval=True,
        )

    if profile == "strict":
        if not any(re.search(pattern, normalized) for pattern in STRICT_ALLOWED_COMMAND_PATTERNS):
            return CommandSafetyDecision(
                False,
                "strict profile allows only test/build/lint/read-only git commands",
                argv,
                risk=risk,
            )
    elif profile == "balanced":
        # Balanced mode still uses shell=False and blocks dangerous patterns.
        # Unknown commands are allowed; high-risk/network operations still require
        # explicit approval or permissions.
        pass
    elif profile == "permissive":
        pass
    else:
        return CommandSafetyDecision(False, f"unknown safety profile: {profile}", argv, risk=risk)

    return CommandSafetyDecision(
        True,
        "command passed MiniCodex safety checks",
        argv,
        risk=risk,
        requires_explicit_permission=is_network,
        requires_manual_approval=is_network or risk.startswith("high"),
    )


def unsafe_command_reason(
    command: str, profile: str = "strict", allow_network: bool = False
) -> str | None:
    """Return a reason if the command should be blocked."""

    decision = assess_command_safety(command, profile=profile, allow_network=allow_network)
    return None if decision.allowed else decision.render()


def command_risk_label(command: str) -> str:
    """Return a human-readable risk label for a command."""

    normalized = command.strip().lower()
    if any(re.search(pattern, normalized) for pattern in NETWORK_OR_INSTALL_PATTERNS):
        return "high: dependency/network/install command"
    if any(token in normalized for token in ["rm ", "del ", "chmod", "chown", "sudo", "dd "]):
        return "high: destructive/system command"
    if any(
        token in normalized
        for token in ["pytest", "test", "lint", "build", "git diff", "git status"]
    ):
        return "low: check/test/build command"
    return "unknown: review carefully"


def safe_resolve(root: Path, user_path: str) -> Path:
    """Resolve a user path and ensure it stays inside the workspace root."""

    if not user_path:
        user_path = "."

    root = root.resolve()
    target = (root / user_path).resolve()

    if target != root and root not in target.parents:
        raise ValueError(f"Path proje klasörünün dışına çıkıyor: {user_path}")

    return target


def _relative_parts_lower(path: Path, root: Path) -> tuple[str, ...] | None:
    """Return lower-cased relative path parts, or None for paths outside root."""

    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return tuple(part.lower() for part in rel.parts)


def is_env_example_name(name: str) -> bool:
    """Return True for documented environment example/template files."""

    return name.lower() in ENV_EXAMPLE_NAMES


def sensitive_path_reason(path: Path, root: Path) -> str | None:
    """Return the reason a path is considered sensitive, or None.

    This intentionally focuses on real secret containers such as .env files,
    private-key material, token config files, and known credential locations.
    Example/template env files remain visible so projects can document setup.
    """

    parts = _relative_parts_lower(path, root)
    if parts is None:
        return "outside workspace"
    if not parts:
        return None

    name = parts[-1]
    if is_env_example_name(name):
        return None
    if name == ".env" or name.startswith(".env."):
        return "environment file"
    if name in SENSITIVE_FILE_NAMES:
        return "credential file name"
    if name.startswith(("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")):
        return "private key file name"
    if Path(name).suffix.lower() in SENSITIVE_FILE_SUFFIXES:
        return "private key/certificate container suffix"
    if set(parts) & SENSITIVE_DIR_NAMES:
        return "credential directory"
    return None


def is_sensitive_path(path: Path, root: Path) -> bool:
    """Return True when a path should not be exposed through normal agent IO."""

    return sensitive_path_reason(path, root) is not None


def should_skip_path(path: Path, root: Path, *, allow_sensitive: bool = False) -> bool:
    """Return True if a path should be hidden from normal agent-visible IO."""

    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True

    if set(rel.parts) & EXCLUDED_DIRS:
        return True

    if not allow_sensitive and sensitive_path_reason(path, root):
        return True

    if path.is_file() and path.suffix.lower() in EXCLUDED_FILE_SUFFIXES:
        return True

    return False
