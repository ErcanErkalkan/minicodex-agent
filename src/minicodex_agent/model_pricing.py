"""Local provider/model pricing catalog for MiniCodex cost telemetry.

The catalog is intentionally offline and editable.  It supplies conservative
runtime defaults so eval/telemetry reports can compare relative cost without
calling vendor pricing APIs.  Review/override hosted prices before using them
for financial reporting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    """One provider/model token price entry.

    Prices are expressed per one million tokens in ``currency``.  Local and test
    providers default to zero cost.
    """

    provider: str
    model: str
    input_price_per_million: float
    output_price_per_million: float
    currency: str = "USD"
    source: str = "builtin"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_HOSTED_NOTE = (
    "Offline builtin default for telemetry only. Review current vendor pricing "
    "and override before financial reporting."
)
_LOCAL_NOTE = "Local/test provider default: no hosted token billing assumed."

DEFAULT_MODEL_PRICES: tuple[ModelPrice, ...] = (
    ModelPrice("openai", "gpt-5.5", 0.0, 0.0, notes=_HOSTED_NOTE),
    ModelPrice("openai", "gpt-5.3-codex", 0.0, 0.0, notes=_HOSTED_NOTE),
    ModelPrice(
        "openai_compatible",
        "qwen3-coder",
        0.0,
        0.0,
        notes="Self-hosted/OpenAI-compatible default; override if billed.",
    ),
    ModelPrice("ollama", "qwen3-coder", 0.0, 0.0, notes=_LOCAL_NOTE),
    ModelPrice("lmstudio", "qwen3-coder", 0.0, 0.0, notes=_LOCAL_NOTE),
    ModelPrice("llama_cpp", "qwen3-coder", 0.0, 0.0, notes=_LOCAL_NOTE),
    ModelPrice("stub", "stub", 0.0, 0.0, notes=_LOCAL_NOTE),
    ModelPrice("echo", "echo", 0.0, 0.0, notes=_LOCAL_NOTE),
)


def _key(provider: str, model: str) -> tuple[str, str]:
    return (str(provider or "").strip().lower(), str(model or "").strip().lower())


PRICE_CATALOG: dict[tuple[str, str], ModelPrice] = {
    _key(entry.provider, entry.model): entry for entry in DEFAULT_MODEL_PRICES
}


_LOCAL_PROVIDERS = {"ollama", "lmstudio", "llama_cpp", "stub", "echo"}


def list_model_prices() -> list[dict[str, Any]]:
    """Return the builtin catalog as JSON-ready dictionaries."""

    return [
        entry.to_dict()
        for entry in sorted(DEFAULT_MODEL_PRICES, key=lambda item: (item.provider, item.model))
    ]


def resolve_model_price(
    provider: str,
    model: str,
    explicit_input: float | int | None = None,
    explicit_output: float | int | None = None,
) -> dict[str, Any]:
    """Resolve token prices from explicit values, catalog defaults, or unknown fallback.

    Positive explicit input/output prices override the catalog as a pair.  If
    only one explicit side is positive, the other side falls back to ``0.0`` so
    the caller's intent remains unambiguous and deterministic.
    """

    provider_value = str(provider or "").strip()
    model_value = str(model or "").strip()
    try:
        in_price = float(explicit_input or 0.0)
    except (TypeError, ValueError):
        in_price = 0.0
    try:
        out_price = float(explicit_output or 0.0)
    except (TypeError, ValueError):
        out_price = 0.0

    if in_price > 0 or out_price > 0:
        return {
            "provider": provider_value,
            "model": model_value,
            "input_price_per_million": max(0.0, in_price),
            "output_price_per_million": max(0.0, out_price),
            "pricing_source": "explicit",
            "currency": "USD",
            "notes": "Explicit runtime/config price override.",
        }

    entry = PRICE_CATALOG.get(_key(provider_value, model_value))
    if entry is not None:
        return {
            "provider": entry.provider,
            "model": entry.model,
            "input_price_per_million": float(entry.input_price_per_million),
            "output_price_per_million": float(entry.output_price_per_million),
            "pricing_source": "catalog",
            "currency": entry.currency,
            "notes": entry.notes,
        }

    notes = (
        _LOCAL_NOTE
        if provider_value.lower() in _LOCAL_PROVIDERS
        else "Unknown provider/model; cost defaults to zero until configured."
    )
    return {
        "provider": provider_value,
        "model": model_value,
        "input_price_per_million": 0.0,
        "output_price_per_million": 0.0,
        "pricing_source": "unknown",
        "currency": "USD",
        "notes": notes,
    }
