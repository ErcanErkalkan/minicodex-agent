from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from minicodex_agent.model_client import ModelBudgetExceeded, ModelClient


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "thought": "ok",
                    "action": "finish",
                    "args": {"summary": "done", "changed_files": [], "checks_run": []},
                }
            ),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_openai_provider_uses_structured_output_and_limits() -> None:
    client = ModelClient(
        "test-model",
        provider="stub",
        timeout_seconds=12,
        max_output_tokens=777,
        max_retries=0,
        structured_output=True,
    )
    fake = FakeOpenAIClient()
    client.provider = "openai"
    client.client = fake

    raw = client.next_action_text("{}")

    assert "finish" in raw
    call = fake.responses.calls[0]
    assert call["timeout"] == 12
    assert call["max_output_tokens"] == 777
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True


def test_model_call_budget_is_enforced() -> None:
    client = ModelClient("test-model", provider="stub", call_budget=1)
    client.next_action_text("{}")
    # Stub calls do not contact provider and intentionally do not count toward budget.
    assert client.usage.calls == 0

    openai_client = ModelClient("test-model", provider="stub", call_budget=1, max_retries=0)
    fake = FakeOpenAIClient()
    openai_client.provider = "openai"
    openai_client.client = fake
    openai_client.next_action_text("{}")
    with pytest.raises(ModelBudgetExceeded):
        openai_client.next_action_text("{}")


def test_cost_budget_uses_provider_usage_when_prices_are_configured() -> None:
    client = ModelClient(
        "test-model",
        provider="stub",
        max_retries=0,
        cost_budget_usd=0.000001,
        input_price_per_million=10.0,
        output_price_per_million=10.0,
    )
    fake = FakeOpenAIClient()
    client.provider = "openai"
    client.client = fake

    with pytest.raises(ModelBudgetExceeded):
        client.next_action_text("{}")
