from pathlib import Path

import pytest

from minicodex_agent.patch_tools import apply_unified_patch, parse_unified_patch
from minicodex_agent.project_policy import extract_patch_paths


def test_apply_patch_deletes_file_transactionally(tmp_path: Path):
    target = tmp_path / "old.txt"
    target.write_text("gone\n", encoding="utf-8")
    patch = """diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""

    result = apply_unified_patch(tmp_path, patch)

    assert "transaction" in result
    assert not target.exists()
    assert list(tmp_path.glob("old.txt.bak_*"))


def test_apply_patch_renames_file_with_content_change(tmp_path: Path):
    source = tmp_path / "old.txt"
    source.write_text("hello\n", encoding="utf-8")
    patch = """diff --git a/old.txt b/new.txt
similarity index 80%
rename from old.txt
rename to new.txt
--- a/old.txt
+++ b/new.txt
@@ -1 +1 @@
-hello
+hello world
"""

    result = apply_unified_patch(tmp_path, patch)

    assert "old.txt -> new.txt" in result
    assert not source.exists()
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello world\n"


def test_apply_patch_applies_mode_change(tmp_path: Path):
    target = tmp_path / "script.sh"
    target.write_text("echo hi\n", encoding="utf-8")
    patch = """diff --git a/script.sh b/script.sh
old mode 100644
new mode 100755
--- a/script.sh
+++ b/script.sh
@@ -1 +1 @@
-echo hi
+echo hello
"""

    result = apply_unified_patch(tmp_path, patch)

    assert "mode ->" in result
    if target.stat().st_mode & 0o111 == 0:
        pytest.skip("Executable permission bits are not supported on this platform")
    assert (target.stat().st_mode & 0o777) == 0o755
    assert target.read_text(encoding="utf-8") == "echo hello\n"


def test_apply_patch_preserves_crlf_for_added_lines(tmp_path: Path):
    target = tmp_path / "win.txt"
    target.write_bytes(b"a\r\nb\r\n")
    patch = """--- a/win.txt
+++ b/win.txt
@@ -1,2 +1,3 @@
 a
+middle
 b
"""

    result = apply_unified_patch(tmp_path, patch)

    assert "transaction" in result
    assert target.read_bytes() == b"a\r\nmiddle\r\nb\r\n"


def test_apply_patch_rolls_back_when_second_write_fails(tmp_path: Path, monkeypatch):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a1\n", encoding="utf-8")
    second.write_text("b1\n", encoding="utf-8")
    patch = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-a1
+a2
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-b1
+b2
"""

    original_write_text = Path.write_text

    def failing_write_text(self, data, *args, **kwargs):
        if self == second and "b2" in data:
            raise OSError("simulated write failure")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    result = apply_unified_patch(tmp_path, patch)

    assert "PATCH ROLLBACK" in result
    assert first.read_text(encoding="utf-8") == "a1\n"
    assert second.read_text(encoding="utf-8") == "b1\n"


def test_binary_patch_is_rejected(tmp_path: Path):
    patch = """diff --git a/image.png b/image.png
GIT binary patch
literal 0
HcmV?d00001
"""

    result = apply_unified_patch(tmp_path, patch)

    assert "Binary patch desteklenmiyor" in result


def test_parse_rename_metadata_and_policy_paths():
    patch = """diff --git a/old.txt b/new.txt
rename from old.txt
rename to new.txt
"""
    parsed = parse_unified_patch(patch)

    assert parsed[0].rename_from == "old.txt"
    assert parsed[0].rename_to == "new.txt"
    assert extract_patch_paths(patch) == ["old.txt", "new.txt"]
