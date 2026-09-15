"""Higher-level GitHub workflow, PR comment, CI, and commit/push helpers.

This module deliberately separates *planning* from externally visible side
-effects. Most helpers return deterministic previews that an agent can reason
about without requiring network access or mutating a GitHub repository.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from .github_api import (
    GitHubIntegrationError,
    fetch_github_actions_jobs_api,
    fetch_github_actions_logs_zip_api,
    fetch_github_actions_run_api,
    get_github_token,
    resolve_github_repository,
)
from .github_tools import github_context
from .test_ci import summarize_ci_log as summarize_generic_ci_log
from .utils import to_pretty_json, truncate

WORKFLOW_DIR = Path(".github/workflows")
DEFAULT_MINICODEX_WORKFLOW = "minicodex-agent.yml"
_ALLOWED_COMMENT_COMMANDS = {
    "review",
    "fix",
    "test",
    "run",
    "eval",
    "resume",
    "plan",
    "help",
}
_ALLOWED_COMMENT_FLAGS = {
    "--dry-run",
    "--long-horizon",
    "--run-eval-suite",
    "--review-after-run",
    "--no-diff",
}
_ALLOWED_VALUE_FLAGS = {
    "--max-steps",
    "--model-call-budget",
    "--provider",
    "--model",
    "--sandbox-mode",
    "--eval-run-id",
    "--run-eval",
}


def _git(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _safe_workflow_name(value: str) -> str:
    name = (value or DEFAULT_MINICODEX_WORKFLOW).strip()
    if not name.endswith((".yml", ".yaml")):
        name += ".yml"
    # Keep workflow names boring; GitHub Actions workflow files do not need path
    # separators and allowing them would make overwrite behavior surprising.
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", name)
    return name or DEFAULT_MINICODEX_WORKFLOW


def _extract_workflow_name(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            return stripped.split(":", 1)[1].strip().strip("\"'") or fallback
    return fallback


def _extract_on_triggers(text: str) -> list[str]:
    triggers: set[str] = set()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("on:"):
            suffix = stripped.split(":", 1)[1].strip()
            if suffix.startswith("[") and suffix.endswith("]"):
                for item in suffix.strip("[]").split(","):
                    item = item.strip().strip("\"'")
                    if item:
                        triggers.add(item)
            # Read simple top-level keys under on: until next root key.
            for child in lines[i + 1 :]:
                if child and not child.startswith((" ", "\t")):
                    break
                child_stripped = child.strip()
                if not child_stripped or child_stripped.startswith("#"):
                    continue
                match = re.match(r"([A-Za-z0-9_-]+):", child_stripped)
                if match:
                    triggers.add(match.group(1))
            break
    return sorted(triggers)


def _extract_jobs(text: str) -> list[str]:
    jobs: set[str] = set()
    lines = text.splitlines()
    in_jobs = False
    for line in lines:
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if in_jobs and line and not line.startswith((" ", "\t")):
            break
        if in_jobs:
            match = re.match(r"^\s{2}([A-Za-z0-9_-]+):\s*$", line)
            if match:
                jobs.add(match.group(1))
    return sorted(jobs)


def detect_github_workflows(root: Path, *, max_chars: int = 16000) -> str:
    """Inspect local .github workflow files without running GitHub commands."""

    workflow_dir = root / WORKFLOW_DIR
    workflows: list[dict[str, Any]] = []
    if workflow_dir.exists():
        for path in sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                workflows.append({"path": str(path.relative_to(root)), "error": str(exc)})
                continue
            workflows.append(
                {
                    "path": str(path.relative_to(root)),
                    "name": _extract_workflow_name(text, path.stem),
                    "triggers": _extract_on_triggers(text),
                    "jobs": _extract_jobs(text),
                    "mentions_minicodex": "minicodex" in text.lower(),
                    "permissions_block": "permissions:" in text,
                }
            )
    data: dict[str, Any] = {
        "workflow_dir": str(WORKFLOW_DIR),
        "exists": workflow_dir.exists(),
        "count": len(workflows),
        "workflows": workflows,
        "recommendations": [],
    }
    if not workflows:
        data["recommendations"].append(
            "Add a GitHub Actions workflow for CI and optional MiniCodex slash-command automation."
        )
    if workflows and not any(w.get("mentions_minicodex") for w in workflows):
        data["recommendations"].append(
            "Existing workflows do not appear to expose a MiniCodex automation entrypoint."
        )
    return truncate("GitHub workflow inspection:\n" + to_pretty_json(data), max_chars)


def _minicodex_workflow_yaml() -> str:
    return """name: MiniCodex Agent

