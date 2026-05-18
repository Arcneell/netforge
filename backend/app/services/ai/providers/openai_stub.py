"""OpenAI provider stub — implemented in Phase 2.

Registered today so settings.ai_provider="openai" picks it up and surfaces
a clear "not implemented yet" error to the caller, rather than the cryptic
"unknown provider" failure. When Phase 2 lands, the file gets replaced by
a real implementation following the same pattern as `anthropic.py`.
"""

from __future__ import annotations

from app.services.ai.types import (
    AICompletion,
    AIUnsupportedFeatureError,
    ToolDef,
)


class OpenAIStubProvider:
    name = "openai"

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
            "OpenAI provider not implemented yet — switch AI_PROVIDER to 'anthropic' "
            "or wait for Phase 2 of the AI rollout."
        )
