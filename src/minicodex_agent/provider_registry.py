"""Provider registry for MiniCodex model backends."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata for one model provider."""

    name: str
    requires_api_key: bool
    description: str
    default_model: str


_PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        name="openai",
        requires_api_key=True,
        description="Official OpenAI Responses API provider for strongest coding-agent runs.",
        default_model="gpt-5.5",
    ),
    "openai_compatible": ProviderInfo(
        name="openai_compatible",
        requires_api_key=False,
        description=(
            "OpenAI-compatible Chat Completions provider for local or self-hosted endpoints "
            "such as Ollama, LM Studio, llama.cpp, vLLM, and compatible gateways."
        ),
        default_model="qwen3-coder",
    ),
    "ollama": ProviderInfo(
        name="ollama",
        requires_api_key=False,
        description="Shortcut for an Ollama OpenAI-compatible local endpoint at http://localhost:11434/v1.",
        default_model="qwen3-coder",
    ),
    "lmstudio": ProviderInfo(
        name="lmstudio",
        requires_api_key=False,
        description="Shortcut for an LM Studio OpenAI-compatible local server at http://localhost:1234/v1.",
        default_model="qwen3-coder",
    ),
    "llama_cpp": ProviderInfo(
        name="llama_cpp",
        requires_api_key=False,
        description="Shortcut for llama-cpp-python OpenAI-compatible server at http://localhost:8000/v1.",
        default_model="qwen3-coder",
    ),
    "stub": ProviderInfo(
        name="stub",
        requires_api_key=False,
        description="Deterministic smoke-test provider that immediately finishes.",
        default_model="stub",
    ),
    "echo": ProviderInfo(
        name="echo",
        requires_api_key=False,
        description="Debug provider that echoes the prompt into a finish action without editing files.",
        default_model="echo",
    ),
}

OPENAI_COMPATIBLE_PROVIDERS = {"openai_compatible", "ollama", "lmstudio", "llama_cpp"}


def list_provider_infos() -> list[ProviderInfo]:
    """Return all known model providers in stable order."""

    return [_PROVIDERS[name] for name in sorted(_PROVIDERS)]


def list_provider_names() -> list[str]:
    """Return provider names accepted by the CLI and model client."""

    return [provider.name for provider in list_provider_infos()]


def get_provider_info(name: str) -> ProviderInfo:
    """Return metadata for a provider or raise a clear error."""

    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        allowed = ", ".join(list_provider_names())
        raise ValueError(f"Unsupported provider: {name}. Allowed providers: {allowed}") from exc


def render_provider_registry(providers: Iterable[ProviderInfo] | None = None) -> str:
    """Render provider metadata for humans and agent observations."""

    selected = list(providers) if providers is not None else list_provider_infos()
    lines = ["Known model providers:"]
    for info in selected:
        key_msg = "requires API key" if info.requires_api_key else "API key optional"
        lines.append(
            f"- {info.name}: {info.description} Default model: {info.default_model}; {key_msg}."
        )
    return "\n".join(lines)
