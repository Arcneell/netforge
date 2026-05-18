"""Provider factory — picks an `AIProvider` from settings.

Concrete providers register themselves in `_REGISTRY`. The Anthropic one is
fully implemented; OpenAI and Gemini stubs raise `AIUnsupportedFeatureError`
on use, so the routes can be wired today and provider implementations land
in later phases without touching anything upstream.
"""

from __future__ import annotations

from typing import Protocol

from app.config import get_settings
from app.services.ai.types import (
    AICompletion,
    AIProviderError,
    AIUnsupportedFeatureError,
    ToolDef,
)


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
    ) -> AICompletion: ...


# Lazy import inside the factory so missing optional deps (anthropic /
# openai / google-generativeai not installed) only break the matching
# provider, not the whole app boot.
def get_provider(name: str | None = None) -> AIProvider:
    """Return a configured provider. Defaults to `settings.ai_provider`.

    Raises `AIProviderError` if the provider is unknown or its SDK is
    missing — never returns a half-built object.
    """
    settings = get_settings()
    chosen = (name or settings.ai_provider).lower()

    if chosen == "anthropic":
        from app.services.ai.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.ai_anthropic_api_key,
            model=settings.ai_model or "claude-sonnet-4-6",
        )

    if chosen == "openai":
        from app.services.ai.providers.openai_stub import OpenAIStubProvider

        return OpenAIStubProvider(model=settings.ai_model or "gpt-4o")

    if chosen == "gemini":
        from app.services.ai.providers.gemini_stub import GeminiStubProvider

        return GeminiStubProvider(model=settings.ai_model or "gemini-2.5-pro")

    raise AIProviderError(f"unknown AI provider: {chosen!r}")


__all__ = [
    "AICompletion",
    "AIProvider",
    "AIProviderError",
    "AIUnsupportedFeatureError",
    "ToolDef",
    "get_provider",
]
