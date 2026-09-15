from minicodex_agent.provider_registry import (
    get_provider_info,
    list_provider_names,
    render_provider_registry,
)


def test_provider_registry_contains_stub_and_echo():
    names = list_provider_names()
    assert "openai" in names
    assert "stub" in names
    assert "echo" in names
    assert not get_provider_info("echo").requires_api_key
    assert "Known model providers" in render_provider_registry()
