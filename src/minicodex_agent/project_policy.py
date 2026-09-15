"""Project-local policy enforcement for MiniCodex.

The policy file is intentionally simple JSON so teams can review it in pull
requests. It does not try to be a perfect sandbox; it adds a deterministic
project-level guardrail on top of the command safety layer.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safety import safe_resolve
from .utils import to_pretty_json

POLICY_PATH = Path(".minicodex/policy.json")

DEFAULT_PROJECT_POLICY: dict[str, Any] = {
    "version": 4,
    "enabled": True,
    "allowed_write_globs": [".env.example", "**/*"],
    "plugin_allowed_write_globs": [],
    "allow_env_examples": True,
    "blocked_write_globs": [
        ".git/**",
        ".env",
        ".env.*",
        ".env.local",
        ".env.*.local",
        "**/*.pem",
        "**/*.key",
        ".minicodex/runs/**",
        ".minicodex/snapshots/**",
    ],
    "blocked_command_regexes": [
        r"\brm\s+-rf\b",
        r"\bsudo\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bdd\s+if=.*\bof=/dev/",
    ],
    "allowed_command_prefixes": [],
    "require_approval_for_globs": ["pyproject.toml", "package.json", "pom.xml", "build.gradle"],
    "require_approval_command_regexes": [],
    "notes": "Project-local MiniCodex policy. Empty allowed_command_prefixes means rely on safety profile.",
}


@dataclass(frozen=True)
class PolicyDecision:
    """Result of evaluating a write or command against project policy."""

    allowed: bool
    reason: str
    requires_extra_approval: bool = False

    def render(self) -> str:
        """Return a readable one-line decision."""

        status = "allowed" if self.allowed else "blocked"
        extra = "; extra approval recommended" if self.requires_extra_approval else ""
        return f"{status}: {self.reason}{extra}"


def _normalize_policy_file(policy_file: str | Path | None) -> Path:
    """Return a safe project-relative policy path."""

    if policy_file is None or str(policy_file).strip() == "":
        return POLICY_PATH
    path = Path(str(policy_file))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("policy_file must be a project-relative path inside the workspace")
    return path


def project_policy_path(root: Path, policy_file: str | Path | None = None) -> Path:
    """Return the absolute project policy path."""

    return (root / _normalize_policy_file(policy_file)).resolve()


def read_project_policy(root: Path, policy_file: str | Path | None = None) -> dict[str, Any]:
    """Read the configured project policy or return defaults when it does not exist."""

    path = project_policy_path(root, policy_file)
    if not path.exists():
        return dict(DEFAULT_PROJECT_POLICY)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid MiniCodex policy JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"MiniCodex policy must be a JSON object: {path}")
    merged = dict(DEFAULT_PROJECT_POLICY)
    merged.update(raw)
    return merged


def _extend_unique(base: list[str], additions: list[str]) -> list[str]:
    """Return base plus additions without duplicates, preserving order."""

    return list(dict.fromkeys([*base, *additions]))


def read_effective_project_policy(
    root: Path,
    policy_file: str | Path | None = None,
    enabled_plugins: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Read project policy and merge policies from enabled plugin manifests.

    Plugin policies are intentionally allowed to tighten the runtime policy, not
    loosen it. Supported plugin policy fields are: blocked_write_globs,
    allowed_write_globs, blocked_command_regexes, allowed_command_prefixes,
    require_approval_for_globs, require_approval_command_regexes, and
    prefer_dry_run.
    """

    policy = read_project_policy(root, policy_file)
    try:
        from .plugin_registry import list_active_plugin_policies

        plugin_policies = list_active_plugin_policies(root, enabled_plugins)
    except Exception:  # noqa: BLE001 - plugin diagnostics must not break base policy
        plugin_policies = []

    for plugin_policy in plugin_policies:
        if not isinstance(plugin_policy, dict):
            continue

        for field in (
            "blocked_write_globs",
            "blocked_command_regexes",
            "require_approval_for_globs",
            "require_approval_command_regexes",
        ):
            policy[field] = _extend_unique(
                _as_list(policy.get(field)), _as_list(plugin_policy.get(field))
            )

        # A plugin-level allowed_write_globs entry is treated as an additional
        # restriction. It cannot expand project policy; evaluate_write_path
        # requires the target path to match this list when it is present.
        policy["plugin_allowed_write_globs"] = _extend_unique(
            _as_list(policy.get("plugin_allowed_write_globs")),
            _as_list(plugin_policy.get("allowed_write_globs")),
        )

        prefixes = _as_list(plugin_policy.get("allowed_command_prefixes"))
        if prefixes:
            current = _as_list(policy.get("allowed_command_prefixes"))
            policy["allowed_command_prefixes"] = _extend_unique(current, prefixes)

        if bool(plugin_policy.get("prefer_dry_run", False)):
            policy["require_approval_for_globs"] = _extend_unique(
                _as_list(policy.get("require_approval_for_globs")), ["**/*"]
            )
            policy["require_approval_command_regexes"] = _extend_unique(
                _as_list(policy.get("require_approval_command_regexes")), [r".*"]
            )

    return policy


