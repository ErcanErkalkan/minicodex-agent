from __future__ import annotations

import json
from types import SimpleNamespace

from minicodex_agent.action_schema import validate_action
from minicodex_agent.model_client import ModelClient, build_chat_completion_tools, response_to_text


class FakeToolCallChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Use finish.",
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="finish",
                                    arguments=json.dumps(
                                        {"summary": "done", "changed_files": [], "checks_run": []}
                                    ),
                                )
                            )
                        ],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        )


class FakeJsonFallbackChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "tools" in kwargs:
            raise TypeError("tools unsupported")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "thought": "fallback",
                                "action": "finish",
                                "args": {"summary": "ok", "changed_files": [], "checks_run": []},
                            }
                        )
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=1),
        )


def test_build_chat_completion_tools_contains_action_schemas() -> None:
    tools = build_chat_completion_tools()
    finish = next(tool for tool in tools if tool["function"]["name"] == "finish")

    assert finish["type"] == "function"
    assert finish["function"]["parameters"]["type"] == "object"
    assert "summary" in finish["function"]["parameters"]["properties"]


def test_build_chat_completion_tools_can_filter_actions() -> None:
    tools = build_chat_completion_tools(["finish", "read_file", "unknown"])

    assert [tool["function"]["name"] for tool in tools] == ["finish", "read_file"]


def test_response_to_text_converts_native_tool_call_to_action_json() -> None:
    choice = SimpleNamespace(
        message=SimpleNamespace(
            content="Next action",
            tool_calls=[
                SimpleNamespace(
                    function=SimpleNamespace(
                        name="finish",
                        arguments='{"summary":"done","changed_files":[],"checks_run":[]}',
                    )
                )
            ],
        )
    )
    raw = response_to_text(SimpleNamespace(choices=[choice]))
    action = validate_action(json.loads(raw))

    assert action["action"] == "finish"
    assert action["args"]["summary"] == "done"


def test_local_auto_protocol_uses_native_tool_calls() -> None:
    client = ModelClient(
        "local",
        provider="stub",
        max_retries=0,
        action_protocol="auto",
        available_actions=["finish"],
    )
    fake_chat = FakeToolCallChat()
    client.provider = "ollama"
    client.action_protocol = "tool_calls"
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=fake_chat))

    raw = client.next_action_text("{}")
    action = validate_action(json.loads(raw))

    assert action["action"] == "finish"
    call = fake_chat.calls[0]
    assert "tools" in call
    assert call["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in call["tools"]] == ["finish"]
    assert client.usage.native_tool_calls == 1
    assert client.usage.json_text_actions == 0


def test_local_tool_call_protocol_falls_back_to_json_text_when_server_rejects_tools() -> None:
    client = ModelClient("local", provider="stub", max_retries=0, action_protocol="tool_calls")
    fake_chat = FakeJsonFallbackChat()
    client.provider = "openai_compatible"
    client.action_protocol = "tool_calls"
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=fake_chat))

    raw = client.next_action_text("{}")
    action = validate_action(json.loads(raw))

    assert action["action"] == "finish"
    assert "tools" in fake_chat.calls[0]
    assert "tools" not in fake_chat.calls[1]
    assert fake_chat.calls[1]["response_format"] == {"type": "json_object"}
    assert client.usage.native_tool_calls == 0
    assert client.usage.json_text_actions == 1


def test_schema_reliability_metrics_are_recorded() -> None:
    client = ModelClient("local", provider="stub")
    client.record_action_validation(True)
    client.record_action_validation(False)

    report = client.schema_reliability_report()

    assert report["validation_successes"] == 1
    assert report["validation_failures"] == 1
    assert report["schema_reliability"] == 0.5


def test_streaming_tool_call_chunks_are_collected() -> None:
    events = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                function=SimpleNamespace(name="finish", arguments='{"summary":"do'),
                            )
                        ]
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                function=SimpleNamespace(
                                    name="", arguments='ne","changed_files":[],"checks_run":[]}'
                                ),
                            )
                        ]
                    )
                )
            ]
        ),
    ]
    raw = response_to_text(iter(events))
    action = validate_action(json.loads(raw))

    assert action["action"] == "finish"
    assert action["args"]["summary"] == "done"
