"""Anthropic Claude provider.

Uses the official `anthropic` SDK with prompt caching enabled on the
system message — for repeated calls within the cache TTL (5 min default)
the system block is billed at 10 % of the normal rate, which makes the
re-run of "suggest links" on the same infra extremely cheap.
"""

from __future__ import annotations

import time
from typing import Any

from app.services.ai.types import (
    AICompletion,
    AIProviderError,
    TokenUsage,
    ToolCall,
    ToolDef,
)


class AnthropicProvider:
    """Concrete `AIProvider` for Claude (anthropic.com).

    The SDK is imported lazily so the import only fails on actual use —
    deployments that don't enable Anthropic don't need to install the
    package at all.
    """

    name = "anthropic"

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key:
            raise AIProviderError(
                "ANTHROPIC_API_KEY is empty — set ai_anthropic_api_key in settings"
            )
        self._api_key = api_key
        self.model = model
        # Lazily-built AsyncAnthropic client, reused across calls. Each SDK
        # client holds an httpx pool; rebuilding it for every advisor /
        # nl_query call was throwing away connection reuse and TLS handshakes.
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise AIProviderError(
                "anthropic SDK not installed (`pip install anthropic`)"
            ) from exc
        self._client = AsyncAnthropic(api_key=self._api_key)
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
        # Anthropic's prompt cache requires a content block of ≥ 1024 tokens
        # (~4 KB of text). Below that, `cache_control` is a no-op. The system
        # prompt is always large enough; the user message only is when it
        # contains the topology snapshot — guard the marker so we don't ship
        # a useless `cache_control` on a short ping.
        user_block: list[dict[str, Any]] | str = prompt
        if len(prompt) >= 4096:
            # Cache the bulky snapshot+conversation prefix. Anthropic accepts
            # up to 4 cache breakpoints per request, well above the two we use.
            user_block = [
                {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}},
            ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            # `cache_control` on the system block opts into prompt caching.
            # The cache key is the exact bytes — feeding the same infra
            # snapshot back makes the second call dramatically cheaper.
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
            ],
            "messages": [{"role": "user", "content": user_block}],
        }
        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
            # Force a tool call when one is offered — keeps the parser happy
            # and avoids the model "explaining" instead of doing the work.
            kwargs["tool_choice"] = {"type": "tool", "name": tools[0].name}

        try:
            t0 = time.monotonic()
            resp = await client.messages.create(**kwargs)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
        except Exception as exc:
            raise AIProviderError(f"anthropic API call failed: {exc}") from exc

        # The response is a list of content blocks. Walk it once and pick
        # the first tool_use; if none, concatenate text blocks.
        tool_call: ToolCall | None = None
        text_chunks: list[str] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "tool_use" and tool_call is None:
                tool_call = ToolCall(name=block.name, input=dict(block.input))
            elif btype == "text":
                text_chunks.append(block.text)

        usage = TokenUsage(
            prompt_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
        )

        return AICompletion(
            text="\n".join(text_chunks) or None,
            tool_call=tool_call,
            usage=usage,
            raw={"id": resp.id, "stop_reason": resp.stop_reason, "latency_ms": elapsed_ms},
        )
