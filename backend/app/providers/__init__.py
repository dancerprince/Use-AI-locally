"""Model provider registry. To add a provider, subclass ``ModelProvider`` and register it here."""

from __future__ import annotations

from .base import ModelProvider, PingResult, ProviderError, StreamEvent, ToolCall, ToolSpec
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

PROVIDERS: dict[str, type[ModelProvider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAICompatProvider,
}


def build_provider(
    name: str, base_url: str, *, api_key: str | None, timeout_s: float, ping_timeout_s: float
) -> ModelProvider:
    try:
        cls = PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider '{name}'") from exc
    return cls(base_url, api_key=api_key, timeout_s=timeout_s, ping_timeout_s=ping_timeout_s)


__all__ = [
    "PROVIDERS",
    "ModelProvider",
    "PingResult",
    "ProviderError",
    "StreamEvent",
    "ToolCall",
    "ToolSpec",
    "build_provider",
]
