from pathlib import Path

from minicodex_agent.failure_tools import analyze_failure_output, parse_error_locations


def test_parse_python_traceback_location():
    output = 'Traceback\n  File "src/app.py", line 12, in run\n    boom()\n'

    locations = parse_error_locations(output)

    assert locations[0].path == "src/app.py"
    assert locations[0].line == 12


def test_analyze_failure_output_includes_context(tmp_path: Path):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    output = 'Exit code: 1\nTraceback\n  File "src/app.py", line 3, in run\n    three\n'

    result = analyze_failure_output(tmp_path, output, context_lines=1)

    assert "src/app.py:3" in result
    assert ">    3 | three" in result
