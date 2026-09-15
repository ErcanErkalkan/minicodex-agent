"""GitHub-helper and GitHub API tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.github_api import (
    GitHubIntegrationError,
    create_github_issue_api,
    create_github_pr_api,
    create_github_review_comment_api,
    render_github_api_preview,
)
from minicodex_agent.github_integration import (
    detect_github_workflows,
    execute_commit_push_workflow,
    fetch_github_ci_log,
    generate_github_app_manifest,
    github_ci_fetch_preview,
    init_github_action,
    init_github_webhook_server,
    parse_pr_comment_command,
    prepare_commit_push_plan,
    prepare_github_artifact_upload,
    resolve_review_comments,
    summarize_github_ci_log,
)
from minicodex_agent.github_tools import prepare_github_issue, prepare_github_pr
from minicodex_agent.secret_scanner import scan_secrets
from minicodex_agent.tool_registry import ToolSpec, register_tools
from minicodex_agent.tools.context import ToolContext


def _scan_secrets_before_pr_if_enabled(ctx: ToolContext) -> str:
    """Return a blocking/nonblocking PR secret-scan message."""

    if not getattr(ctx.config, "scan_secrets_before_pr", True):
        return ""
    report = scan_secrets(
        ctx.config.root,
        start_path=".",
        max_files=1000,
        max_bytes_per_file=600000,
        max_findings=50,
        minimum_severity="high",
        max_chars=ctx.config.max_observation_chars,
    )
    if "No likely secrets found" in report:
        return "SECRET SCAN BEFORE PR: passed; no high/critical findings.\n"
    return (
        "SECRET SCAN BEFORE PR: BLOCKED because high/critical findings were reported. "
        "Review or re-run with --no-scan-secrets-before-pr only if this is intentional.\n" + report
    )


def _labels(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(label) for label in value]


def _github_write_enabled(ctx: ToolContext) -> bool:
    return bool(getattr(ctx.config, "allow_github_api_writes", False))


def _confirm_github_write(ctx: ToolContext, question: str) -> bool:
    # GitHub writes are external side effects. They always require a human
    # confirmation, even when MiniCodex is running with approval=auto.
    return ctx.confirm(question, force_manual=True)


def handle_prepare_github_pr(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    secret_note = _scan_secrets_before_pr_if_enabled(ctx)
    if secret_note.startswith("SECRET SCAN BEFORE PR: BLOCKED"):
        return secret_note
    result = prepare_github_pr(
        ctx.config.root,
        title=str(args.get("title", "")),
        body=str(args.get("body", "")),
        base=str(args.get("base", "")),
        draft=bool(args.get("draft", True)),
        max_chars=ctx.config.max_observation_chars,
    )
    return (secret_note + "\n" if secret_note else "") + result


def handle_prepare_github_issue(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return prepare_github_issue(
        ctx.config.root,
        title=str(args["title"]),
        body=str(args["body"]),
        labels=_labels(args.get("labels", [])),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_create_github_issue(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    title = str(args["title"]).strip()
    body = str(args["body"]).strip()
    labels = _labels(args.get("labels", []))
    owner = str(args.get("owner", ""))
    repo = str(args.get("repo", ""))
    dry_run = bool(args.get("dry_run", False)) or ctx.config.dry_run
    try:
        preview = render_github_api_preview(
            ctx.config.root,
            kind="issue",
            title=title,
            body=body,
            labels=labels,
            owner=owner,
            repo=repo,
            max_chars=ctx.config.max_observation_chars,
        )
    except GitHubIntegrationError as exc:
        return f"GITHUB API BLOCK: {exc}"

    if dry_run:
        return "GITHUB API DRY RUN: issue would be created with this request.\n" + preview

    if not _github_write_enabled(ctx):
        return (
            "GITHUB API BLOCK: real GitHub API writes are disabled. "
            "Re-run with --allow-github-api-writes or set allow_github_api_writes=true in .minicodex/config.json.\n\n"
            + preview
        )

    if not _confirm_github_write(
        ctx, "GitHub issue oluşturulacak. Harici GitHub API yazma işlemini onaylıyor musun?"
    ):
        return "GitHub issue creation rejected by user.\n\n" + preview

    try:
        result = create_github_issue_api(
            ctx.config.root,
            title=title,
            body=body,
            labels=labels,
            owner=owner,
            repo=repo,
            timeout=ctx.config.model_timeout_seconds,
        )
    except GitHubIntegrationError as exc:
        return f"GITHUB API ERROR: {exc}"

    if result.ok:
        url = result.data.get("html_url") or result.data.get("url") or ""
        return (
            "GitHub issue created successfully.\n"
            + (f"URL: {url}\n" if url else "")
            + result.render(max_chars=ctx.config.max_observation_chars)
        )
    return "GitHub issue creation failed.\n" + result.render(
        max_chars=ctx.config.max_observation_chars
    )


def handle_create_github_pr(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    title = str(args["title"]).strip()
    body = str(args["body"]).strip()
    base = str(args.get("base", "main"))
    head = str(args.get("head", ""))
    draft = bool(args.get("draft", True))
    owner = str(args.get("owner", ""))
    repo = str(args.get("repo", ""))
    dry_run = bool(args.get("dry_run", False)) or ctx.config.dry_run
    try:
        preview = render_github_api_preview(
            ctx.config.root,
            kind="pull_request",
            title=title,
            body=body,
            base=base,
            head=head,
            draft=draft,
            owner=owner,
            repo=repo,
            max_chars=ctx.config.max_observation_chars,
        )
    except GitHubIntegrationError as exc:
        return f"GITHUB API BLOCK: {exc}"

    secret_note = _scan_secrets_before_pr_if_enabled(ctx)
    if secret_note.startswith("SECRET SCAN BEFORE PR: BLOCKED"):
        return secret_note + "\n\n" + preview

    if dry_run:
        return "GITHUB API DRY RUN: pull request would be created with this request.\n" + preview

    if not _github_write_enabled(ctx):
        return (
            "GITHUB API BLOCK: real GitHub API writes are disabled. "
            "Re-run with --allow-github-api-writes or set allow_github_api_writes=true in .minicodex/config.json.\n\n"
            + preview
        )

    if not _confirm_github_write(
        ctx, "GitHub pull request oluşturulacak. Harici GitHub API yazma işlemini onaylıyor musun?"
    ):
        return "GitHub pull request creation rejected by user.\n\n" + preview

    try:
        result = create_github_pr_api(
            ctx.config.root,
            title=title,
            body=body,
            base=base,
            head=head,
            draft=draft,
            owner=owner,
            repo=repo,
            timeout=ctx.config.model_timeout_seconds,
        )
    except GitHubIntegrationError as exc:
        return f"GITHUB API ERROR: {exc}"

    if result.ok:
        url = result.data.get("html_url") or result.data.get("url") or ""
        return (
            "GitHub pull request created successfully.\n"
            + (f"URL: {url}\n" if url else "")
            + result.render(max_chars=ctx.config.max_observation_chars)
        )
    return "GitHub pull request creation failed.\n" + result.render(
        max_chars=ctx.config.max_observation_chars
    )


def handle_detect_github_workflows(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return detect_github_workflows(
        ctx.config.root,
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_init_github_action(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    overwrite = bool(args.get("overwrite", False))
    if (
        overwrite
        and not ctx.config.dry_run
        and not ctx.confirm("GitHub Actions workflow overwrite edilecek.")
    ):
        return "Kullanıcı init_github_action overwrite işlemini reddetti."
    return init_github_action(
        ctx.config.root,
        workflow_name=str(args.get("workflow_name", "minicodex-agent.yml")),
        overwrite=overwrite,
        dry_run=ctx.config.dry_run or bool(args.get("dry_run", False)),
    )


def handle_parse_pr_comment_command(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return parse_pr_comment_command(
        str(args["comment"]),
        prefix=str(args.get("prefix", "/minicodex")),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_prepare_commit_push_plan(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return prepare_commit_push_plan(
        ctx.config.root,
        branch=str(args.get("branch", "")),
        commit_message=str(args.get("commit_message", "")),
        remote=str(args.get("remote", "origin")),
        include_push=bool(args.get("include_push", True)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_summarize_github_ci_log(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return summarize_github_ci_log(
        ctx.config.root,
        output=str(args.get("output", "")),
        log_path=str(args.get("log_path", "")),
        workflow_name=str(args.get("workflow_name", "")),
        max_chars=int(args.get("max_chars", ctx.config.max_observation_chars)),
    )


def handle_github_ci_fetch_preview(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    return github_ci_fetch_preview(
        ctx.config.root,
        owner=str(args.get("owner", "")),
        repo=str(args.get("repo", "")),
        run_id=str(args.get("run_id", "")),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_generate_github_app_manifest(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    overwrite = bool(args.get("overwrite", False))
    dry_run = ctx.config.dry_run or bool(args.get("dry_run", False))
    if overwrite and not dry_run and not ctx.confirm("GitHub App manifest overwrite edilecek."):
        return "Kullanıcı generate_github_app_manifest overwrite işlemini reddetti."
    return generate_github_app_manifest(
        ctx.config.root,
        app_name=str(args.get("app_name", "MiniCodex Agent")),
        webhook_url=str(args.get("webhook_url", "")),
        output_path=str(args.get("output_path", ".github/minicodex-app-manifest.json")),
        overwrite=overwrite,
        dry_run=dry_run,
        max_chars=ctx.config.max_observation_chars,
    )


def handle_init_github_webhook_server(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    overwrite = bool(args.get("overwrite", False))
    dry_run = ctx.config.dry_run or bool(args.get("dry_run", False))
    if (
        overwrite
        and not dry_run
        and not ctx.confirm("GitHub webhook server scaffold overwrite edilecek.")
    ):
        return "Kullanıcı init_github_webhook_server overwrite işlemini reddetti."
    return init_github_webhook_server(
        ctx.config.root,
        output_path=str(args.get("output_path", "scripts/minicodex_github_webhook.py")),
        overwrite=overwrite,
        dry_run=dry_run,
        max_chars=ctx.config.max_observation_chars,
    )


def handle_fetch_github_ci_log(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    if ctx.config.dry_run or bool(args.get("dry_run", False)):
        return github_ci_fetch_preview(
            ctx.config.root,
            owner=str(args.get("owner", "")),
            repo=str(args.get("repo", "")),
            run_id=str(args.get("run_id", "")),
            max_chars=ctx.config.max_observation_chars,
        )
    if not ctx.config.allow_network_commands and not ctx.config.allow_github_api_writes:
        return (
            "GITHUB CI FETCH BLOCK: real GitHub API reads require --allow-network-commands "
            "or --allow-github-api-writes. Use github_ci_fetch_preview for an offline plan."
        )
    if not _confirm_github_write(
        ctx,
        "GitHub Actions logları GitHub API üzerinden okunacak. Harici network/API erişimini onaylıyor musun?",
    ):
        return "GitHub CI log fetch rejected by user."
    return fetch_github_ci_log(
        ctx.config.root,
        owner=str(args.get("owner", "")),
        repo=str(args.get("repo", "")),
        run_id=str(args.get("run_id", "")),
        summarize=bool(args.get("summarize", True)),
        max_log_chars=int(args.get("max_log_chars", 50000)),
        timeout=int(args.get("timeout", ctx.config.model_timeout_seconds)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_execute_commit_push_workflow(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    include_push = bool(args.get("include_push", False))
    dry_run = ctx.config.dry_run or bool(args.get("dry_run", True))
    if dry_run:
        return execute_commit_push_workflow(
            ctx.config.root,
            branch=str(args.get("branch", "")),
            commit_message=str(args.get("commit_message", "")),
            remote=str(args.get("remote", "origin")),
            include_push=include_push,
            dry_run=True,
            timeout=int(args.get("timeout", 60)),
            max_chars=ctx.config.max_observation_chars,
        )
    if include_push and not ctx.config.allow_github_api_writes:
        return "GIT PUSH BLOCK: include_push=true requires --allow-github-api-writes and manual approval."
    if not _confirm_github_write(
        ctx,
        "Yerel git branch/add/commit işlemi yapılacak"
        + (" ve remote'a push edilecek" if include_push else "")
        + ". Onaylıyor musun?",
    ):
        return "Git commit/push workflow rejected by user."
    return execute_commit_push_workflow(
        ctx.config.root,
        branch=str(args.get("branch", "")),
        commit_message=str(args.get("commit_message", "")),
        remote=str(args.get("remote", "origin")),
        include_push=include_push,
        dry_run=False,
        timeout=int(args.get("timeout", 60)),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_resolve_review_comments(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    comments = args.get("comments")
    clean_comments = comments if isinstance(comments, list) else None
    return resolve_review_comments(
        ctx.config.root,
        comments=clean_comments,  # type: ignore[arg-type]
        comments_json=str(args.get("comments_json", "")),
        post=bool(args.get("post", False)),
        pull_number=int(args.get("pull_number", 0)),
        owner=str(args.get("owner", "")),
        repo=str(args.get("repo", "")),
        max_chars=ctx.config.max_observation_chars,
    )


def handle_prepare_github_artifact_upload(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    paths = args.get("paths")
    clean_paths = [str(item) for item in paths] if isinstance(paths, list) else None
    return prepare_github_artifact_upload(
        ctx.config.root,
        workflow_name=str(args.get("workflow_name", "minicodex-agent.yml")),
        artifact_name=str(args.get("artifact_name", "minicodex-artifacts")),
        paths=clean_paths,
        max_chars=ctx.config.max_observation_chars,
    )


def handle_create_github_review_comment(ctx: ToolContext, args: Mapping[str, Any]) -> str:
    pull_number = int(args.get("pull_number", 0))
    body = str(args.get("body", "")).strip()
    event = str(args.get("event", "COMMENT")).strip().upper() or "COMMENT"
    owner = str(args.get("owner", ""))
    repo = str(args.get("repo", ""))
    dry_run = bool(args.get("dry_run", False)) or ctx.config.dry_run
    preview = {
        "pull_number": pull_number,
        "owner": owner,
        "repo": repo,
        "event": event,
        "body": body,
        "endpoint": f"POST /repos/{{owner}}/{{repo}}/pulls/{pull_number}/reviews",
    }
    if dry_run:
        from minicodex_agent.utils import to_pretty_json

        return "GITHUB API DRY RUN: review comment would be created.\n" + to_pretty_json(preview)
    if not _github_write_enabled(ctx):
        from minicodex_agent.utils import to_pretty_json

        return (
            "GITHUB API BLOCK: review comment writes require --allow-github-api-writes.\n"
            + to_pretty_json(preview)
        )
    if pull_number <= 0:
        return "GITHUB API BLOCK: pull_number must be a positive integer."
    if not _confirm_github_write(
        ctx,
        "GitHub PR review comment oluşturulacak. Harici GitHub API yazma işlemini onaylıyor musun?",
    ):
        return "GitHub review comment creation rejected by user."
    try:
        result = create_github_review_comment_api(
            ctx.config.root,
            pull_number=pull_number,
            body=body,
            event=event,
            owner=owner,
            repo=repo,
            timeout=ctx.config.model_timeout_seconds,
        )
    except GitHubIntegrationError as exc:
        return f"GITHUB API ERROR: {exc}"
    if result.ok:
        url = result.data.get("html_url") or result.data.get("url") or ""
        return (
            "GitHub review comment created successfully.\n"
            + (f"URL: {url}\n" if url else "")
            + result.render(max_chars=ctx.config.max_observation_chars)
        )
    return "GitHub review comment creation failed.\n" + result.render(
        max_chars=ctx.config.max_observation_chars
    )


register_tools(
    [
        ToolSpec(
            "detect_github_workflows",
            ACTION_SPECS["detect_github_workflows"],
            handle_detect_github_workflows,
            plugin="github",
        ),
        ToolSpec(
            "init_github_action",
            ACTION_SPECS["init_github_action"],
            handle_init_github_action,
            plugin="github",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "parse_pr_comment_command",
            ACTION_SPECS["parse_pr_comment_command"],
            handle_parse_pr_comment_command,
            plugin="github",
        ),
        ToolSpec(
            "prepare_commit_push_plan",
            ACTION_SPECS["prepare_commit_push_plan"],
            handle_prepare_commit_push_plan,
            plugin="github",
        ),
        ToolSpec(
            "summarize_github_ci_log",
            ACTION_SPECS["summarize_github_ci_log"],
            handle_summarize_github_ci_log,
            plugin="github",
        ),
        ToolSpec(
            "github_ci_fetch_preview",
            ACTION_SPECS["github_ci_fetch_preview"],
            handle_github_ci_fetch_preview,
            plugin="github",
        ),
        ToolSpec(
            "generate_github_app_manifest",
            ACTION_SPECS["generate_github_app_manifest"],
            handle_generate_github_app_manifest,
            plugin="github",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "init_github_webhook_server",
            ACTION_SPECS["init_github_webhook_server"],
            handle_init_github_webhook_server,
            plugin="github",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "fetch_github_ci_log",
            ACTION_SPECS["fetch_github_ci_log"],
            handle_fetch_github_ci_log,
            plugin="github",
            requires_approval=True,
            risk_level="medium",
        ),
        ToolSpec(
            "execute_commit_push_workflow",
            ACTION_SPECS["execute_commit_push_workflow"],
            handle_execute_commit_push_workflow,
            plugin="github",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "resolve_review_comments",
            ACTION_SPECS["resolve_review_comments"],
            handle_resolve_review_comments,
            plugin="github",
        ),
        ToolSpec(
            "prepare_github_artifact_upload",
            ACTION_SPECS["prepare_github_artifact_upload"],
            handle_prepare_github_artifact_upload,
            plugin="github",
        ),
        ToolSpec(
            "create_github_review_comment",
            ACTION_SPECS["create_github_review_comment"],
            handle_create_github_review_comment,
            plugin="github",
            requires_approval=True,
            risk_level="high",
        ),
        ToolSpec(
            "prepare_github_pr",
            ACTION_SPECS["prepare_github_pr"],
            handle_prepare_github_pr,
            plugin="github",
        ),
        ToolSpec(
            "prepare_github_issue",
            ACTION_SPECS["prepare_github_issue"],
            handle_prepare_github_issue,
            plugin="github",
        ),
        ToolSpec(
            "create_github_pr",
            ACTION_SPECS["create_github_pr"],
            handle_create_github_pr,
            plugin="github",
            requires_approval=True,
            risk_level="high",
            description="Create a GitHub pull request through the GitHub REST API after explicit enablement and manual approval.",
        ),
        ToolSpec(
            "create_github_issue",
            ACTION_SPECS["create_github_issue"],
            handle_create_github_issue,
            plugin="github",
            requires_approval=True,
            risk_level="high",
            description="Create a GitHub issue through the GitHub REST API after explicit enablement and manual approval.",
        ),
    ]
)
