from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility
    import tomli as tomllib

from minicodex_agent import cli
from minicodex_agent.agent import AgentState
from minicodex_agent.code_search import build_dependency_graph, search_code
from minicodex_agent.config import AgentConfig
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.prompts import SYSTEM_PROMPT
from minicodex_agent.run_logger import RunLogger
from minicodex_agent.snapshot_tools import create_snapshot, restore_snapshot
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.tools.control import handle_ask_user
from minicodex_agent.tools.security import handle_run_external_secret_scan


def test_cli_lang_tr_keeps_turkish_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["minicodex", "--lang", "tr", "--root", str(tmp_path), "--provider", "stub", "--no-log"],
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1
    assert "goal gerekli" in capsys.readouterr().out


def test_ask_user_non_interactive_uses_default_answer(tmp_path: Path) -> None:
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        non_interactive=True,
        default_answer="continue",
    )
    state = AgentState(goal="g", project_profile=detect_project(tmp_path))
    ctx = ToolContext(
        config=config,
        state=state,
        logger=RunLogger(tmp_path / "logs", enabled=False),
        confirm_fn=lambda *args, **kwargs: False,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )
    out = handle_ask_user(ctx, {"question": "Proceed?"})
    assert "Non-interactive mode" in out
    assert "continue" in out


def test_system_prompt_uses_generated_action_reference() -> None:
    assert "AUTO-GENERATED ACTION REFERENCE" in SYSTEM_PROMPT
    assert "- read_file:" in SYSTEM_PROMPT
    assert "0b." not in SYSTEM_PROMPT


def test_external_secret_scan_dry_run_selects_available_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = AgentConfig(root=tmp_path, model="stub", provider="stub", dry_run=True)
    state = AgentState(goal="g", project_profile=detect_project(tmp_path))
    ctx = ToolContext(
        config=config,
        state=state,
        logger=RunLogger(tmp_path / "logs", enabled=False),
        confirm_fn=lambda *args, **kwargs: True,
        print_header_fn=lambda title: None,
        ensure_auto_snapshot_before_edit=lambda action, target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )
    monkeypatch.setattr(
        "minicodex_agent.tools.security.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "gitleaks" else None,
    )
    out = handle_run_external_secret_scan(ctx, {"tool": "auto", "path": "."})
    assert "DRY-RUN external secret scan command" in out
    assert "gitleaks detect" in out


def test_snapshot_ignore_metadata_and_pre_restore_backup(tmp_path: Path) -> None:
    (tmp_path / ".minicodex").mkdir()
    (tmp_path / ".minicodex" / "snapshot_ignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("skip\n", encoding="utf-8")
    result = create_snapshot(tmp_path, label="check")
    snapshot_id = result.split("Snapshot created: ", 1)[1].splitlines()[0]
    manifest = json.loads(
        (tmp_path / ".minicodex" / "snapshots" / snapshot_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["snapshot_schema_version"] == 2
    assert manifest["files"][0]["sha256"]
    assert all(item["path"] != "ignored.txt" for item in manifest["files"])
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")
    out = restore_snapshot(tmp_path, snapshot_id, create_restore_backup=True)
    assert "Pre-restore safety snapshot" in out
    assert (tmp_path / "tracked.txt").read_text(encoding="utf-8") == "before\n"


def test_code_search_dependency_graph_and_definition_boost(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "import json\n\ndef calculate_total(items):\n    return sum(items)\n", encoding="utf-8"
    )
    graph = build_dependency_graph(tmp_path)
    assert "json" in graph
    results = search_code(tmp_path, "calculate total")
    assert "calculate_total" in results


def test_pyproject_metadata_and_ci_files_are_professional() -> None:
    project_root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["license"] == "MIT"
    assert data["project"]["authors"][0]["email"]
    assert "Repository" in data["project"]["urls"]
    assert "coding-agent" in data["project"]["keywords"]
    assert (project_root / ".github" / "workflows" / "ci.yml").exists()
    assert (project_root / ".github" / "workflows" / "release.yml").exists()
    assert (project_root / ".github" / "workflows" / "security.yml").exists()
    assert (project_root / ".github" / "dependabot.yml").exists()
