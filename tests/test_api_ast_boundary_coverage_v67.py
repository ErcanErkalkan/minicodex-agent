from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from minicodex_agent import ast_patch_tools, github_api, github_integration


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {"content-type": "application/json"}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_github_repository_resolution_and_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "fallback")
    assert github_api.get_github_token() == "fallback"
    assert github_api.parse_github_remote_url("") is None
    assert github_api.parse_github_remote_url("not configured") is None
    assert github_api.parse_github_remote_url("https://example.test/o/r.git") is None
    assert github_api.parse_github_remote_url("git@github.com:owner/repo.git").full_name == (
        "owner/repo"
    )
    assert github_api.resolve_github_repository(tmp_path, "owner", "repo.git").full_name == (
        "owner/repo"
    )

    monkeypatch.setattr(
        github_api,
        "github_context",
        lambda root: {"remote_origin": "https://github.com/from/remote.git", "branch": "unknown"},
    )
    assert github_api.resolve_github_repository(tmp_path).full_name == "from/remote"
    assert github_api.current_branch(tmp_path) == ""

    monkeypatch.setattr(
        github_api, "github_context", lambda root: {"remote_origin": "", "branch": "main"}
    )
    with pytest.raises(github_api.GitHubIntegrationError):
        github_api.resolve_github_repository(tmp_path)
    assert github_api.current_branch(tmp_path) == "main"


