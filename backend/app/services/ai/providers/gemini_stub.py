"""Gemini provider stub — implemented in Phase 2.

Same role as `openai_stub.py`: registered so settings.ai_provider="gemini"
fails with a clear message instead of "unknown provider".
"""

from __future__ import annotations

from app.services.ai.types import (
    AICompletion,
    AIUnsupportedFeatureError,
    ToolDef,
)


class GeminiStubProvider:
    name = "gemini"

    def __init__(self, *, model: str) -> None:
        self.model = model

    async def call(
        self,
        *,
        system: str,
        prompt: str,
        tools: list[ToolDef] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> AICompletion:
        raise AIUnsupportedFeatureError(
            "Gemini provider not implemented yet — switch AI_PROVIDER to 'anthropic' "
            "or wait for Phase 2 of the AI rollout."
        )
