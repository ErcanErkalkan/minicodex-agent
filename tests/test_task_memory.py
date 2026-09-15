from minicodex_agent.task_memory import read_task_memory, save_task_memory


def test_task_memory_roundtrip(tmp_path):
    result = save_task_memory(
        tmp_path,
        goal="fix tests",
        summary="Updated parser",
        changed_files=["src/parser.py"],
        checks_run=["pytest -q"],
        success=True,
    )

    assert "memory.jsonl" in result
    loaded = read_task_memory(tmp_path, limit=5)
    assert "fix tests" in loaded
    assert "src/parser.py" in loaded
    assert "pytest -q" in loaded


def test_task_memory_query(tmp_path):
    save_task_memory(tmp_path, goal="frontend", summary="done", success=True)
    save_task_memory(tmp_path, goal="backend", summary="done", success=True)

    loaded = read_task_memory(tmp_path, query="backend")

    assert "backend" in loaded
    assert "frontend" not in loaded
