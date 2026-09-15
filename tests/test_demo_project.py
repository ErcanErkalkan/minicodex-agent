from minicodex_agent.demo_project import create_demo_project


def test_create_demo_project(tmp_path):
    target = tmp_path / "demo"
    result = create_demo_project(target)

    assert "Demo project created" in result
    assert (target / "pyproject.toml").exists()
    assert (target / "src" / "minicodex_demo" / "calculator.py").exists()
    assert (target / "tests" / "test_calculator.py").exists()
    assert (target / ".minicodex" / "config.json").exists()


def test_create_demo_project_refuses_non_empty_without_overwrite(tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    (target / "existing.txt").write_text("x", encoding="utf-8")

    result = create_demo_project(target)

    assert "not empty" in result
