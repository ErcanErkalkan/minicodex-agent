from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from minicodex_agent import cli
from minicodex_agent.project_settings import update_project_config


def test_documented_project_health_cli_flag(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minicodex",
            "--project-health",
            "--root",
            str(tmp_path),
            "--provider",
            "stub",
            "--no-log",
        ],
    )

    cli.main()

    out = capsys.readouterr().out.lower()
    assert "project health" in out
    assert "detected_test_command" in out


def test_legacy_list_eval_tasks_alias_matches_list_evals(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minicodex",
            "--list-eval-tasks",
            "--root",
            str(tmp_path),
            "--provider",
            "stub",
            "--no-log",
        ],
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert "tasks" in payload


def test_no_github_api_writes_overrides_project_config(monkeypatch: pytest.MonkeyPatch, tmp_path):
    update_project_config(tmp_path, {"allow_github_api_writes": True})
    seen = {}

    class FakeAgent:
        def __init__(self, config):
            seen["allow_github_api_writes"] = config.allow_github_api_writes

        def run(self, goal):
            return SimpleNamespace(exit_code=0)

    monkeypatch.setattr(cli, "MiniCodexAgent", FakeAgent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minicodex",
            "inspect",
            "--root",
            str(tmp_path),
            "--provider",
            "stub",
            "--no-log",
            "--no-github-api-writes",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert int(excinfo.value.code) == 0
    assert seen == {"allow_github_api_writes": False}


def test_final_readiness_forwards_verification_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    seen = {}

    def fake_report(root, **kwargs):
        seen.update(kwargs)
        return "ready"

    monkeypatch.setattr(cli, "final_readiness_report", fake_report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minicodex",
            "--final-readiness",
            "--final-readiness-run-verification-tools",
            "--final-readiness-verification-timeout",
            "777",
            "--root",
            str(tmp_path),
            "--provider",
            "stub",
            "--no-log",
        ],
    )

    cli.main()

    assert capsys.readouterr().out.strip() == "ready"
    assert seen["run_verification_tools"] is True
    assert seen["verification_timeout"] == 777
