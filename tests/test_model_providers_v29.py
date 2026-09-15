from __future__ import annotations

import json
from types import SimpleNamespace

from minicodex_agent.config import AgentConfig, apply_project_config, require_api_key
from minicodex_agent.model_client import ModelClient, provider_default_base_url
from minicodex_agent.project_settings import update_project_config
from minicodex_agent.provider_registry import get_provider_info, list_provider_names


class FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "thought": "ok",
                                "action": "finish",
                                "args": {"summary": "done", "changed_files": [], "checks_run": []},
                            }
                        )
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


class FakeCompatibleClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeChatCompletions())


class TypeErrorThenSuccessChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "response_format" in kwargs:
            raise TypeError("response_format unsupported")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"thought":"ok","action":"finish","args":{}}')
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )


def test_provider_registry_includes_openai_compatible_and_local_shortcuts() -> None:
    names = list_provider_names()

    assert "openai_compatible" in names
    assert "ollama" in names
    assert "lmstudio" in names
    assert "llama_cpp" in names
    assert not get_provider_info("ollama").requires_api_key
    assert provider_default_base_url("ollama") == "http://localhost:11434/v1"


def test_require_api_key_uses_custom_env_and_skips_local_provider(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MINICODEX_TEST_KEY", "secret")

    assert require_api_key("openai", "MINICODEX_TEST_KEY") == "secret"
    assert require_api_key("ollama", "MISSING_KEY") == ""


def test_openai_compatible_provider_uses_chat_completions_contract() -> None:
    client = ModelClient(
        "local-coder",
        provider="stub",
        timeout_seconds=13,
        max_output_tokens=700,
        max_retries=0,
        structured_output=True,
        reasoning_effort="medium",
    )
    fake = FakeCompatibleClient()
    client.provider = "openai_compatible"
    client.action_protocol = "tool_calls"
    client.client = fake

    raw = client.next_action_text("{}")

    assert "finish" in raw
    call = fake.chat.completions.calls[0]
    assert call["model"] == "local-coder"
    assert call["max_tokens"] == 700
    assert call["timeout"] == 13
    assert "tools" in call
    assert call["tool_choice"] == "auto"
    assert any(tool["function"]["name"] == "finish" for tool in call["tools"])
    assert call["reasoning_effort"] == "medium"
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][1]["role"] == "user"
    assert client.usage.calls == 1
    assert client.usage.input_tokens == 10
    assert client.usage.output_tokens == 5


def test_openai_compatible_fallback_preserves_timeout_and_token_limit() -> None:
    client = ModelClient(
        "local-coder",
        provider="stub",
        timeout_seconds=11,
        max_output_tokens=333,
        max_retries=0,
        structured_output=True,
        action_protocol="json_text",
    )
    fake_chat = TypeErrorThenSuccessChat()
    client.provider = "ollama"
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=fake_chat))

    raw = client.next_action_text("{}")

    assert "finish" in raw
    fallback = fake_chat.calls[-1]
    assert "tools" not in fallback
    assert "tool_choice" not in fallback
    assert "response_format" not in fallback
    assert fallback["timeout"] == 11
    assert fallback["max_tokens"] == 333


def test_project_config_applies_model_provider_fields(tmp_path) -> None:
    update_project_config(
        tmp_path,
        {
            "preferred_provider": "ollama",
            "preferred_model": "qwen3-coder:latest",
            "model_base_url": "http://localhost:11434/v1",
            "model_api_key_env": "OLLAMA_API_KEY",
            "model_reasoning_effort": "low",
            "model_stream": True,
            "model_stream_ui": True,
            "model_action_protocol": "tool_calls",
        },
    )

    cfg = apply_project_config(
        AgentConfig(root=tmp_path, model="local", provider="stub"),
        explicit_options=set(),
    )

    assert cfg.provider == "ollama"
    assert cfg.model == "qwen3-coder:latest"
    assert cfg.model_base_url == "http://localhost:11434/v1"
    assert cfg.model_api_key_env == "OLLAMA_API_KEY"
    assert cfg.model_reasoning_effort == "low"
    assert cfg.model_stream is True
    assert cfg.model_stream_ui is True
    assert cfg.model_action_protocol == "tool_calls"


def test_cli_defaults_local_provider_to_provider_default_model(monkeypatch, tmp_path) -> None:
    import sys

    from minicodex_agent import cli

    seen = {}

    class FakeAgent:
        def __init__(self, config):
            seen["provider"] = config.provider
            seen["model"] = config.model

        def run(self, goal):
            return SimpleNamespace(exit_code=0)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minicodex",
            "inspect",
            "--root",
            str(tmp_path),
            "--provider",
            "ollama",
            "--no-project-config",
        ],
    )
    monkeypatch.setattr(cli, "MiniCodexAgent", FakeAgent)

    try:
        cli.main()
    except SystemExit as exc:
        assert int(exc.code) == 0

    assert seen == {"provider": "ollama", "model": "qwen3-coder"}
