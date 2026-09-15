from __future__ import annotations

import pytest

from minicodex_agent.action_schema import (
    MODEL_ACTION_JSON_SCHEMA,
    ActionValidationError,
    validate_action,
)


def test_validate_action_rejects_extra_top_level_keys() -> None:
    with pytest.raises(ActionValidationError, match="unsupported top-level"):
        validate_action(
            {
                "thought": "x",
                "action": "finish",
                "args": {},
                "debug": "not allowed",
            }
        )


def test_validate_action_rejects_extra_action_args() -> None:
    with pytest.raises(ActionValidationError, match="unsupported arg"):
        validate_action(
            {
                "thought": "x",
                "action": "read_file",
                "args": {"path": "README.md", "delete_after_reading": True},
            }
        )


def test_validate_action_rejects_wrong_arg_type() -> None:
    with pytest.raises(ActionValidationError, match="must be integer"):
        validate_action(
            {
                "thought": "x",
                "action": "read_file",
                "args": {"path": "README.md", "max_chars": "many"},
            }
        )


def test_validate_action_accepts_typed_array_args() -> None:
    decision = validate_action(
        {
            "thought": "plan",
            "action": "update_plan",
            "args": {"steps": ["read", "test"]},
        }
    )
    assert decision["args"]["steps"] == ["read", "test"]


def test_model_action_json_schema_is_action_specific_and_strict() -> None:
    variants = MODEL_ACTION_JSON_SCHEMA["oneOf"]
    read_file = next(
        variant
        for variant in variants
        if variant["properties"]["action"].get("const") == "read_file"
    )
    assert read_file["additionalProperties"] is False
    assert read_file["properties"]["args"]["additionalProperties"] is False
    assert read_file["properties"]["args"]["required"] == ["path"]
    assert read_file["properties"]["args"]["properties"]["max_chars"]["type"] == "integer"
