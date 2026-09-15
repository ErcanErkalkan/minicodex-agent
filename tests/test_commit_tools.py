import subprocess

from minicodex_agent.commit_tools import generate_commit_message


def test_generate_commit_message_no_git_changes(tmp_path):
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
    )

    message = generate_commit_message(tmp_path, goal="update docs")

    assert "No git changes" in message


def test_generate_commit_message_with_change(tmp_path):
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")

    message = generate_commit_message(tmp_path, goal="update docs")

    assert "update docs" in message
    assert "README.md" in message
    assert "git add" in message
