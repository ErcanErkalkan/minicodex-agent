from __future__ import annotations

from minicodex_agent.model_client import ModelClient


def test_model_client_stub_finishes_without_api_call():
    client = ModelClient("stub-model", provider="stub")
    result = client.next_action("{}")

    assert result["action"] == "finish"
    assert "Stub provider" in result["thought"]