on:
  workflow_dispatch:
    inputs:
      goal:
        description: MiniCodex goal to run
        required: true
        default: Review the pull request and summarize risks.
      dry_run:
        description: Run without writing project files
        required: true
        type: boolean
        default: true
  issue_comment:
    types: [created]

permissions:
  contents: read
  pull-requests: write
  issues: write
  actions: read

concurrency:
  group: minicodex-${{ github.event.pull_request.number || github.event.issue.number || github.run_id }}
  cancel-in-progress: false

jobs:
  minicodex:
    if: >-
      github.event_name == 'workflow_dispatch' ||
      (github.event_name == 'issue_comment' && github.event.issue.pull_request && startsWith(github.event.comment.body, '/minicodex'))
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install MiniCodex project
        run: python -m pip install -e .
      - name: Build goal
        id: goal
        shell: bash
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            printf 'goal=%s\n' "${{ inputs.goal }}" >> "$GITHUB_OUTPUT"
            printf 'dry_run=%s\n' "${{ inputs.dry_run }}" >> "$GITHUB_OUTPUT"
          else
            printf 'goal=%s\n' "${{ github.event.comment.body }}" >> "$GITHUB_OUTPUT"
            printf 'dry_run=true\n' >> "$GITHUB_OUTPUT"
          fi
      - name: Run MiniCodex safely
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          EXTRA="--dry-run"
          if [ "${{ steps.goal.outputs.dry_run }}" = "false" ]; then
            EXTRA="--review-after-run"
          fi
          minicodex "${{ steps.goal.outputs.goal }}" \
            --root . \
            --approval ask \
            --safety-profile strict \
            --max-steps 8 \
            --model-call-budget 8 \
            $EXTRA
      - name: Upload MiniCodex artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: minicodex-artifacts-${{ github.run_id }}
          path: |
            .minicodex/runs
            .minicodex/review_bundles
            .minicodex/agent_workspaces/*/changes.diff
            .minicodex/agent_workspaces/*/manifest.json
          if-no-files-found: ignore
          retention-days: 7
