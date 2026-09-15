from __future__ import annotations

import pytest

from minicodex_agent.action_schema import ActionValidationError, validate_action


def test_validate_action_accepts_required_args() -> None:
    decision = {
        "thought": "read file",
        "action": "read_file",
        "args": {"path": "README.md"},
    }

    normalized = validate_action(decision)

    assert normalized["action"] == "read_file"
    assert normalized["args"]["path"] == "README.md"


def test_validate_action_rejects_unknown_action() -> None:
    with pytest.raises(ActionValidationError):
        validate_action({"thought": "x", "action": "delete_everything", "args": {}})


def test_validate_action_rejects_missing_required_arg() -> None:
    with pytest.raises(ActionValidationError):
        validate_action(
            {"thought": "x", "action": "rename_python_symbol", "args": {"old_name": "a"}}
        )
