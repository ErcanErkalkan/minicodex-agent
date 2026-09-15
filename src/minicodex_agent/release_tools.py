"""Release-readiness helpers for MiniCodex projects."""

from __future__ import annotations

from pathlib import Path

from .project_inspector import choose_test_command, detect_project
from .secret_scanner import (
    count_findings_by_severity,
    has_blocking_secret_findings,
    scan_secret_findings,
    scan_secrets,
)
from .utils import to_pretty_json, truncate


def _read_pyproject_version(root: Path) -> str:
    path = root / "pyproject.toml"
    if not path.exists():
        return "unknown"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("version") and "=" in line:
            return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


def build_release_checklist(root: Path, *, version: str = "") -> str:
    """Render a practical release checklist for the current project."""

    profile = detect_project(root)
    detected_version = version or _read_pyproject_version(root)
    test_command = choose_test_command(profile, "auto") or "manual test command not detected"
    checklist = {
        "version": detected_version,
        "project_types": profile.project_types,
        "detected_test_command": test_command,
        "required_checks": [
            "pytest -q or detected project test command passes",
            "ruff check . or project linter passes when available",
            "python -m build succeeds for package releases",
            "scan_secrets reports no high-risk findings",
            "review_change_set has been reviewed by a human",
            "README quickstart is current",
            "CHANGELOG includes the release version",
            "LICENSE is present",
            "pyproject.toml metadata is correct",
        ],
        "recommended_commands": [
            test_command,
            "ruff check .",
            "python -m build",
            "git status --short",
            "git diff --stat",
        ],
        "manual_review": [
            "Confirm API keys are not committed.",
            "Confirm project policy allows only expected writes/commands.",
            "Confirm demo project and smoke-test commands work.",
            "Tag release only after tests and docs are verified.",
        ],
    }
    return "MiniCodex release checklist:\n" + to_pretty_json(checklist)


def write_release_notes(
    root: Path, *, version: str = "", output_path: str = "RELEASE_NOTES.md", dry_run: bool = False
) -> str:
    """Write a concise release notes template."""

    detected_version = version or _read_pyproject_version(root)
    path = (root / output_path).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise ValueError("output_path must stay inside project root")
    content = f"""# Release Notes - {detected_version}\n\n## Highlights\n\n- MiniCodex {detected_version} package structure with runtime plugin enforcement.\n- Setup wizard for project-local config, policy, env example, and plugin manifest.\n- Demo project generator for safe local testing.\n- Release checklist and health-report helpers.\n- Policy-aware file/command operations, runtime plugin tool gates, snapshots, task memory, secret scanning, and PR preparation.\n\n## Verification\n\n- [ ] Test suite passes.\n- [ ] Linter passes or known warnings are documented.\n- [ ] Secret scan reviewed.\n- [ ] README and examples reviewed.\n- [ ] Package build checked.\n\n## Upgrade Notes\n\nFor existing projects, run:\n\n```bash\nminicodex --setup --root .\n```\n\nThen review `.minicodex/config.json` and `.minicodex/policy.json`.\n"""
    if dry_run:
        return f"DRY-RUN: release notes not written: {path.relative_to(root)}\n\n" + content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Release notes written: {path.relative_to(root)}"


def project_health_report(root: Path, *, max_chars: int = 12000) -> str:
    """Return a compact readiness report for a MiniCodex-managed project."""

    profile = detect_project(root)
    files = {
        "pyproject": (root / "pyproject.toml").exists(),
        "readme": (root / "README.md").exists(),
        "license": (root / "LICENSE").exists(),
        "changelog": (root / "CHANGELOG.md").exists(),
        "minicodex_config": (root / ".minicodex" / "config.json").exists(),
        "minicodex_policy": (root / ".minicodex" / "policy.json").exists(),
    }
    secret_findings, scanned, skipped = scan_secret_findings(root, max_files=300, max_findings=50)
    severity_counts = count_findings_by_severity(secret_findings)
    secret_blocker = has_blocking_secret_findings(secret_findings)
    secret_summary = scan_secrets(
        root, max_files=300, max_findings=20, minimum_severity="high", max_chars=4000
    )
    report = {
        "project_profile": profile.to_dict(),
        "version": _read_pyproject_version(root),
        "detected_test_command": choose_test_command(profile, "auto"),
        "important_files": files,
        "release_readiness": {
            "has_readme": files["readme"],
            "has_license": files["license"],
            "has_changelog": files["changelog"],
            "has_project_config": files["minicodex_config"],
            "has_project_policy": files["minicodex_policy"],
            "secret_scan_files_scanned": scanned,
            "secret_scan_files_skipped": skipped,
            "secret_scan_severity_counts": severity_counts,
            "secret_scan_blocks_pr_or_release": secret_blocker,
            "secret_scan_blocking_rule": "only high/critical findings block by default",
        },
    }
    return (
        "MiniCodex project health report:\n"
        + to_pretty_json(report)
        + "\n\nSecret scan excerpt:\n"
        + truncate(secret_summary, max_chars)
    )
