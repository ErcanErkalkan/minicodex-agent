from __future__ import annotations

from minicodex_agent.model_client import ModelClient
from minicodex_agent.model_pricing import list_model_prices, resolve_model_price


def test_catalog_resolution_for_known_models() -> None:
    pricing = resolve_model_price("openai", "gpt-5.5")
    assert pricing["pricing_source"] == "catalog"
    assert pricing["currency"] == "USD"
    assert pricing["provider"] == "openai"


def test_explicit_price_override_wins() -> None:
    pricing = resolve_model_price("openai", "gpt-5.5", explicit_input=1.25, explicit_output=9.5)
    assert pricing["pricing_source"] == "explicit"
    assert pricing["input_price_per_million"] == 1.25
    assert pricing["output_price_per_million"] == 9.5


def test_unknown_model_falls_back_to_zero() -> None:
    pricing = resolve_model_price("new_provider", "new_model")
    assert pricing["pricing_source"] == "unknown"
    assert pricing["input_price_per_million"] == 0.0
    assert pricing["output_price_per_million"] == 0.0


def test_local_provider_defaults_to_zero_cost() -> None:
    pricing = resolve_model_price("ollama", "qwen3-coder")
    assert pricing["pricing_source"] == "catalog"
    assert pricing["input_price_per_million"] == 0.0
    assert pricing["output_price_per_million"] == 0.0


def test_model_client_exposes_pricing_metadata_without_network() -> None:
    client = ModelClient("stub", provider="stub")
    assert client.pricing_source == "catalog"
    usage = client.to_usage_dict()
    assert usage["provider"] == "stub"
    assert usage["input_price_per_million"] == 0.0
    report = client.schema_reliability_report()
    assert report["pricing_source"] == "catalog"


def test_price_catalog_is_listable() -> None:
    catalog = list_model_prices()
    assert any(item["provider"] == "stub" and item["model"] == "stub" for item in catalog)
