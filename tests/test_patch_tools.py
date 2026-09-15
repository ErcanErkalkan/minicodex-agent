from pathlib import Path

from minicodex_agent.patch_tools import apply_unified_patch, parse_unified_patch


def test_parse_unified_patch_single_file():
    patch = """--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n print('old')\n-x = 1\n+x = 2\n"""
    patches = parse_unified_patch(patch)
    assert len(patches) == 1
    assert patches[0].new_path == "app.py"
    assert len(patches[0].hunks) == 1


def test_apply_unified_patch_updates_file(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("print('old')\nx = 1\n", encoding="utf-8")
    patch = """--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n print('old')\n-x = 1\n+x = 2\n"""

    result = apply_unified_patch(tmp_path, patch)

    assert "Patch uygulandı" in result
    assert target.read_text(encoding="utf-8") == "print('old')\nx = 2\n"


def test_apply_unified_patch_dry_run_does_not_write(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    patch = """--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"""

    result = apply_unified_patch(tmp_path, patch, dry_run=True)

    assert "DRY-RUN" in result
    assert target.read_text(encoding="utf-8") == "x = 1\n"


def test_apply_unified_patch_creates_file(tmp_path: Path):
    patch = """--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+hello\n+world\n"""

    result = apply_unified_patch(tmp_path, patch)

    assert "new.txt" in result
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello\nworld\n"