def init_project_policy(
    root: Path,
    overwrite: bool = False,
    policy_file: str | Path | None = None,
    dry_run: bool = False,
) -> str:
    """Create .minicodex/policy.json with safe defaults."""

    path = project_policy_path(root, policy_file)
    if path.exists() and not overwrite:
        return f"Project policy already exists: {path.relative_to(root)}\n\n" + to_pretty_json(
            read_project_policy(root, policy_file)
        )
    action = "overwrite" if path.exists() else "create"
    if dry_run:
        return (
            f"DRY-RUN: would {action} project policy: {path.relative_to(root)}\n\n"
            + to_pretty_json(DEFAULT_PROJECT_POLICY)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(DEFAULT_PROJECT_POLICY) + "\n", encoding="utf-8")
    return f"Project policy created: {path.relative_to(root)}\n\n" + to_pretty_json(
        DEFAULT_PROJECT_POLICY
    )


def update_project_policy(
    root: Path,
    updates: dict[str, Any],
    policy_file: str | Path | None = None,
    dry_run: bool = False,
) -> str:
    """Merge updates into .minicodex/policy.json."""

    if not isinstance(updates, dict):
        raise ValueError("updates must be a JSON object")
    current = read_project_policy(root, policy_file)
    current.update(updates)
    path = project_policy_path(root, policy_file)
    if dry_run:
        return (
            f"DRY-RUN: would update project policy: {path.relative_to(root)}\n\n"
            + to_pretty_json(current)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(current) + "\n", encoding="utf-8")
    return f"Project policy updated: {path.relative_to(root)}\n\n" + to_pretty_json(current)


def render_project_policy(root: Path, policy_file: str | Path | None = None) -> str:
    """Render the currently active policy."""

    path = project_policy_path(root, policy_file)
    status = "stored" if path.exists() else "defaults only; file not created yet"
    return (
        f"MiniCodex project policy ({status}, file={path.relative_to(root)}):\n"
        + to_pretty_json(read_project_policy(root, policy_file))
    )


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _rel_path(root: Path, user_path: str) -> str:
    resolved = safe_resolve(root, user_path)
    try:
        rel = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = user_path
    return rel or "."


def _matches_any(path: str, patterns: list[str]) -> bool:
    candidates = {path, f"./{path}"}
    if "/" not in path:
        candidates.add(f"**/{path}")
    for pattern in patterns:
        normalized = pattern.replace("\\", "/")
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, normalized) or fnmatch.fnmatch(path, normalized):
                return True
    return False


def _is_env_example_path(path: str) -> bool:
    """Return true for documented env example files, not real env files."""

    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    name = normalized.rsplit("/", 1)[-1]
    return name in {".env.example", ".env.sample", ".env.template", ".env.example.local.sample"}


def _matches_blocked_write(path: str, patterns: list[str], policy: dict[str, Any]) -> bool:
    """Evaluate blocked globs while honoring allow_env_examples."""

    allow_env_examples = bool(policy.get("allow_env_examples", True))
    if allow_env_examples and _is_env_example_path(path):
        # Teams often use broad legacy patterns such as `.env.*`. Those should
        # still block real env variants, but should not block example/template
        # files that intentionally contain placeholders for onboarding. Explicit
        # non-env blocks such as `.git/**` and `**/*.key` continue to apply.
        env_patterns = {".env.*", "**/.env.*", "./.env.*"}
        filtered = [p for p in patterns if p.replace("\\", "/") not in env_patterns]
        return _matches_any(path, filtered)
    return _matches_any(path, patterns)