"""


def init_github_action(
    root: Path,
    *,
    workflow_name: str = DEFAULT_MINICODEX_WORKFLOW,
    overwrite: bool = False,
    dry_run: bool = False,
) -> str:
    """Create a conservative MiniCodex GitHub Actions workflow template."""

    workflow_name = _safe_workflow_name(workflow_name)
    path = root / WORKFLOW_DIR / workflow_name
    content = _minicodex_workflow_yaml()
    rel = str(path.relative_to(root))
    if path.exists() and not overwrite:
        return f"GitHub workflow already exists: {rel}. Re-run with overwrite=true to replace it."
    if dry_run:
        return "DRY-RUN: GitHub workflow would be written.\n" + to_pretty_json(
            {"path": rel, "overwrite": overwrite, "preview": content[:2400]}
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"GitHub workflow written: {rel}"


def parse_pr_comment_command(
    comment: str, *, prefix: str = "/minicodex", max_chars: int = 12000
) -> str:
    """Parse a PR slash command into a safe MiniCodex execution plan."""

    raw = comment.strip()
    normalized_prefix = prefix.strip() or "/minicodex"
    result: dict[str, Any] = {
        "ok": False,
        "prefix": normalized_prefix,
        "raw": raw,
        "command": "",
        "goal": "",
        "flags": [],
        "value_flags": {},
        "warnings": [],
        "recommended_cli": [],
    }
    if not raw.startswith(normalized_prefix):
        result["warnings"].append("Comment does not start with the configured MiniCodex prefix.")
        return truncate("GitHub PR comment command parse:\n" + to_pretty_json(result), max_chars)
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        result["warnings"].append(f"Could not parse shell-like arguments: {exc}")
        return truncate("GitHub PR comment command parse:\n" + to_pretty_json(result), max_chars)
    if not parts or parts[0] != normalized_prefix:
        result["warnings"].append("Prefix must be the first token.")
        return truncate("GitHub PR comment command parse:\n" + to_pretty_json(result), max_chars)
    command = parts[1] if len(parts) > 1 and not parts[1].startswith("--") else "review"
    if command not in _ALLOWED_COMMENT_COMMANDS:
        result["warnings"].append(f"Unsupported command: {command}")
        return truncate("GitHub PR comment command parse:\n" + to_pretty_json(result), max_chars)
    remaining = parts[2:] if len(parts) > 1 and parts[1] == command else parts[1:]
    value_flags: dict[str, str] = {}
    flags: list[str] = []
    goal_tokens: list[str] = []
    i = 0
    while i < len(remaining):
        token = remaining[i]
        if token in _ALLOWED_COMMENT_FLAGS:
            flags.append(token)
            i += 1
            continue
        if token in _ALLOWED_VALUE_FLAGS:
            if i + 1 >= len(remaining) or remaining[i + 1].startswith("--"):
                result["warnings"].append(f"Flag {token} requires a value.")
                i += 1
                continue
            value_flags[token] = remaining[i + 1]
            i += 2
            continue
        if token.startswith("--"):
            result["warnings"].append(f"Ignored unsupported flag: {token}")
            i += 1
            continue
        goal_tokens.append(token)
        i += 1
    default_goals = {
        "review": "Review this pull request, summarize risks, and suggest focused checks.",
        "fix": "Investigate the pull request failure and prepare a minimal fix plan.",
        "test": "Plan and run targeted tests for the pull request.",
        "run": "Run the requested MiniCodex task.",
        "eval": "Run or plan MiniCodex evals for this repository.",
        "resume": "Resume the current long-horizon MiniCodex task.",
        "plan": "Create an implementation plan for the requested change.",
        "help": "Show supported MiniCodex PR slash commands.",
    }
    goal = " ".join(goal_tokens).strip() or default_goals[command]
    cli = ["minicodex", goal, "--root", ".", "--safety-profile", "strict"]
    if "--dry-run" not in flags:
        cli.append("--dry-run")
        result["warnings"].append("Dry-run was added by default for PR comments.")
    for flag in sorted(set(flags)):
        cli.append(flag)
    for flag, value in value_flags.items():
        cli.extend([flag, value])
    result.update(
        {
            "ok": not any(w.startswith("Unsupported") for w in result["warnings"]),
            "command": command,
            "goal": goal,
            "flags": sorted(set(flags + ["--dry-run"])),
            "value_flags": value_flags,
            "recommended_cli": cli,
        }
    )
    return truncate("GitHub PR comment command parse:\n" + to_pretty_json(result), max_chars)


def prepare_commit_push_plan(
    root: Path,
    *,
    branch: str = "",
    commit_message: str = "",
    remote: str = "origin",
    include_push: bool = True,
    max_chars: int = 16000,
) -> str:
    """Return a safe local Git branch/commit/push command plan without executing it."""

    context = github_context(root)
    status = _git(root, ["status", "--short"]).stdout.strip() if (root / ".git").exists() else ""
    current = context.get("branch", "unknown")
    safe_branch = (
        re.sub(r"[^A-Za-z0-9_./-]", "-", branch.strip()) if branch.strip() else "minicodex/changes"
    )
    safe_branch = safe_branch.strip("./") or "minicodex/changes"
    title = commit_message.strip() or "Apply MiniCodex changes"
    commands: list[str] = []
    warnings: list[str] = []
    if context["is_git_repo"] != "yes":
        warnings.append(
            "Current root is not a git repository; initialize or run inside a repo first."
        )
    if not status:
        warnings.append("No local git changes detected; commit would be empty.")
    if current != safe_branch:
        commands.append(
            f"git switch -c {shlex.quote(safe_branch)} || git switch {shlex.quote(safe_branch)}"
        )
    commands.extend(
        [
            "git status --short",
            "git diff -- .",
            "git add -- .",
            "git commit -m " + shlex.quote(title),
        ]
    )
    if include_push:
        commands.append(f"git push -u {shlex.quote(remote or 'origin')} {shlex.quote(safe_branch)}")
    data = {
        "repository": context,
        "target_branch": safe_branch,
        "commit_message": title,
        "include_push": include_push,
        "commands": commands,
        "warnings": warnings,
        "safety_notes": [
            "This tool does not execute git add/commit/push.",
            "Review git diff and run targeted tests before using the commands.",
            "Do not commit secrets, generated caches, or sandbox workspaces.",
        ],
    }
    return truncate("GitHub branch/commit/push plan:\n" + to_pretty_json(data), max_chars)


def summarize_github_ci_log(
    root: Path,
    *,
    output: str = "",
    log_path: str = "",
    workflow_name: str = "",
    max_chars: int = 16000,
) -> str:
    """Summarize a GitHub Actions log using the existing CI failure classifier."""

    text = output or ""
    if log_path:
        candidate = (root / log_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return "GitHub CI log path is outside the project root."
        if candidate.exists() and candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace")
        elif not text:
            return f"GitHub CI log file not found: {log_path}"
    if not text.strip():
        return "No GitHub CI log output was provided."
    summary = summarize_generic_ci_log(root, text, max_chars=max_chars)
    annotations = []
    for line in text.splitlines():
        if "::error" in line or "::warning" in line:
            annotations.append(line.strip())
    data = {
        "workflow_name": workflow_name.strip(),
        "github_annotations": annotations[:20],
        "generic_summary": summary,
    }
    return truncate("GitHub CI log summary:\n" + to_pretty_json(data), max_chars)


def github_ci_fetch_preview(
    root: Path,
    *,
    owner: str = "",
    repo: str = "",
    run_id: str = "",
    max_chars: int = 12000,
) -> str:
    """Render safe commands/API endpoints for fetching GitHub Actions logs."""

    try:
        repository = resolve_github_repository(root, owner=owner, repo=repo)
    except GitHubIntegrationError as exc:
        return f"GITHUB CI FETCH BLOCK: {exc}"
    rid = run_id.strip() or "<run_id>"
    data = {
        "repository": repository.full_name,
        "run_id": rid,
        "api_endpoints": {
            "run": f"GET /repos/{repository.owner}/{repository.repo}/actions/runs/{rid}",
            "jobs": f"GET /repos/{repository.owner}/{repository.repo}/actions/runs/{rid}/jobs",
            "logs_zip": f"GET /repos/{repository.owner}/{repository.repo}/actions/runs/{rid}/logs",
        },
        "gh_cli_commands": [
            f"gh run view {shlex.quote(rid)} --repo {shlex.quote(repository.full_name)} --log-failed",
            f"gh run view {shlex.quote(rid)} --repo {shlex.quote(repository.full_name)} --json conclusion,event,headBranch,jobs,status,url",
        ],
        "notes": [
            "MiniCodex does not fetch network logs in this preview tool.",
            "Paste failed log output into summarize_github_ci_log for local analysis.",
        ],
    }
    return truncate("GitHub CI fetch preview:\n" + to_pretty_json(data), max_chars)


def _safe_json_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-/]", "-", (value or fallback).strip())
    return name.strip(".-/") or fallback


def generate_github_app_manifest(
    root: Path,
    *,
    app_name: str = "MiniCodex Agent",
    webhook_url: str = "",
    output_path: str = ".github/minicodex-app-manifest.json",
    overwrite: bool = False,
    dry_run: bool = False,
    max_chars: int = 16000,
) -> str:
    """Create a GitHub App manifest template for a MiniCodex PR agent."""

    raw_path = (output_path or ".github/minicodex-app-manifest.json").strip()
    if raw_path.startswith(".github/"):
        rel_path = ".github/" + _safe_json_name(
            raw_path.removeprefix(".github/"), "minicodex-app-manifest.json"
        )
    else:
        rel_path = ".github/" + _safe_json_name(raw_path, "minicodex-app-manifest.json")
    path = (root / rel_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return "GitHub App manifest path is outside the project root."
    manifest = {
        "name": app_name.strip() or "MiniCodex Agent",
        "url": "https://github.com/minicodex-agent/minicodex-agent",
        "hook_attributes": {
            "url": webhook_url.strip() or "https://example.com/minicodex/github/webhook"
        },
        "redirect_url": "https://github.com/settings/apps",
        "callback_urls": [],
        "public": False,
        "default_permissions": {
            "actions": "read",
            "checks": "read",
            "contents": "write",
            "issues": "write",
            "metadata": "read",
            "pull_requests": "write",
        },
        "default_events": [
            "check_suite",
            "issue_comment",
            "pull_request",
            "pull_request_review_comment",
            "workflow_run",
        ],
        "minicodex_security_notes": [
            "Install this App only on trusted repositories or run MiniCodex in untrusted-workspace mode.",
            "Use least-privilege repository access and rotate private keys regularly.",
            "Webhook handlers must verify X-Hub-Signature-256 before parsing events.",
        ],
    }
    data = {"path": str(path.relative_to(root)), "manifest": manifest, "dry_run": dry_run}
    if dry_run:
        return truncate("GitHub App manifest dry-run:\n" + to_pretty_json(data), max_chars)
    if path.exists() and not overwrite:
        return f"GitHub App manifest already exists: {path.relative_to(root)}. Re-run with overwrite=true."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_pretty_json(manifest) + "\n", encoding="utf-8")
    return truncate("GitHub App manifest written:\n" + to_pretty_json(data), max_chars)


_WEBHOOK_SERVER_TEMPLATE = """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PREFIX = "/minicodex"


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    if not secret or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + digest, signature)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        secret = os.environ.get("MINICODEX_GITHUB_WEBHOOK_SECRET", "")
        signature = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(secret, body, signature):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"invalid signature")
            return
        event = self.headers.get("X-GitHub-Event", "")
        payload = json.loads(body.decode("utf-8"))
        comment = ((payload.get("comment") or {}).get("body") or "").strip()
        result = {"event": event, "accepted": False, "recommended_cli": []}
        if event == "issue_comment" and comment.startswith(PREFIX):
            result["accepted"] = True
            result["recommended_cli"] = ["minicodex", comment, "--root", ".", "--dry-run", "--safety-profile", "strict"]
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if not os.environ.get("MINICODEX_GITHUB_WEBHOOK_SECRET"):
        raise SystemExit("Set MINICODEX_GITHUB_WEBHOOK_SECRET before starting the webhook server.")
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
"""


def init_github_webhook_server(
    root: Path,
    *,
    output_path: str = "scripts/minicodex_github_webhook.py",
    overwrite: bool = False,
    dry_run: bool = False,
    max_chars: int = 16000,
) -> str:
    """Write a minimal signed GitHub webhook listener scaffold."""

    rel = output_path.strip() or "scripts/minicodex_github_webhook.py"
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return "GitHub webhook server path is outside the project root."
    data = {
        "path": str(candidate.relative_to(root)),
        "dry_run": dry_run,
        "bytes": len(_WEBHOOK_SERVER_TEMPLATE.encode("utf-8")),
    }
    if dry_run:
        data["preview"] = _WEBHOOK_SERVER_TEMPLATE[:2400]
        return truncate("GitHub webhook server dry-run:\n" + to_pretty_json(data), max_chars)
    if candidate.exists() and not overwrite:
        return f"GitHub webhook server already exists: {candidate.relative_to(root)}. Re-run with overwrite=true."
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(_WEBHOOK_SERVER_TEMPLATE, encoding="utf-8")
    candidate.chmod(0o755)
    return truncate("GitHub webhook server written:\n" + to_pretty_json(data), max_chars)


def fetch_github_ci_log(
    root: Path,
    *,
    owner: str = "",
    repo: str = "",
    run_id: str = "",
    summarize: bool = True,
    max_log_chars: int = 50000,
    timeout: int = 30,
    max_chars: int = 20000,
) -> str:
    """Fetch GitHub Actions run metadata, jobs, and logs through the REST API."""

    if not run_id.strip():
        return "GITHUB CI FETCH BLOCK: run_id is required for real log fetching."
    if not get_github_token():
        return "GITHUB CI FETCH BLOCK: GITHUB_TOKEN or GH_TOKEN is required."
    run = fetch_github_actions_run_api(
        root, owner=owner, repo=repo, run_id=run_id.strip(), timeout=timeout
    )
    jobs = fetch_github_actions_jobs_api(
        root, owner=owner, repo=repo, run_id=run_id.strip(), timeout=timeout
    )
    log_status, raw, headers = fetch_github_actions_logs_zip_api(
        root, owner=owner, repo=repo, run_id=run_id.strip(), timeout=timeout
    )
    extracted: list[dict[str, str]] = []
    combined = ""
    if log_status == 200 and raw:
        try:
            with zipfile.ZipFile(BytesIO(raw)) as zf:
                for info in zf.infolist()[:50]:
                    if info.is_dir():
                        continue
                    text = zf.read(info.filename).decode("utf-8", errors="replace")
                    remaining = max(0, max_log_chars - len(combined))
                    if remaining <= 0:
                        break
                    combined += f"\n--- {info.filename} ---\n" + text[:remaining]
                    extracted.append({"path": info.filename, "bytes": str(info.file_size)})
        except zipfile.BadZipFile:
            combined = raw.decode("utf-8", errors="replace")[:max_log_chars]
            extracted.append({"path": "raw-response", "bytes": str(len(raw))})
    summary = (
        summarize_github_ci_log(
            root,
            output=combined,
            workflow_name=str((run.data or {}).get("name", "")),
            max_chars=max_chars,
        )
        if summarize and combined
        else ""
    )
    data = {
        "ok": bool(run.ok and jobs.ok and log_status == 200),
        "run": {"status": run.status, "ok": run.ok, "data": run.data},
        "jobs": {
            "status": jobs.status,
            "ok": jobs.ok,
            "total_count": (jobs.data or {}).get("total_count"),
        },
        "logs": {
            "status": log_status,
            "headers": {k: headers.get(k, "") for k in ("content-type", "content-length")},
            "files": extracted,
        },
        "summary": summary,
    }
    return truncate("GitHub CI fetched log summary:\n" + to_pretty_json(data), max_chars)


def execute_commit_push_workflow(
    root: Path,
    *,
    branch: str = "",
    commit_message: str = "",
    remote: str = "origin",
    include_push: bool = False,
    dry_run: bool = True,
    timeout: int = 60,
    max_chars: int = 16000,
) -> str:
    """Execute a local git branch/add/commit workflow and optionally push."""

    safe_branch = (
        re.sub(r"[^A-Za-z0-9_./-]", "-", branch.strip()) if branch.strip() else "minicodex/changes"
    )
    safe_branch = safe_branch.strip("./") or "minicodex/changes"
    message = commit_message.strip() or "Apply MiniCodex changes"
    if dry_run:
        return prepare_commit_push_plan(
            root,
            branch=safe_branch,
            commit_message=message,
            remote=remote,
            include_push=include_push,
            max_chars=max_chars,
        )
    commands: list[list[str]] = [
        ["git", "switch", "-c", safe_branch],
        ["git", "add", "--", "."],
        ["git", "commit", "-m", message],
    ]
    if include_push:
        commands.append(["git", "push", "-u", remote or "origin", safe_branch])
    results: list[dict[str, Any]] = []
    for cmd in commands:
        proc = subprocess.run(
            cmd,
            cwd=root,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        results.append(
            {
                "command": cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        )
        if proc.returncode != 0:
            if cmd[:3] == ["git", "switch", "-c"]:
                retry = subprocess.run(
                    ["git", "switch", safe_branch],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
                results.append(
                    {
                        "command": ["git", "switch", safe_branch],
                        "returncode": retry.returncode,
                        "stdout": retry.stdout[-4000:],
                        "stderr": retry.stderr[-4000:],
                    }
                )
                if retry.returncode == 0:
                    continue
            break
    return truncate(
        "GitHub branch/commit/push execution:\n"
        + to_pretty_json(
            {"target_branch": safe_branch, "include_push": include_push, "results": results}
        ),
        max_chars,
    )


def resolve_review_comments(
    root: Path,
    *,
    comments: list[dict[str, Any]] | None = None,
    comments_json: str = "",
    post: bool = False,
    pull_number: int = 0,
    owner: str = "",
    repo: str = "",
    max_chars: int = 16000,
) -> str:
    """Group PR review comments and prepare resolution replies."""

    parsed: list[dict[str, Any]] = []
    if comments_json.strip():
        try:
            raw = json.loads(comments_json)
            if isinstance(raw, list):
                parsed = [item for item in raw if isinstance(item, dict)]
        except json.JSONDecodeError as exc:
            return f"Review comment resolver input is not valid JSON: {exc}"
    if comments:
        parsed.extend([item for item in comments if isinstance(item, dict)])
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in parsed:
        path = str(item.get("path") or item.get("file") or "general")
        groups.setdefault(path, []).append(item)
    resolutions = []
    for path, items in sorted(groups.items()):
        body = "MiniCodex reviewed this thread. Suggested resolution:\n" + "\n".join(
            f"- {str(i.get('body') or i.get('comment') or '')[:240]}" for i in items[:8]
        )
        resolutions.append(
            {"path": path, "comment_count": len(items), "reply_body": body, "status": "planned"}
        )
    data = {
        "ok": True,
        "post_requested": post,
        "pull_number": pull_number,
        "owner": owner,
        "repo": repo,
        "repository": github_context(root),
        "resolution_count": len(resolutions),
        "resolutions": resolutions,
        "notes": [
            "Posting review comments requires create_github_review_comment and manual approval.",
            "This resolver groups comments by file and drafts conservative replies; it does not mark GitHub threads resolved through GraphQL.",
        ],
    }
    return truncate("GitHub review comment resolver:\n" + to_pretty_json(data), max_chars)


def prepare_github_artifact_upload(
    root: Path,
    *,
    workflow_name: str = DEFAULT_MINICODEX_WORKFLOW,
    artifact_name: str = "minicodex-artifacts",
    paths: list[str] | None = None,
    max_chars: int = 12000,
) -> str:
    """Render a GitHub Actions upload-artifact step for MiniCodex outputs."""

    clean_paths = [str(p).strip() for p in (paths or []) if str(p).strip()] or [
        ".minicodex/runs",
        ".minicodex/review_bundles",
        ".minicodex/agent_workspaces/*/changes.diff",
        ".minicodex/agent_workspaces/*/manifest.json",
    ]
    step = {
        "name": "Upload MiniCodex artifacts",
        "if": "always()",
        "uses": "actions/upload-artifact@v4",
        "with": {
            "name": artifact_name.strip() or "minicodex-artifacts",
            "path": "\n".join(clean_paths),
            "if-no-files-found": "ignore",
            "retention-days": 7,
        },
    }
    workflow_path = str(
        (root / WORKFLOW_DIR / _safe_workflow_name(workflow_name)).relative_to(root)
    )
    return truncate(
        "GitHub artifact upload step:\n"
        + to_pretty_json({"workflow_path": workflow_path, "step": step}),
        max_chars,
    )
