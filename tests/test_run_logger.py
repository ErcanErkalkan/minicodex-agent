from pathlib import Path

from minicodex_agent.run_logger import RunLogger


def test_run_logger_writes_files(tmp_path: Path):
    logger = RunLogger(tmp_path)
    logger.write_metadata({"goal": "test"})
    logger.log_event({"step": 1, "action": "inspect_project"})
    logger.write_plan(["one", "two"])
    logger.write_final({"summary": "done"})

    assert (logger.run_dir / "metadata.json").exists()
    assert (logger.run_dir / "events.jsonl").exists()
    assert (logger.run_dir / "plan.md").exists()
    assert (logger.run_dir / "final.json").exists()


def test_run_logger_redacts_secrets_before_writing(tmp_path: Path):
    logger = RunLogger(tmp_path)
    secret = "sk-1234567890abcdefghijklmnopqrstuv"  # minicodex-security-test-fixture
    logger.write_metadata({"api_key": secret})
    logger.log_event({"observation": f"OPENAI_API_KEY={secret}"})
    logger.write_plan([f"use token={secret}"])
    logger.write_final({"summary": f"finished with {secret}"})

    combined = "\n".join(
        [
            (logger.run_dir / "metadata.json").read_text(encoding="utf-8"),
            (logger.run_dir / "events.jsonl").read_text(encoding="utf-8"),
            (logger.run_dir / "plan.md").read_text(encoding="utf-8"),
            (logger.run_dir / "final.json").read_text(encoding="utf-8"),
        ]
    )
    assert secret not in combined
    assert "REDACTED" in combined


def test_run_logger_truncates_long_values(tmp_path: Path):
    logger = RunLogger(tmp_path, max_value_chars=300)
    logger.log_event({"observation": "x" * 2000})
    text = (logger.run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert len(text) < 700
    assert "TRUNCATED" in text


def test_run_logger_disabled_creates_no_files(tmp_path: Path):
    logger = RunLogger(tmp_path, enabled=False)
    logger.write_metadata({"goal": "test"})
    logger.log_event({"step": 1})
    logger.write_plan(["one"])
    logger.write_final({"summary": "done"})

    assert not any(tmp_path.iterdir())
