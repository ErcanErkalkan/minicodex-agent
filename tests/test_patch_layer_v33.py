from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.config import AgentConfig
from minicodex_agent.patch_tools import (
    apply_unified_patch,
    build_patch_plan_summary,
    render_patch_plan,
    verify_unified_patch,
)
from minicodex_agent.tools.context import ToolContext
from minicodex_agent.tools.filesystem import handle_plan_patch, handle_verify_patch


def test_patch_plan_summary_is_machine_readable(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    patch = """--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-x = 1
+x = 2
"""

    summary = build_patch_plan_summary(tmp_path, patch)
    rendered = render_patch_plan(tmp_path, patch)

    assert summary.ok is True
    assert summary.total_files == 1
    assert summary.total_additions == 1
    assert summary.total_deletions == 1
    assert summary.files[0].operation == "modify"
    assert "Patch plan JSON" in rendered
    assert '"path": "app.py"' in rendered


def test_apply_patch_runs_post_apply_verification(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    patch = """--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-x = 1
+x = 2
"""

    result = apply_unified_patch(tmp_path, patch, verify=True)

    assert "Patch uygulandı" in result
    assert "Patch verification: ok" in result
    assert target.read_text(encoding="utf-8") == "x = 2\n"


def test_apply_patch_can_verify_python_syntax_and_rollback(tmp_path: Path):
    target = tmp_path / "bad.py"
    target.write_text("x = 1\n", encoding="utf-8")
    patch = """--- a/bad.py
+++ b/bad.py
@@ -1 +1 @@
-x = 1
+def broken(:
"""

    result = apply_unified_patch(tmp_path, patch, verify_python_syntax=True)

    assert "PATCH VERIFY FAILED" in result
    assert "Python syntax error" in result
    assert target.read_text(encoding="utf-8") == "x = 1\n"


def test_verify_patch_detects_already_applied_patch(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("x = 2\n", encoding="utf-8")
    patch = """--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-x = 1
+x = 2
"""

    result = verify_unified_patch(tmp_path, patch)

    assert "Patch verification: ok" in result
    assert "already present" in result or "already-applied" in result or "already" in result


def test_patch_tools_are_in_action_schema_and_handlers(tmp_path: Path):
    assert "plan_patch" in ACTION_SPECS
    assert "verify_patch" in ACTION_SPECS
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    patch = """--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-x = 1
+x = 2
"""
    ctx = ToolContext(
        config=AgentConfig(root=tmp_path, model="stub", provider="stub", approval="auto"),
        state=None,
        logger=None,
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )

    assert "Patch plan JSON" in handle_plan_patch(ctx, {"patch": patch})
    assert "Patch verification" in handle_verify_patch(ctx, {"patch": patch})
