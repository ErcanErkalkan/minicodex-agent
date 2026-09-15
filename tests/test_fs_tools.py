from pathlib import Path

from minicodex_agent.fs_tools import preview_replace_in_file, replace_in_file, write_file


def test_preview_replace_does_not_modify_file(tmp_path: Path):
    target = tmp_path / "hello.txt"
    target.write_text("hello world\n", encoding="utf-8")
    preview = preview_replace_in_file(tmp_path, "hello.txt", "world", "agent")
    assert "agent" in preview
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_replace_dry_run_does_not_modify_file(tmp_path: Path):
    target = tmp_path / "hello.txt"
    target.write_text("hello world\n", encoding="utf-8")
    result = replace_in_file(tmp_path, "hello.txt", "world", "agent", dry_run=True)
    assert "DRY-RUN" in result
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_write_file_creates_file(tmp_path: Path):
    result = write_file(tmp_path, "src/new.txt", "content")
    assert "Dosya oluşturuldu" in result
    assert (tmp_path / "src" / "new.txt").read_text(encoding="utf-8") == "content"
