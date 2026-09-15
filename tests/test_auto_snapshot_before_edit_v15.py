from __future__ import annotations

import json
from pathlib import Path

import minicodex_agent.agent as agent_module
from minicodex_agent.agent import AgentState, MiniCodexAgent
from minicodex_agent.config import AgentConfig, apply_project_config
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.project_settings import update_project_config


def _agent(tmp_path: Path, **kwargs):
    config = AgentConfig(
        root=tmp_path,
        model="stub",
        provider="stub",
        approval="auto",
        show_diff=False,
        project_config_enabled=True,
        project_policy_enabled=True,
        log_enabled=False,
        **kwargs,
    )
    return MiniCodexAgent(config), AgentState(goal="test", project_profile=detect_project(tmp_path))


def _snapshot_manifests(root: Path) -> list[Path]:
    return sorted((root / ".minicodex" / "snapshots").glob("*/manifest.json"))


def test_first_write_creates_one_automatic_snapshot_before_edit(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('v1')\n", encoding="utf-8")
    agent, state = _agent(tmp_path)

    first = agent.execute_action(
        state, "write_file", {"path": "app.py", "content": "print('v2')\n"}
    )
    second = agent.execute_action(
        state, "write_file", {"path": "other.py", "content": "print('new')\n"}
    )

    manifests = _snapshot_manifests(tmp_path)
    assert "AUTO SNAPSHOT BEFORE EDIT" in first
    assert "AUTO SNAPSHOT BEFORE EDIT" not in second
    assert len(manifests) == 1
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('v2')\n"
    assert (tmp_path / "other.py").read_text(encoding="utf-8") == "print('new')\n"

    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["label"] == "auto-before-edit"
    assert any(item["path"] == "app.py" for item in manifest["files"])
    snapshot_id = manifest["snapshot_id"]
    assert (manifests[0].parents[0] / "files" / "app.py").read_text(
        encoding="utf-8"
    ) == "print('v1')\n"
    assert snapshot_id in first


def test_dry_run_does_not_create_auto_snapshot(tmp_path: Path):
    agent, state = _agent(tmp_path, dry_run=True)

    result = agent.execute_action(
        state, "write_file", {"path": "app.py", "content": "print('v2')\n"}
    )

    assert "AUTO SNAPSHOT: skipped because dry-run is enabled" in result
    assert not _snapshot_manifests(tmp_path)
    assert not (tmp_path / "app.py").exists()


def test_project_config_can_disable_auto_snapshot(tmp_path: Path):
    update_project_config(tmp_path, {"auto_snapshot_before_edit": False})
    config = apply_project_config(
        AgentConfig(
            root=tmp_path, model="stub", provider="stub", approval="auto", log_enabled=False
        ),
        explicit_options={"provider", "approval"},
    )
    agent = MiniCodexAgent(config)
    state = AgentState(goal="test", project_profile=detect_project(tmp_path))

    result = agent.execute_action(
        state, "write_file", {"path": "app.py", "content": "print('v2')\n"}
    )

    assert "AUTO SNAPSHOT" not in result
    assert not _snapshot_manifests(tmp_path)
    assert (tmp_path / "app.py").exists()


def test_snapshot_failure_requires_manual_confirmation_even_with_auto_approval(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "app.py").write_text("print('v1')\n", encoding="utf-8")
    agent, state = _agent(tmp_path)
    calls: list[tuple[bool, bool]] = []

    def fail_snapshot(*args, **kwargs):
        raise RuntimeError("disk full")

    def deny(question: str, auto_approve: bool, *, force_manual: bool = False) -> bool:
        if not force_manual:
            return True
        calls.append((auto_approve, force_manual))
        return False

    monkeypatch.setattr(agent_module, "create_snapshot", fail_snapshot)
    monkeypatch.setattr(agent_module, "confirm", deny)

    result = agent.execute_action(
        state, "write_file", {"path": "app.py", "content": "print('v2')\n"}
    )

    assert result.startswith("AUTO SNAPSHOT FAILED")
    assert "Edit blocked" in result
    assert calls == [(True, True)]
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('v1')\n"
