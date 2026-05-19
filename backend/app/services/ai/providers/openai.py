"""OpenAI provider — Chat Completions API with function calling.

Mirrors the Anthropic provider's surface: builds a single user message,
optionally offers one tool, forces a tool call when one is provided so the
parser doesn't have to handle prose-fallback paths.

Notes:
- Uses the modern `chat.completions` endpoint (the same one as 4o/4-turbo).
  Switching to the Responses API later is a one-method rewrite.
- No prompt caching here — OpenAI's auto-caching kicks in transparently on
  long identical prefixes, but it's not opt-in like Anthropic's.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.services.ai.types import (
    AICompletion,
    AIProviderError,
    TokenUsage,
    ToolCall,
    ToolDef,
)


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key:
            raise AIProviderError(
                "OPENAI_API_KEY is empty — set ai_openai_api_key in settings"
            )
        self._api_key = api_key
        self.model = model
        # Lazily-built AsyncOpenAI client, reused across calls — same rationale
        # as the Anthropic provider: keep the underlying httpx pool warm.
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise AIProviderError(
                "openai SDK not installed (`pip install openai`)"
            ) from exc
        self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def call(
        self,
        *,
        system: str,
        prompt: str,
        tools: list[ToolDef] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> AICompletion:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
            # Force the function call so the model can't reply in prose.
            kwargs["tool_choice"] = {
                "type": "function",
                "function": {"name": tools[0].name},
            }

        try:
            t0 = time.monotonic()
            resp = await client.chat.completions.create(**kwargs)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
        except Exception as exc:
            raise AIProviderError(f"openai API call failed: {exc}") from exc

        choice = resp.choices[0] if resp.choices else None
        if choice is None:
            raise AIProviderError("openai returned no choices")

        tool_call: ToolCall | None = None
        msg = choice.message
        if msg.tool_calls:
            first = msg.tool_calls[0]
            try:
                args = json.loads(first.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise AIProviderError(
                    f"openai tool call returned invalid JSON: {exc}"
                ) from exc
            tool_call = ToolCall(name=first.function.name, input=args)

        usage = TokenUsage(
            prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
        )

        return AICompletion(
            text=msg.content or None,
            tool_call=tool_call,
            usage=usage,
            raw={"id": resp.id, "finish_reason": choice.finish_reason, "latency_ms": elapsed_ms},
        )
