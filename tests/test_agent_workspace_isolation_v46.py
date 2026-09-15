from __future__ import annotations

import json
from pathlib import Path

from minicodex_agent.config import AgentConfig
from minicodex_agent.workspace_isolation import (
    apply_workspace_changes,
    cleanup_agent_workspace,
    create_agent_workspace,
    finalize_agent_workspace,
)


def test_isolated_agent_workspace_does_not_mutate_original_and_filters_secrets(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")

    session = create_agent_workspace(
        tmp_path,
        mode="isolated",
        keep_workspace=True,
        max_file_bytes=2_000_000,
    )
    try:
        assert session.active_root != tmp_path
        assert (session.active_root / "app.py").exists()
        assert not (session.active_root / ".env").exists()

        (session.active_root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        assert (tmp_path / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"

        finalize_agent_workspace(session, max_diff_chars=4000)
        assert [change.path for change in session.changes] == ["app.py"]
        assert "-VALUE = 1" in session.diff_text
        assert "+VALUE = 2" in session.diff_text
        assert session.diff_path and session.diff_path.exists()
        manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        assert manifest["change_count"] == 1
    finally:
        cleanup_agent_workspace(session)


def test_apply_workspace_changes_syncs_back_only_after_explicit_apply(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("name = 'old'\n", encoding="utf-8")
    session = create_agent_workspace(
        tmp_path, mode="isolated", keep_workspace=True, max_file_bytes=2_000_000
    )
    try:
        (session.active_root / "pkg" / "mod.py").write_text("name = 'new'\n", encoding="utf-8")
        (session.active_root / "pkg" / "extra.py").write_text("created = True\n", encoding="utf-8")
        finalize_agent_workspace(session)
        assert (tmp_path / "pkg" / "mod.py").read_text(encoding="utf-8") == "name = 'old'\n"
        result = apply_workspace_changes(session)
        assert "modified pkg/mod.py" in result
        assert "created pkg/extra.py" in result
        assert (tmp_path / "pkg" / "mod.py").read_text(encoding="utf-8") == "name = 'new'\n"
        assert (tmp_path / "pkg" / "extra.py").exists()
    finally:
        cleanup_agent_workspace(session)


def test_agent_config_has_agent_workspace_defaults(tmp_path: Path) -> None:
    config = AgentConfig(root=tmp_path, model="stub", provider="stub")
    assert config.agent_workspace_mode == "direct"
    assert config.agent_workspace_apply == "never"
    assert config.agent_workspace_max_file_bytes > 0
