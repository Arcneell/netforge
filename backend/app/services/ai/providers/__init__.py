"""Provider factory — picks an `AIProvider` from settings.

Concrete providers register themselves in `_REGISTRY`. The Anthropic one is
fully implemented; OpenAI and Gemini stubs raise `AIUnsupportedFeatureError`
on use, so the routes can be wired today and provider implementations land
in later phases without touching anything upstream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from threading import Lock
from typing import Protocol

from app.config import get_settings
from app.services.ai.types import (
    AICompletion,
    AIProviderError,
    AIUnsupportedFeatureError,
    StreamChunk,
    ToolDef,
)

# Per-process cache: provider instances are reusable across requests so that
# their internal SDK client (and its httpx pool) is built once. Keyed by
# `(provider_name, model)` — the api key never changes at runtime so it does
# not need to be part of the key. `get_settings()` is itself lru_cached so the
# key derivation stays consistent.
_PROVIDER_CACHE: dict[tuple[str, str], AIProvider] = {}
_PROVIDER_CACHE_LOCK = Lock()


def reset_provider_cache() -> None:
    """Drop cached provider instances. Used by tests; not exposed via API."""
    with _PROVIDER_CACHE_LOCK:
        _PROVIDER_CACHE.clear()


class AIProvider(Protocol):
    """Minimal protocol every provider must satisfy.

    Implementations are async because every concrete SDK (anthropic, openai,
    google-generativeai) exposes an async client; sync calls would block the
    event loop on each LLM round-trip.
    """

    name: str  # "anthropic" | "openai" | "gemini"
    model: str  # e.g. "claude-sonnet-4-6"

    async def call(
        self,
        *,
        system: str,
        prompt: str,
        tools: list[ToolDef] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        cache_prefix: str = "",
    ) -> AICompletion: ...

    def stream_call(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        cache_prefix: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """Stream the model's text response chunk-by-chunk.

        Yields zero or more `StreamDelta` followed by exactly one
        `StreamDone` carrying the aggregated text + token usage. Tool calls
        are intentionally NOT supported in the streaming path — the route
        only uses this for free-text Q&A where progressive rendering is
        the point. Errors raise `AIProviderError`.
        """
        ...


# Lazy import inside the factory so missing optional deps (anthropic /
# openai / google-generativeai not installed) only break the matching
# provider, not the whole app boot.
def get_provider(name: str | None = None) -> AIProvider:
    """Return a configured provider. Defaults to `settings.ai_provider`.

    Instances are cached per (name, model) — see `_PROVIDER_CACHE`. Raises
    `AIProviderError` if the provider is unknown or its SDK is missing —
    never returns a half-built object.
    """
    settings = get_settings()
    chosen = (name or settings.ai_provider).lower()

    if chosen == "anthropic":
        from app.services.ai.providers.anthropic import AnthropicProvider

        model = settings.ai_model or "claude-sonnet-4-6"
        key = (chosen, model)
        with _PROVIDER_CACHE_LOCK:
            cached = _PROVIDER_CACHE.get(key)
            if cached is None:
                cached = AnthropicProvider(
                    api_key=settings.ai_anthropic_api_key,
                    model=model,
                )
                _PROVIDER_CACHE[key] = cached
        return cached

    if chosen == "openai":
        from app.services.ai.providers.openai import OpenAIProvider

        model = settings.ai_model or "gpt-4o"
        key = (chosen, model)
        with _PROVIDER_CACHE_LOCK:
            cached = _PROVIDER_CACHE.get(key)
            if cached is None:
                cached = OpenAIProvider(
                    api_key=settings.ai_openai_api_key,
                    model=model,
                )
                _PROVIDER_CACHE[key] = cached
        return cached

    if chosen == "gemini":
        from app.services.ai.providers.gemini import GeminiProvider

        model = settings.ai_model or "gemini-2.5-pro"
        key = (chosen, model)
        with _PROVIDER_CACHE_LOCK:
            cached = _PROVIDER_CACHE.get(key)
            if cached is None:
                cached = GeminiProvider(
                    api_key=settings.ai_gemini_api_key,
                    model=model,
                )
                _PROVIDER_CACHE[key] = cached
        return cached

    raise AIProviderError(f"unknown AI provider: {chosen!r}")


__all__ = [
    "AICompletion",
    "AIProvider",
    "AIProviderError",
    "AIUnsupportedFeatureError",
    "ToolDef",
    "get_provider",
    "reset_provider_cache",
]
