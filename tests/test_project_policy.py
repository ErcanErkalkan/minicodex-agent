from __future__ import annotations

from minicodex_agent.project_policy import (
    evaluate_command,
    evaluate_patch_paths,
    evaluate_write_path,
    extract_patch_paths,
    init_project_policy,
    read_project_policy,
    render_policy_check,
    update_project_policy,
)


def test_project_policy_blocks_env_write(tmp_path):
    decision = evaluate_write_path(tmp_path, ".env")
    assert not decision.allowed
    assert "blocked_write_globs" in decision.reason


def test_project_policy_allows_source_write(tmp_path):
    decision = evaluate_write_path(tmp_path, "src/app.py")
    assert decision.allowed


def test_project_policy_blocks_command_regex(tmp_path):
    decision = evaluate_command(tmp_path, "sudo rm -rf /tmp/x", read_project_policy(tmp_path))
    assert not decision.allowed


def test_project_policy_extracts_patch_paths(tmp_path):
    patch = """--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a
+b
"""
    assert extract_patch_paths(patch) == ["src/a.py"]
    assert evaluate_patch_paths(tmp_path, patch).allowed


def test_project_policy_init_update_and_render(tmp_path):
    created = init_project_policy(tmp_path)
    assert "Project policy created" in created
    updated = update_project_policy(tmp_path, {"allowed_command_prefixes": ["pytest"]})
    assert "allowed_command_prefixes" in updated
    blocked = render_policy_check(tmp_path, "command", "python script.py")
    assert blocked.startswith("blocked:")


def test_project_policy_allows_env_example_but_blocks_real_env_variants(tmp_path):
    example = evaluate_write_path(tmp_path, ".env.example")
    assert example.allowed

    sample = evaluate_write_path(tmp_path, ".env.sample")
    assert sample.allowed

    real_env = evaluate_write_path(tmp_path, ".env")
    assert not real_env.allowed

    production_env = evaluate_write_path(tmp_path, ".env.production")
    assert not production_env.allowed

    local_env = evaluate_write_path(tmp_path, ".env.local")
    assert not local_env.allowed


def test_project_policy_can_disable_env_example_exception(tmp_path):
    policy = read_project_policy(tmp_path)
    policy["allow_env_examples"] = False
    decision = evaluate_write_path(tmp_path, ".env.example", policy)
    assert not decision.allowed
    assert "blocked_write_globs" in decision.reason


def test_project_policy_accepts_utf8_bom(tmp_path):
    policy_dir = tmp_path / ".minicodex"
    policy_dir.mkdir()
    (policy_dir / "policy.json").write_text(
        '{"blocked_write_globs":["private/**"]}',
        encoding="utf-8-sig",
    )

    policy = read_project_policy(tmp_path)

    assert "private/**" in policy["blocked_write_globs"]
