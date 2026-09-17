from scripts.p0_6_swebench_preflight import _validate_manifest


def test_pilot_manifest_validation_accepts_minimum_fields():
    raw = {
        "tasks": [
            {
                "instance_id": "x__y-1",
                "repo": "x/y",
                "base_commit": "a" * 40,
                "environment_setup_commit": "b" * 40,
                "difficulty": "easy",
                "fail_to_pass": ["test_x"],
            }
        ]
    }
    output = _validate_manifest(raw)
    assert output["ok"] is True
    assert output["task_count"] == 1
    assert output["repo_count"] == 1


def test_pilot_manifest_validation_rejects_duplicate_and_missing_oracle():
    task = {
        "instance_id": "x__y-1",
        "repo": "x/y",
        "base_commit": "a" * 40,
        "environment_setup_commit": "b" * 40,
        "difficulty": "easy",
        "fail_to_pass": [],
    }
    output = _validate_manifest({"tasks": [task, dict(task)]})
    assert output["ok"] is False
    assert any("duplicate instance_id" in item for item in output["problems"])
    assert any("fail_to_pass" in item for item in output["problems"])
