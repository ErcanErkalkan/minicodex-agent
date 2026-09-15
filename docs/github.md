# GitHub integration

MiniCodex includes GitHub-oriented helpers for CI diagnostics, PR workflows, and GitHub App scaffolding.

## Workflow detection

```bash
minicodex --detect-github-workflows --root .
```

## GitHub App manifest and webhook scaffold

```bash
minicodex --generate-github-app-manifest --github-app-name "MiniCodex Agent" --root .
minicodex --init-github-webhook-server --root .
```

Webhook scaffolding is local code generation. Real deployment, secret storage, and GitHub App installation remain manual review steps.

## CI logs and PR review workflows

The GitHub layer supports CI log fetching and review-comment resolution when GitHub API/network options are explicitly enabled. Write operations such as commit/push or review-comment posting are gated and should remain dry-run/preview-first unless the user intentionally enables GitHub writes.

Useful safety posture. `--no-github-api-writes` explicitly disables write operations and overrides any project config value that enabled them:

```bash
minicodex "inspect failing GitHub CI" --root . --approval ask --no-github-api-writes
```

## Actions artifact upload helper

```bash
minicodex --prepare-github-artifact-upload --root .
```

This generates upload-artifact workflow guidance without performing a remote write.
