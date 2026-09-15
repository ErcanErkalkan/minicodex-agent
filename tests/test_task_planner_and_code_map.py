from minicodex_agent.code_map import build_code_map
from minicodex_agent.task_planner import decompose_task


def test_decompose_task_contains_goal(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    result = decompose_task(tmp_path, "fix parser")

    assert "fix parser" in result
    assert "Recommended steps" in result


def test_build_code_map_python_symbols(tmp_path):
    src = tmp_path / "app.py"
    src.write_text(
        "import os\n\nclass Service:\n    def run(self):\n        pass\n", encoding="utf-8"
    )

    result = build_code_map(tmp_path)

    assert "app.py" in result
    assert "Service" in result
    assert "run" in result
