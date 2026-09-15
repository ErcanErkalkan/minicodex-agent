import subprocess

from minicodex_agent.change_review import record_change_approval, review_change_set


def test_change_review_without_git(tmp_path):
    assert "requires a git repository" in review_change_set(tmp_path)


def test_record_change_approval(tmp_path):
    result = record_change_approval(tmp_path, "approved", "looks good")
    assert "approved" in result
    log = tmp_path / ".minicodex" / "change_approvals.jsonl"
    assert log.exists()
    assert "looks good" in log.read_text(encoding="utf-8")


def test_review_change_set_with_git(tmp_path):
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    output = review_change_set(tmp_path)
    assert "Change-set review" in output
    assert "a.txt" in output


def test_record_change_approval_dry_run_does_not_write(tmp_path):
    result = record_change_approval(tmp_path, "approved", "looks good", dry_run=True)
    assert "DRY-RUN" in result
    assert not (tmp_path / ".minicodex" / "change_approvals.jsonl").exists()
