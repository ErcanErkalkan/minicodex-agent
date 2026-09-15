from __future__ import annotations

from pathlib import Path

from minicodex_agent.recovery_tools import diagnose_patch_failure


def test_diagnose_patch_failure_mentions_recovery_sequence(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    patch = """--- a/app.py\n+++ b/app.py\n@@ -10 +10 @@\n-x = 1\n+x = 2\n"""

    result = diagnose_patch_failure(tmp_path, patch, "line mismatch")

    assert "Patch recovery diagnosis" in result
    assert "Recommended recovery sequence" in result
    assert "app.py" in result