def evaluate_write_path(
    root: Path, user_path: str, policy: dict[str, Any] | None = None
) -> PolicyDecision:
    """Evaluate whether a write to user_path is allowed by project policy."""

    policy = read_project_policy(root) if policy is None else policy
    if not bool(policy.get("enabled", True)):
        return PolicyDecision(True, "project policy disabled")

    rel = _rel_path(root, user_path)
    blocked = _as_list(policy.get("blocked_write_globs"))
    allowed = _as_list(policy.get("allowed_write_globs")) or ["**/*"]
    extra = _as_list(policy.get("require_approval_for_globs"))

    plugin_allowed = _as_list(policy.get("plugin_allowed_write_globs"))

    if _matches_blocked_write(rel, blocked, policy):
        return PolicyDecision(False, f"path '{rel}' matches blocked_write_globs")
    if not _matches_any(rel, allowed):
        return PolicyDecision(False, f"path '{rel}' does not match allowed_write_globs")
    if plugin_allowed and not _matches_any(rel, plugin_allowed):
        return PolicyDecision(
            False, f"path '{rel}' does not match enabled plugin allowed_write_globs"
        )
    return PolicyDecision(True, f"path '{rel}' allowed", _matches_any(rel, extra))


def extract_patch_paths(patch_text: str) -> list[str]:
    """Extract relative file paths from a unified/git diff patch.

    This intentionally includes write targets for creates, modifies, deletes,
    and renames so policy checks cover all paths the patch engine may touch.
    """

    paths: list[str] = []

    def add(raw: str) -> None:
        raw = raw.strip().split("\t", 1)[0]
        if raw == "/dev/null":
            return
        if raw.startswith("a/") or raw.startswith("b/"):
            raw = raw[2:]
        if raw and raw not in paths:
            paths.append(raw)

    for line in patch_text.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            add(line[4:])
        elif line.startswith("rename from "):
            add(line[len("rename from ") :])
        elif line.startswith("rename to "):
            add(line[len("rename to ") :])
        elif line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                add(parts[2])
                add(parts[3])
    return paths


def evaluate_patch_paths(
    root: Path, patch_text: str, policy: dict[str, Any] | None = None
) -> PolicyDecision:
    """Evaluate all write targets in a unified diff patch."""

    paths = extract_patch_paths(patch_text)
    if not paths:
        return PolicyDecision(False, "patch contains no recognizable file paths")
    extra = False
    for path in paths:
        decision = evaluate_write_path(root, path, policy)
        if not decision.allowed:
            return decision
        extra = extra or decision.requires_extra_approval
    return PolicyDecision(True, f"patch paths allowed: {', '.join(paths)}", extra)


def evaluate_command(
    root: Path, command: str, policy: dict[str, Any] | None = None
) -> PolicyDecision:
    """Evaluate a command against project policy."""

    del root  # root kept for a symmetrical tool API and future path-aware policies
    policy = DEFAULT_PROJECT_POLICY if policy is None else policy
    if not bool(policy.get("enabled", True)):
        return PolicyDecision(True, "project policy disabled")

    normalized = command.strip()
    for pattern in _as_list(policy.get("blocked_command_regexes")):
        try:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return PolicyDecision(False, f"command matches blocked_command_regexes: {pattern}")
        except re.error:
            return PolicyDecision(False, f"invalid blocked command regex in policy: {pattern}")

    prefixes = _as_list(policy.get("allowed_command_prefixes"))
    if prefixes and not any(normalized.startswith(prefix) for prefix in prefixes):
        return PolicyDecision(False, "command does not start with any allowed_command_prefixes")

    extra_approval = False
    for pattern in _as_list(policy.get("require_approval_command_regexes")):
        try:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                extra_approval = True
        except re.error:
            return PolicyDecision(
                False, f"invalid require-approval command regex in policy: {pattern}"
            )

    return PolicyDecision(True, "command allowed by project policy", extra_approval)


def render_policy_check(
    root: Path,
    kind: str,
    value: str,
    policy_file: str | Path | None = None,
    enabled_plugins: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Render a policy decision for CLI/model inspection."""

    policy = read_effective_project_policy(root, policy_file, enabled_plugins)
    if kind == "write_path":
        decision = evaluate_write_path(root, value, policy)
    elif kind == "command":
        decision = evaluate_command(root, value, policy)
    elif kind == "patch":
        decision = evaluate_patch_paths(root, value, policy)
    else:
        return "Unknown policy check kind. Use write_path, command, or patch."
    return decision.render()