def test_github_json_api_request_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(github_api.GitHubIntegrationError):
        github_api.github_api_request("POST", "/demo", token="")

    monkeypatch.setattr(
        github_api.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(b'["one", "two"]', status=201),
    )
    result = github_api.github_api_request("post", "/demo", token="token", payload={"value": 1})
    assert result.ok is True
    assert result.status == 201
    assert result.data == {"response": ["one", "two"]}

    http_error = urllib.error.HTTPError(
        "https://api.github.test/demo",
        422,
        "invalid",
        {},
        io.BytesIO(b'{"message":"invalid"}'),
    )
    monkeypatch.setattr(
        github_api.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(http_error),
    )
    result = github_api.github_api_request("POST", "/demo", token="token")
    assert result.ok is False
    assert result.status == 422
    assert result.data["message"] == "invalid"

    invalid_json_error = urllib.error.HTTPError(
        "https://api.github.test/demo",
        500,
        "invalid",
        {},
        io.BytesIO(b"not-json"),
    )
    monkeypatch.setattr(
        github_api.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(invalid_json_error),
    )
    assert github_api.github_api_request("GET", "/demo", token="token").data == {
        "error": "not-json"
    }

    monkeypatch.setattr(
        github_api.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(github_api.GitHubIntegrationError, match="network error"):
        github_api.github_api_request("GET", "/demo", token="token")


def test_github_raw_api_request_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(github_api.GitHubIntegrationError):
        github_api.github_api_raw_request("GET", "/demo", token="")

    monkeypatch.setattr(
        github_api.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(
            b"archive", status=200, headers={"content-type": "application/zip"}
        ),
    )
    status, body, headers = github_api.github_api_raw_request("GET", "/demo", token="token")
    assert (status, body, headers["content-type"]) == (200, b"archive", "application/zip")

    error = urllib.error.HTTPError(
        "https://api.github.test/demo",
        404,
        "missing",
        {"x-test": "yes"},
        io.BytesIO(b"missing"),
    )
    monkeypatch.setattr(
        github_api.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(error),
    )
    status, body, headers = github_api.github_api_raw_request("GET", "/demo", token="token")
    assert status == 404
    assert body == b"missing"
    assert headers["x-test"] == "yes"

    monkeypatch.setattr(
        github_api.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(github_api.GitHubIntegrationError):
        github_api.github_api_raw_request("GET", "/demo", token="token")


def test_github_api_convenience_calls_build_expected_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    result = github_api.GitHubApiResult(True, 200, {}, "ok")

    def fake_request(method: str, path: str, **kwargs: Any) -> github_api.GitHubApiResult:
        calls.append((method, path, kwargs))
        return result

    monkeypatch.setattr(github_api, "github_api_request", fake_request)
    monkeypatch.setattr(
        github_api, "github_api_raw_request", lambda *args, **kwargs: (200, b"zip", {})
    )
    monkeypatch.setattr(github_api, "current_branch", lambda root: "feature")

    github_api.create_github_issue_api(
        tmp_path,
        title=" issue ",
        body=" body ",
        labels=[" bug ", ""],
        owner="owner",
        repo="repo",
        token="token",
    )
    github_api.create_github_pr_api(
        tmp_path,
        title="",
        body="",
        owner="owner",
        repo="repo",
        token="token",
    )
    github_api.fetch_github_actions_run_api(
        tmp_path, run_id="1", owner="owner", repo="repo", token="token"
    )
    github_api.fetch_github_actions_jobs_api(
        tmp_path, run_id="1", owner="owner", repo="repo", token="token"
    )
    assert (
        github_api.fetch_github_actions_logs_zip_api(
            tmp_path, run_id="1", owner="owner", repo="repo", token="token"
        )[1]
        == b"zip"
    )
    github_api.create_github_review_comment_api(
        tmp_path,
        pull_number=3,
        body="review",
        comments=[{"path": "app.py", "body": "note"}],
        owner="owner",
        repo="repo",
        token="token",
    )

    assert calls[0][1].endswith("/issues")
    assert calls[0][2]["payload"]["labels"] == ["bug"]
    assert calls[1][2]["payload"]["head"] == "feature"
    assert calls[-1][1].endswith("/pulls/3/reviews")

    monkeypatch.setattr(github_api, "current_branch", lambda root: "")
    with pytest.raises(github_api.GitHubIntegrationError, match="head branch"):
        github_api.create_github_pr_api(
            tmp_path, title="t", body="b", owner="owner", repo="repo", token="token"
        )


def test_github_api_preview_variants(tmp_path: Path) -> None:
    issue = json.loads(
        github_api.render_github_api_preview(
            tmp_path,
            kind="issue",
            title="issue",
            body="body",
            labels=["bug"],
            owner="owner",
            repo="repo",
        )
    )
    assert issue["payload"]["labels"] == ["bug"]

    pull = json.loads(
        github_api.render_github_api_preview(
            tmp_path,
            kind="pull_request",
            title="",
            body="",
            owner="owner",
            repo="repo",
        )
    )
    assert pull["payload"]["head"] == "<current-branch>"
    with pytest.raises(ValueError):
        github_api.render_github_api_preview(
            tmp_path,
            kind="unknown",
            title="",
            body="",
            owner="owner",
            repo="repo",
        )


def test_github_workflow_parser_covers_fallbacks_and_inline_triggers(tmp_path: Path) -> None:
    empty = github_integration.detect_github_workflows(tmp_path)
    assert "Add a GitHub Actions workflow" in empty

    assert github_integration._safe_workflow_name("feature workflow") == "feature-workflow.yml"
    assert github_integration._extract_workflow_name("jobs:\n", "fallback") == "fallback"
    assert github_integration._extract_workflow_name("name:\njobs:\n", "fallback") == "fallback"
    assert github_integration._extract_on_triggers("on: [push, pull_request]\njobs:\n") == [
        "pull_request",
        "push",
    ]
    nested_triggers = github_integration._extract_on_triggers(
        "on:\n  # comment\n\n  workflow_dispatch:\njobs:\n  test:\n"
    )
    assert nested_triggers == ["workflow_dispatch"]
    assert github_integration._extract_jobs("jobs:\n  test:\nname: later\n  ignored:\n") == ["test"]

    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    report = github_integration.detect_github_workflows(tmp_path)
    assert "do not appear to expose a MiniCodex" in report


def test_ast_semantic_plans_and_rename_error_paths(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("value = 1\n", encoding="utf-8")

    invalid_plan = json.loads(
        ast_patch_tools.plan_semantic_edit(
            tmp_path,
            operation="rename_symbol",
            symbol="bad-name",
            new_name="also-bad",
            language="python",
        )
    )
    assert invalid_plan["ok"] is False
    assert len(invalid_plan["errors"]) == 2

    cleanup_plan = json.loads(
        ast_patch_tools.plan_semantic_edit(tmp_path, operation="cleanup_dead_code")
    )
    assert "cleanup_dead_code" in cleanup_plan["recommended_tools"]
    assert cleanup_plan["warnings"]

    unknown_plan = json.loads(ast_patch_tools.plan_semantic_edit(tmp_path, operation="unknown"))
    assert unknown_plan["warnings"]

    for old_name, new_name, message in (
        ("bad-name", "new", "Invalid source"),
        ("old", "bad-name", "Invalid target"),
        ("same", "same", "identical"),
        ("missing", "new", "not found"),
    ):
        result = json.loads(
            ast_patch_tools.rename_symbol_semantic(
                tmp_path,
                old_name=old_name,
                new_name=new_name,
                language="python",
            )
        )
        assert message.lower() in " ".join(result["errors"]).lower()


@pytest.mark.parametrize(
    ("name", "content", "language", "first", "second"),
    [
        (
            "demo.ts",
            "import z from 'z';\nimport a from 'a';\nconsole.log(a, z);\n",
            "typescript",
            "import a",
            "import z",
        ),
        (
            "Demo.java",
            "import z.Type;\nimport a.Type;\nclass Demo {}\n",
            "java",
            "import a",
            "import z",
        ),
        (
            "demo.rs",
            "use z::Type;\nuse a::Type;\nfn main() {}\n",
            "rust",
            "use a",
            "use z",
        ),
    ],
)
def test_ast_import_organization_for_multiple_languages(
    tmp_path: Path,
    name: str,
    content: str,
    language: str,
    first: str,
    second: str,
) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")

    result = json.loads(
        ast_patch_tools.organize_imports(
            tmp_path,
            path=name,
            language=language,
            preview_only=False,
        )
    )

    assert result["ok"] is True
    updated = path.read_text(encoding="utf-8")
    assert updated.index(first) < updated.index(second)


def test_ast_import_and_format_no_change_error_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plain = tmp_path / "plain.py"
    plain.write_text('"""doc"""\n\nvalue = 1\n', encoding="utf-8")
    no_changes = json.loads(
        ast_patch_tools.organize_imports(
            tmp_path, path="plain.py", language="python", preview_only=True
        )
    )
    assert no_changes["ok"] is False

    missing = json.loads(ast_patch_tools.format_and_verify(tmp_path, path="missing.py"))
    assert missing["ok"] is False

    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    syntax = json.loads(
        ast_patch_tools.format_and_verify(
            tmp_path,
            path="bad.py",
            run_formatter=True,
            formatter="missing-formatter",
            verify_syntax=True,
        )
    )
    assert syntax["syntax_ok"] is False
    assert syntax["warnings"]

    good = tmp_path / "good.py"
    good.write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(ast_patch_tools.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        ast_patch_tools.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failed"),
    )
    formatted = json.loads(
        ast_patch_tools.format_and_verify(
            tmp_path,
            path="good.py",
            run_formatter=True,
            formatter="ruff",
        )
    )
    assert formatted["formatter_ran"] is True
    assert formatted["errors"]


def test_ast_cleanup_preserves_referenced_and_dunder_symbols(tmp_path: Path) -> None:
    path = tmp_path / "demo.py"
    path.write_text(
        "@staticmethod\n"
        "def _unused():\n"
        "    return 1\n\n"
        "def __special__():\n"
        "    return 2\n\n"
        "def used():\n"
        "    return 3\n\n"
        "print(used())\n",
        encoding="utf-8",
    )

    result = json.loads(
        ast_patch_tools.cleanup_dead_code(
            tmp_path,
            names=("_unused", "__special__", "used"),
            preview_only=False,
        )
    )

    assert result["ok"] is True
    updated = path.read_text(encoding="utf-8")
    assert "_unused" not in updated
    assert "@staticmethod" not in updated
    assert "__special__" in updated
    assert "used()" in updated
