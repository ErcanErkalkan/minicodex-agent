from minicodex_agent.release_tools import (
    build_release_checklist,
    project_health_report,
    write_release_notes,
)


def test_build_release_checklist_and_health_report(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")

    checklist = build_release_checklist(tmp_path)
    health = project_health_report(tmp_path)

    assert "1.2.3" in checklist
    assert "MiniCodex release checklist" in checklist
    assert "MiniCodex project health report" in health
    assert '"readme": true' in health


def test_write_release_notes(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n', encoding="utf-8"
    )

    result = write_release_notes(tmp_path)

    assert "Release notes written" in result
    assert (tmp_path / "RELEASE_NOTES.md").exists()
    assert "1.0.0" in (tmp_path / "RELEASE_NOTES.md").read_text(encoding="utf-8")
