from minicodex_agent.model_client import ModelClient


def test_echo_provider_finishes():
    decision = ModelClient("echo", provider="echo").next_action("hello world")
    assert decision["action"] == "finish"
    assert "hello world" in decision["args"]["summary"]
