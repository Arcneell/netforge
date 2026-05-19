"""Anthropic Claude provider.

Uses the official `anthropic` SDK with prompt caching enabled on the
system message — for repeated calls within the cache TTL (5 min default)
the system block is billed at 10 % of the normal rate, which makes the
re-run of "suggest links" on the same infra extremely cheap.
"""

from __future__ import annotations

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
        cache_prefix: str = "",
    ) -> AICompletion:
        client = self._get_client()
        # Anthropic's prompt cache requires a content block of ≥ 1024 tokens
        # (~4 KB of text). When the caller supplies a `cache_prefix` (the
        # stable snapshot body for nl_query / advisor / suggest_links), we
        # split the user message into TWO blocks: one cached for the prefix,
        # one non-cached for the dynamic suffix (history + question). This
        # is what lets a follow-up Ask AI within the cache TTL pay the
        # cache-read rate instead of re-billing the full snapshot.
        user_block: list[dict[str, Any]] | str
        if cache_prefix and len(cache_prefix) >= 4096:
            user_block = [
                {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
            ]
            if prompt:
                user_block.append({"type": "text", "text": prompt})
        elif len(prompt) >= 4096 and not cache_prefix:
            # Legacy path — caller didn't split, but the prompt itself is
            # large. Wrap the whole thing in one cached block. Less efficient
            # for follow-ups but correct.
            user_block = [
                {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}},
            ]
        else:
            user_block = (cache_prefix + ("\n\n" if cache_prefix and prompt else "") + prompt) or prompt
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

    async def stream_call(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        cache_prefix: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """Stream text deltas using `client.messages.stream()`.

        We don't expose tool calls in the streaming path — the only call
        site (`/ai/query/stream`) renders Markdown progressively, which
        is incompatible with the all-or-nothing tool_use validation we
        do on the non-streaming endpoint.
        """
        client = self._get_client()

        # Same cache_prefix splitting logic as `call()` — see that method for
        # the rationale. Keep behaviour aligned so a switch from non-streaming
        # to streaming doesn't suddenly stop hitting the cache.
        if cache_prefix and len(cache_prefix) >= 4096:
            user_block: list[dict[str, Any]] | str = [
                {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
            ]
            if prompt:
                user_block.append({"type": "text", "text": prompt})
        else:
            user_block = (
                cache_prefix + ("\n\n" if cache_prefix and prompt else "") + prompt
            ) or prompt

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
            ],
            "messages": [{"role": "user", "content": user_block}],
        }

        # `messages.stream(...)` returns an async context manager. Iterating
        # the stream directly (instead of `.text_stream`) lets us pull text
        # one `content_block_delta` at a time — `.text_stream` is supposed
        # to be equivalent but has historically batched deltas on some SDK
        # versions, so iterating events ourselves is the safe, fine-grained
        # path. The `asyncio.sleep(0)` after each yield is a cooperative
        # yield to the event loop so the StreamingResponse writer flushes
        # the chunk to the socket before we read the next delta.
        import asyncio

        try:
            async with client.messages.stream(**kwargs) as stream:
                full_text: list[str] = []
                async for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        delta_type = getattr(delta, "type", None)
                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "") or ""
                            if text:
                                full_text.append(text)
                                yield StreamDelta(text=text)
                                await asyncio.sleep(0)
                final = await stream.get_final_message()
                usage = TokenUsage(
                    prompt_tokens=getattr(final.usage, "input_tokens", 0) or 0,
                    completion_tokens=getattr(final.usage, "output_tokens", 0) or 0,
                )
                yield StreamDone(text="".join(full_text), usage=usage)
        except Exception as exc:
            raise AIProviderError(f"anthropic stream failed: {exc}") from exc
