"""GitHub REST API integration helpers for MiniCodex.

The helpers in this module intentionally use the Python standard library. They
support authenticated issue and pull-request creation when the user explicitly
enables GitHub API writes at runtime or in project config.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .github_tools import github_context
from .utils import to_pretty_json, truncate

DEFAULT_GITHUB_API_URL = "https://api.github.com"


@dataclass(frozen=True)
class GitHubRepository:
    """Resolved GitHub repository coordinates."""

    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class GitHubApiResult:
    """Normalized GitHub API call result."""

    ok: bool
    status: int
    data: dict[str, Any]
    message: str

    def render(self, *, max_chars: int = 12000) -> str:
        body = {
            "ok": self.ok,
            "status": self.status,
            "message": self.message,
            "data": self.data,
        }
        return truncate(to_pretty_json(body), max_chars)


class GitHubIntegrationError(RuntimeError):
    """Raised when GitHub API integration cannot proceed."""


def get_github_token() -> str:
    """Return a GitHub token from common environment variables."""

    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""


def parse_github_remote_url(remote: str) -> GitHubRepository | None:
    """Parse common GitHub remote URL forms into owner/repo.

    Supported examples:
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo.git
    - ssh://git@github.com/owner/repo.git
    """

    remote = remote.strip()
    if not remote or remote == "not configured":
        return None

    patterns = [
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, remote)
        if match:
            owner = match.group("owner").strip()
            repo = match.group("repo").strip().removesuffix(".git")
            if owner and repo:
                return GitHubRepository(owner=owner, repo=repo)
    return None


def resolve_github_repository(root: Path, owner: str = "", repo: str = "") -> GitHubRepository:
    """Resolve repository coordinates from explicit args or git remote origin."""

    owner = owner.strip()
    repo = repo.strip().removesuffix(".git")
    if owner and repo:
        return GitHubRepository(owner=owner, repo=repo)

    context = github_context(root)
    parsed = parse_github_remote_url(context.get("remote_origin", ""))
    if parsed:
        return parsed

    raise GitHubIntegrationError(
        "GitHub repository could not be resolved. Provide owner/repo or configure git remote origin."
    )


def current_branch(root: Path) -> str:
    """Return the current git branch if available."""

    context = github_context(root)
    branch = context.get("branch", "").strip()
    if branch == "unknown" or branch.lower().startswith("fatal:"):
        return ""
    return branch


def _api_base() -> str:
    return os.getenv("GITHUB_API_URL", DEFAULT_GITHUB_API_URL).rstrip("/")


def github_api_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> GitHubApiResult:
    """Call the GitHub REST API and return a normalized result."""

    if not token:
        raise GitHubIntegrationError("GITHUB_TOKEN or GH_TOKEN is required for GitHub API writes.")

    url = _api_base() + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "minicodex-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit GitHub API integration
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            if not isinstance(parsed, dict):
                parsed = {"response": parsed}
            return GitHubApiResult(
                ok=200 <= response.status < 300,
                status=response.status,
                data=parsed,
                message="GitHub API request succeeded.",
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_error = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed_error = {"error": raw}
        if not isinstance(parsed_error, dict):
            parsed_error = {"error": parsed_error}
        return GitHubApiResult(
            ok=False,
            status=exc.code,
            data=parsed_error,
            message="GitHub API request failed.",
        )
    except urllib.error.URLError as exc:
        raise GitHubIntegrationError(f"GitHub API network error: {exc}") from exc


def create_github_issue_api(
    root: Path,
    *,
    title: str,
    body: str,
    labels: list[str] | None = None,
    owner: str = "",
    repo: str = "",
    token: str | None = None,
    timeout: int = 30,
) -> GitHubApiResult:
    """Create a GitHub issue through the REST API."""

    repository = resolve_github_repository(root, owner=owner, repo=repo)
    payload: dict[str, Any] = {"title": title.strip(), "body": body.strip()}
    clean_labels = [str(label).strip() for label in labels or [] if str(label).strip()]
    if clean_labels:
        payload["labels"] = clean_labels
    return github_api_request(
        "POST",
        f"/repos/{repository.owner}/{repository.repo}/issues",
        token=token if token is not None else get_github_token(),
        payload=payload,
        timeout=timeout,
    )


def create_github_pr_api(
    root: Path,
    *,
    title: str,
    body: str,
    base: str = "main",
    head: str = "",
    draft: bool = True,
    owner: str = "",
    repo: str = "",
    token: str | None = None,
    timeout: int = 30,
) -> GitHubApiResult:
    """Create a GitHub pull request through the REST API."""

    repository = resolve_github_repository(root, owner=owner, repo=repo)
    resolved_head = head.strip() or current_branch(root)
    if not resolved_head:
        raise GitHubIntegrationError(
            "Pull request head branch could not be resolved; pass head explicitly."
        )
    payload = {
        "title": title.strip() or "MiniCodex changes",
        "body": body.strip() or "Prepared by MiniCodex. Review the diff and checks before merging.",
        "base": base.strip() or "main",
        "head": resolved_head,
        "draft": bool(draft),
    }
    return github_api_request(
        "POST",
        f"/repos/{repository.owner}/{repository.repo}/pulls",
        token=token if token is not None else get_github_token(),
        payload=payload,
        timeout=timeout,
    )


def github_api_raw_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> tuple[int, bytes, dict[str, str]]:
    """Call GitHub REST API and return raw bytes for non-JSON endpoints.

    This is used for endpoints such as Actions logs, which return a zip file.
    It is intentionally small and standard-library only.
    """

    if not token:
        raise GitHubIntegrationError(
            "GITHUB_TOKEN or GH_TOKEN is required for GitHub API reads/writes."
        )

    url = _api_base() + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "minicodex-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit GitHub API integration
            headers = {str(k): str(v) for k, v in response.headers.items()}
            return response.status, response.read(), headers
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        headers = {str(k): str(v) for k, v in exc.headers.items()}
        return exc.code, raw, headers
    except urllib.error.URLError as exc:
        raise GitHubIntegrationError(f"GitHub API network error: {exc}") from exc


def fetch_github_actions_run_api(
    root: Path,
    *,
    run_id: str,
    owner: str = "",
    repo: str = "",
    token: str | None = None,
    timeout: int = 30,
) -> GitHubApiResult:
    """Fetch one GitHub Actions run metadata object."""

    repository = resolve_github_repository(root, owner=owner, repo=repo)
    return github_api_request(
        "GET",
        f"/repos/{repository.owner}/{repository.repo}/actions/runs/{run_id}",
        token=token if token is not None else get_github_token(),
        timeout=timeout,
    )


def fetch_github_actions_jobs_api(
    root: Path,
    *,
    run_id: str,
    owner: str = "",
    repo: str = "",
    token: str | None = None,
    timeout: int = 30,
) -> GitHubApiResult:
    """Fetch GitHub Actions jobs for one workflow run."""

    repository = resolve_github_repository(root, owner=owner, repo=repo)
    return github_api_request(
        "GET",
        f"/repos/{repository.owner}/{repository.repo}/actions/runs/{run_id}/jobs",
        token=token if token is not None else get_github_token(),
        timeout=timeout,
    )


def fetch_github_actions_logs_zip_api(
    root: Path,
    *,
    run_id: str,
    owner: str = "",
    repo: str = "",
    token: str | None = None,
    timeout: int = 30,
) -> tuple[int, bytes, dict[str, str]]:
    """Fetch the GitHub Actions logs zip for one workflow run."""

    repository = resolve_github_repository(root, owner=owner, repo=repo)
    return github_api_raw_request(
        "GET",
        f"/repos/{repository.owner}/{repository.repo}/actions/runs/{run_id}/logs",
        token=token if token is not None else get_github_token(),
        timeout=timeout,
    )


def create_github_review_comment_api(
    root: Path,
    *,
    pull_number: int,
    body: str,
    event: str = "COMMENT",
    comments: list[dict[str, Any]] | None = None,
    owner: str = "",
    repo: str = "",
    token: str | None = None,
    timeout: int = 30,
) -> GitHubApiResult:
    """Create a pull-request review or review comments through the REST API."""

    repository = resolve_github_repository(root, owner=owner, repo=repo)
    payload: dict[str, Any] = {"body": body.strip(), "event": event.strip().upper() or "COMMENT"}
    if comments:
        payload["comments"] = comments
    return github_api_request(
        "POST",
        f"/repos/{repository.owner}/{repository.repo}/pulls/{pull_number}/reviews",
        token=token if token is not None else get_github_token(),
        payload=payload,
        timeout=timeout,
    )


def render_github_api_preview(
    root: Path,
    *,
    kind: str,
    title: str,
    body: str,
    base: str = "main",
    head: str = "",
    draft: bool = True,
    labels: list[str] | None = None,
    owner: str = "",
    repo: str = "",
    max_chars: int = 12000,
) -> str:
    """Render the exact API request MiniCodex would send without sending it."""

    repository = resolve_github_repository(root, owner=owner, repo=repo)
    if kind == "issue":
        payload: dict[str, Any] = {"title": title.strip(), "body": body.strip()}
        clean_labels = [str(label).strip() for label in labels or [] if str(label).strip()]
        if clean_labels:
            payload["labels"] = clean_labels
        endpoint = f"POST /repos/{repository.owner}/{repository.repo}/issues"
    elif kind == "pull_request":
        payload = {
            "title": title.strip() or "MiniCodex changes",
            "body": body.strip()
            or "Prepared by MiniCodex. Review the diff and checks before merging.",
            "base": base.strip() or "main",
            "head": head.strip() or current_branch(root) or "<current-branch>",
            "draft": bool(draft),
        }
        endpoint = f"POST /repos/{repository.owner}/{repository.repo}/pulls"
    else:
        raise ValueError("kind must be issue or pull_request")

    preview = {
        "dry_run": True,
        "endpoint": endpoint,
        "repository": repository.full_name,
        "payload": payload,
        "auth": "GITHUB_TOKEN or GH_TOKEN required for real execution",
    }
    return truncate(to_pretty_json(preview), max_chars)
