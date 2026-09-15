from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from minicodex_agent.fs_tools import list_files, read_file
from minicodex_agent.index_tools import index_project
from minicodex_agent.model_client import ModelBudgetExceeded, ModelClient
from minicodex_agent.secret_scanner import redact_secret, scan_secrets
from minicodex_agent.setup_wizard import run_setup_wizard
from minicodex_agent.snapshot_tools import create_snapshot
from minicodex_agent.task_memory import save_task_memory


def test_sensitive_env_files_are_hidden_from_agent_io(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-" + "A" * 32 + "\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=your_api_key_here\n", encoding="utf-8")

    listing = list_files(tmp_path)
    assert ".env.example" in listing
    assert "[FILE] .env " not in listing
    assert "okuma engellendi" in read_file(tmp_path, ".env", 1000)


def test_snapshot_and_index_skip_sensitive_files(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PASSWORD=supersecretpassword\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('safe')\n", encoding="utf-8")

    snapshot = create_snapshot(tmp_path, label="safe")
    snapshot_id = snapshot.split("Snapshot created: ", 1)[1].splitlines()[0]
    manifest = json.loads(
        (tmp_path / ".minicodex" / "snapshots" / snapshot_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert [item["path"] for item in manifest["files"]] == ["app.py"]
    assert any(item["path"] == ".env" for item in manifest["skipped"])

    index = index_project(tmp_path, save=False)
    assert "app.py" in index
    assert ".env" not in index


def test_secret_scan_still_scans_env_but_redacts_multiline_output(tmp_path: Path) -> None:
    key = "sk-" + "B" * 32
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={key}\n", encoding="utf-8")

    report = scan_secrets(tmp_path)
    assert "openai_api_key" in report
    assert key not in report

    output = "before\nPASSWORD=supersecretpassword\nafter\n"
    redacted = redact_secret(output)
    assert "PASSWORD=supe…REDACTED…word" in redacted
    assert "supersecretpassword" not in redacted


def test_dry_run_does_not_write_setup_index_snapshot_or_memory(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('safe')\n", encoding="utf-8")

    setup = run_setup_wizard(tmp_path, provider="stub", dry_run=True)
    assert "DRY-RUN" in setup
    assert not (tmp_path / ".minicodex" / "config.json").exists()

    index = index_project(tmp_path, save=True, dry_run=True)
    assert "DRY-RUN" in index
    assert not (tmp_path / ".minicodex" / "index.json").exists()

    snapshot = create_snapshot(tmp_path, label="dry", dry_run=True)
    assert "DRY-RUN" in snapshot
    assert not (tmp_path / ".minicodex" / "snapshots").exists()

    memory = save_task_memory(tmp_path, goal="g", summary="s", dry_run=True)
    assert "DRY-RUN" in memory
    assert not (tmp_path / ".minicodex" / "memory.jsonl").exists()


class AlwaysFailResponses:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        raise RuntimeError("network down")


class TypeErrorThenSuccessResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "text" in kwargs:
            raise TypeError("text unsupported")
        return SimpleNamespace(
            output_text=json.dumps({"thought": "ok", "action": "finish", "args": {}}),
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def test_failed_provider_attempts_count_against_call_budget() -> None:
    client = ModelClient(
        "test", provider="stub", call_budget=1, max_retries=1, retry_backoff_seconds=0
    )
    fake = SimpleNamespace(responses=AlwaysFailResponses())
    client.provider = "openai"
    client.client = fake

    with pytest.raises(ModelBudgetExceeded):
        client.next_action_text("{}")
    assert fake.responses.calls == 1


def test_openai_fallback_preserves_timeout_and_token_limit_when_only_text_is_unsupported() -> None:
    client = ModelClient(
        "test",
        provider="stub",
        timeout_seconds=9,
        max_output_tokens=512,
        max_retries=0,
        structured_output=True,
    )
    fake = SimpleNamespace(responses=TypeErrorThenSuccessResponses())
    client.provider = "openai"
    client.client = fake

    raw = client.next_action_text("{}")

    assert "finish" in raw
    fallback = fake.responses.calls[-1]
    assert "text" not in fallback
    assert fallback["timeout"] == 9
    assert fallback["max_output_tokens"] == 512


def test_cli_setup_dry_run_does_not_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    from minicodex_agent import cli

    monkeypatch.setattr(
        sys,
        "argv",
        ["minicodex", "--setup", "--root", str(tmp_path), "--provider", "stub", "--dry-run"],
    )
    cli.main()

    assert "DRY-RUN" in capsys.readouterr().out
    assert not (tmp_path / ".minicodex" / "config.json").exists()
    assert not (tmp_path / ".env.example").exists()
