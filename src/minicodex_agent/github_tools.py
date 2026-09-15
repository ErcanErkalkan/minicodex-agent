"""GitHub-oriented helpers that prepare safe issue/PR workflows."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from .utils import truncate


def _run(root: Path, args: list[str], timeout: int = 30) -> str:
    completed = subprocess.run(
        args,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return (completed.stdout + completed.stderr).strip()


def _git(root: Path, args: list[str]) -> str:
    return _run(root, ["git", *args])


def _quote(value: str) -> str:
    return shlex.quote(value)


def github_context(root: Path) -> dict[str, str]:
    """Return local GitHub-related git context without making network calls."""

    return {
        "is_git_repo": "yes" if (root / ".git").exists() else "no",
        "branch": _git(root, ["branch", "--show-current"]) or "unknown",
        "remote_origin": _git(root, ["remote", "get-url", "origin"]) or "not configured",
        "status_short": _git(root, ["status", "--short"]) or "clean",
    }


def prepare_github_pr(
    root: Path,
    title: str = "",
    body: str = "",
    base: str = "",
    draft: bool = True,
    max_chars: int = 16000,
) -> str:
    """Prepare a GitHub PR command and checklist without creating the PR."""

    context = github_context(root)
    if context["is_git_repo"] != "yes":
        return "Git repo bulunamadı; GitHub PR hazırlığı için önce repository içinde çalıştırın."

    title = title.strip() or "MiniCodex changes"
    body = body.strip() or "Prepared by MiniCodex. Review the diff and checks before merging."
    command_parts = ["gh", "pr", "create", "--title", _quote(title), "--body", _quote(body)]
    if base.strip():
        command_parts.extend(["--base", _quote(base.strip())])
    if draft:
        command_parts.append("--draft")
    command = " ".join(command_parts)

    rows = [
        "# GitHub PR hazırlığı",
        "",
        f"Branch: `{context['branch']}`",
        f"Remote: `{context['remote_origin']}`",
        "",
        "## Önerilen komut",
        "```bash",
        command,
        "```",
        "",
        "## Önce kontrol et",
        "- `git diff -- .` ile değişiklikleri incele",
        "- Test/lint/build komutlarını çalıştır",
        "- Secret, cache veya yedek dosyası commit edilmediğini doğrula",
        "- `gh auth status` ile GitHub CLI oturumunu kontrol et",
        "",
        "## Git durum özeti",
        "```",
        context["status_short"],
        "```",
    ]
    return truncate("\n".join(rows), max_chars)


def prepare_github_issue(
    root: Path,
    title: str,
    body: str,
    labels: list[str] | None = None,
    max_chars: int = 12000,
) -> str:
    """Prepare a GitHub issue command without creating the issue."""

    context = github_context(root)
    title = title.strip()
    body = body.strip()
    if not title:
        return "Issue başlığı boş olamaz."
    if not body:
        return "Issue açıklaması boş olamaz."

    command_parts = ["gh", "issue", "create", "--title", _quote(title), "--body", _quote(body)]
    for label in labels or []:
        label = str(label).strip()
        if label:
            command_parts.extend(["--label", _quote(label)])

    rows = [
        "# GitHub issue hazırlığı",
        "",
        f"Remote: `{context['remote_origin']}`",
        "",
        "## Önerilen komut",
        "```bash",
        " ".join(command_parts),
        "```",
        "",
        "## Not",
        "Bu araç issue oluşturmaz; güvenli şekilde komut taslağı üretir.",
    ]
    return truncate("\n".join(rows), max_chars)
