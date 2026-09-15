from minicodex_agent.project_settings import (
    init_project_config,
    read_project_config,
    render_project_config,
    update_project_config,
)


def test_project_config_lifecycle(tmp_path):
    defaults = read_project_config(tmp_path)
    assert defaults["default_test_command"] == "auto"
    created = init_project_config(tmp_path)
    assert ".minicodex/config.json" in created
    updated = update_project_config(tmp_path, {"default_safety_profile": "strict"})
    assert "strict" in updated
    config = read_project_config(tmp_path)
    assert config["default_safety_profile"] == "strict"
    assert "MiniCodex project config" in render_project_config(tmp_path)


def test_project_config_accepts_utf8_bom(tmp_path):
    config_dir = tmp_path / ".minicodex"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        '{"preferred_provider":"ollama"}',
        encoding="utf-8-sig",
    )

    config = read_project_config(tmp_path)

    assert config["preferred_provider"] == "ollama"
