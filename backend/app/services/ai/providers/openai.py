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
from collections.abc import AsyncIterator
from typing import Any

from app.services.ai.types import (
    AICompletion,
    AIProviderError,
    StreamChunk,
    StreamDelta,
    StreamDone,
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
        cache_prefix: str = "",
    ) -> AICompletion:
        client = self._get_client()
        # OpenAI auto-caches identical prefixes transparently — we just
        # concatenate `cache_prefix` ahead of the prompt and let the API
        # do its thing. Keeping the join character set predictable helps
        # the prefix-matching across calls.
        user_content = (cache_prefix + ("\n\n" if cache_prefix and prompt else "") + prompt) or prompt
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
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

    async def stream_call(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        cache_prefix: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """Stream text deltas using `chat.completions.create(stream=True)`.

        Same cache_prefix join as `call()` — OpenAI auto-caches identical
        prefixes regardless of streaming.
        """
        client = self._get_client()
        user_content = (
            cache_prefix + ("\n\n" if cache_prefix and prompt else "") + prompt
        ) or prompt
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "stream": True,
            # Ask the API to return usage on the final chunk. Required since
            # mid-2024 (`stream_options.include_usage`); otherwise the
            # streaming response carries no token totals.
            "stream_options": {"include_usage": True},
        }
        try:
            stream = await client.chat.completions.create(**kwargs)
            full_text: list[str] = []
            usage = TokenUsage()
            terminal_reason: str | None = None
            async for event in stream:
                if event.choices:
                    delta = event.choices[0].delta
                    chunk = getattr(delta, "content", None)
                    if chunk:
                        full_text.append(chunk)
                        yield StreamDelta(text=chunk)
                        # Cooperative yield so the StreamingResponse writer
                        # drains the chunk to the socket before we wait on
                        # the next OpenAI delta — mirrors the Anthropic /
                        # Gemini providers.
                        import asyncio as _asyncio

                        await _asyncio.sleep(0)
                    fr = getattr(event.choices[0], "finish_reason", None)
                    if fr:
                        terminal_reason = fr
                # Usage is attached to the final chunk (which may carry an
                # empty `choices` list).
                if getattr(event, "usage", None):
                    usage = TokenUsage(
                        prompt_tokens=getattr(event.usage, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(event.usage, "completion_tokens", 0) or 0,
                    )
            # `stop` is the normal completion. `length` means we hit
            # max_tokens; `content_filter` means moderation interrupted —
            # both leave the UI sitting on a half answer unless we surface
            # them.
            if terminal_reason and terminal_reason not in {"stop", "function_call", "tool_calls"}:
                raise AIProviderError(
                    f"openai stopped mid-response (finish_reason={terminal_reason})"
                )
            yield StreamDone(text="".join(full_text), usage=usage)
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(f"openai stream failed: {exc}") from exc
