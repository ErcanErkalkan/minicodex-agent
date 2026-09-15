from minicodex_agent.project_policy import read_project_policy
from minicodex_agent.project_settings import read_project_config
from minicodex_agent.setup_wizard import run_setup_wizard


def test_run_setup_wizard_creates_expected_files(tmp_path):
    result = run_setup_wizard(
        tmp_path,
        provider="stub",
        approval="ask",
        safety_profile="strict",
        test_command="pytest -q",
    )

    assert "setup wizard completed" in result
    assert (tmp_path / ".minicodex" / "config.json").exists()
    assert (tmp_path / ".minicodex" / "policy.json").exists()
    assert (tmp_path / ".minicodex" / "plugins" / "local-project-defaults.json").exists()
    assert (tmp_path / ".env.example").exists()

    config = read_project_config(tmp_path)
    assert config["preferred_provider"] == "stub"
    assert config["default_safety_profile"] == "strict"
    assert config["default_test_command"] == "pytest -q"

    policy = read_project_policy(tmp_path)
    assert policy["enabled"] is True
    assert policy["allow_env_examples"] is True
    assert ".env" in policy["blocked_write_globs"]
    assert ".env.*" in policy["blocked_write_globs"]
    assert ".env.example" in policy["allowed_write_globs"]
