"""Google Gemini provider — `google-genai` SDK with function declarations.

Gemini's function-calling API differs slightly from Anthropic/OpenAI:
- Tools are wrapped in a `Tool` object with one or more `FunctionDeclaration`s.
- The model returns the call inside `candidates[0].content.parts[0].function_call`.
- Forcing a single function call is done via `tool_config.function_calling_config`
  with `mode="ANY"` and the allowed function name listed.

Token usage lives in `usage_metadata.prompt_token_count` /
`candidates_token_count` (note the singular `candidates_` here is the
output side, not the candidates array).
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

# Gemini's function-declaration schema only accepts a subset of JSON Schema.
# Anthropic / OpenAI happily eat `additionalProperties`, `$schema`, `title`,
# etc. — Gemini rejects the request with a 400 INVALID_ARGUMENT the moment it
# sees one. Keep this list narrow: only the keys actually used by our prompts.
# Source: https://ai.google.dev/api/caching#Schema
#
# `maxItems` / `minItems` are explicitly NOT in this list even though Google's
# docs claim they're supported. Observed in May 2026 that any non-trivial
# schema with `maxItems` at multiple nesting levels makes the v1beta endpoint
# return a generic "Request contains an invalid argument" 400 — isolating the
# keyword alone passes, but the advisor's multi-level schema fails. The cap
# is informative (our prompts say "up to N items" in prose, and the persist
# layer is the actual enforcement), so we strip rather than fight the API.
_GEMINI_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "properties",
    "required",
    "items",
    "minimum",
    "maximum",
    "maxLength",
    "minLength",
}


def _enum_name(value: Any) -> str:
    """Best-effort rendering of a Gemini enum value as its human name.

    The SDK historically returned plain `Enum` members (`FinishReason.SAFETY`)
    but newer versions sometimes hand back the raw protobuf int or the
    string form. We try `.name`, then `str()`, so the surfaced error is
    always intelligible regardless of which shape the SDK uses.
    """
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(value)


def _clean_schema_for_gemini(schema: Any) -> Any:
    """Strip keys Gemini doesn't recognise from a JSON-Schema fragment.

    Two recursion shapes to handle:
    - A *schema node* is a dict whose keys are JSON-Schema keywords (type,
      properties, items, …). We keep only the keywords in `_GEMINI_SCHEMA_KEYS`
      and recurse into the values.
    - A *properties map* is a dict whose keys are field names mapping to
      schemas. The keys are arbitrary identifiers — we must NOT filter them,
      only clean the schema values they point to. Same goes for any future
      keyword whose value is "map of name → schema".

    `items` is itself a schema (or list of schemas in 2020-12, but we don't
    use that here) so it gets the keyword-filter treatment too.
    """
    if isinstance(schema, dict):
        cleaned: dict[str, Any] = {}
        for key, value in schema.items():
            if key not in _GEMINI_SCHEMA_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                # Field names are arbitrary identifiers — keep them all,
                # clean each value (which IS a schema).
                cleaned[key] = {fname: _clean_schema_for_gemini(fval) for fname, fval in value.items()}
            else:
                cleaned[key] = _clean_schema_for_gemini(value)
        return cleaned
    if isinstance(schema, list):
        return [_clean_schema_for_gemini(v) for v in schema]
    return schema


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key:
            raise AIProviderError(
                "GEMINI_API_KEY is empty — set ai_gemini_api_key in settings"
            )
        self._api_key = api_key
        self.model = model
        # Lazily-built genai client + the types module — same rationale as the
        # Anthropic / OpenAI providers: avoid rebuilding the client (and its
        # httpx pool) for every advisor / nl_query call.
        self._client: Any = None
        self._gtypes: Any = None

    def _get_client(self) -> tuple[Any, Any]:
        if self._client is not None and self._gtypes is not None:
            return self._client, self._gtypes
        try:
            from google import genai
            from google.genai import types as gtypes
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise AIProviderError(
                "google-genai SDK not installed (`pip install google-genai`)"
            ) from exc
        self._client = genai.Client(api_key=self._api_key)
        self._gtypes = gtypes
        return self._client, self._gtypes

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
        # Gemini's `cachedContents` API is heavier than what we need here —
        # for now just concat. Heavy users can wire explicit caching later.
        prompt = (cache_prefix + ("\n\n" if cache_prefix and prompt else "") + prompt) or prompt
        client, gtypes = self._get_client()

        config_kwargs: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            config_kwargs["tools"] = [
                gtypes.Tool(
                    function_declarations=[
                        gtypes.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            # Gemini accepts a strict subset of JSON Schema —
                            # strip the keys it doesn't know (additionalProperties,
                            # $schema, …) before sending. Anthropic/OpenAI take
                            # the full schema, so we keep `input_schema` rich on
                            # the ToolDef and only narrow it down here.
                            parameters=_clean_schema_for_gemini(t.input_schema),
                        )
                    ]
                )
                for t in tools
            ]
            # Force the function call so we don't have to parse a prose fallback.
            config_kwargs["tool_config"] = gtypes.ToolConfig(
                function_calling_config=gtypes.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=[tools[0].name],
                )
            )

        try:
            t0 = time.monotonic()
            resp = await client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=gtypes.GenerateContentConfig(**config_kwargs),
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
        except Exception as exc:
            raise AIProviderError(f"gemini API call failed: {exc}") from exc

        tool_call: ToolCall | None = None
        text_chunks: list[str] = []
        for candidate in resp.candidates or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                fc = getattr(part, "function_call", None)
                if fc and tool_call is None:
                    tool_call = ToolCall(name=fc.name, input=dict(fc.args or {}))
                text = getattr(part, "text", None)
                if text:
                    text_chunks.append(text)

        usage_meta = getattr(resp, "usage_metadata", None)
        usage = TokenUsage(
            prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
        )

        return AICompletion(
            text="\n".join(text_chunks) or None,
            tool_call=tool_call,
            usage=usage,
            raw={"latency_ms": elapsed_ms},
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
        """Real streaming for Gemini via `aio.models.generate_content_stream`.

        Each yielded chunk from the SDK carries either a text fragment, a
        `usage_metadata` block (cumulative — only the last chunk has the
        final totals), or both. We forward text fragments as `StreamDelta`
        and reserve the final `StreamDone` for the loop's tail so the
        usage totals reflect the whole call. The `asyncio.sleep(0)` after
        each text delta is the same cooperative-yield trick used in the
        Anthropic provider: lets the StreamingResponse writer drain the
        chunk to the socket before we await the next one.

        Tools aren't passed in the streaming path — the only call site
        (`/api/ai/query/stream`) renders Markdown progressively, which is
        incompatible with the all-or-nothing tool_use validation we do on
        the non-streaming endpoint.

        Mid-stream interruptions (SAFETY, RECITATION, BLOCKLIST,
        PROHIBITED_CONTENT, MAX_TOKENS, …) are surfaced as
        `AIProviderError` instead of swallowed: the SDK iterator naturally
        terminates when one of these trips, which historically left the
        Ask AI page sitting on a half-written answer with no indication
        why it stopped. We also catch `prompt_feedback.block_reason` for
        the whole-prompt block case (the model never produces any
        candidates at all).
        """
        import asyncio

        prompt = (cache_prefix + ("\n\n" if cache_prefix and prompt else "") + prompt) or prompt
        client, gtypes = self._get_client()
        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        full_text: list[str] = []
        usage = TokenUsage()
        terminal_reason: str | None = None
        terminal_message: str | None = None
        block_reason: str | None = None
        try:
            stream = await client.aio.models.generate_content_stream(
                model=self.model,
                contents=prompt,
                config=config,
            )
            async for chunk in stream:
                # `chunk.text` is the convenience accessor that returns the
                # concatenation of every text part in this chunk's first
                # candidate. It RAISES (ValueError) on multi-candidate
                # responses or chunks containing function_call/response
                # parts — we never use either, but guard anyway so a one-off
                # malformed chunk doesn't kill the whole stream.
                text: str | None = None
                try:
                    text = getattr(chunk, "text", None)
                except Exception:  # noqa: BLE001 - SDK property raises on edge cases
                    text = None
                if text is None:
                    parts_text: list[str] = []
                    for candidate in getattr(chunk, "candidates", []) or []:
                        content = getattr(candidate, "content", None)
                        if not content:
                            continue
                        for part in getattr(content, "parts", []) or []:
                            piece = getattr(part, "text", None)
                            if piece:
                                parts_text.append(piece)
                    text = "".join(parts_text)
                if text:
                    full_text.append(text)
                    yield StreamDelta(text=text)
                    await asyncio.sleep(0)

                # The whole *prompt* was rejected — the response carries
                # zero candidates, only `prompt_feedback.block_reason`. We
                # capture it so the final raise has the actual cause.
                pf = getattr(chunk, "prompt_feedback", None)
                pf_block = getattr(pf, "block_reason", None) if pf is not None else None
                if pf_block is not None:
                    block_reason = _enum_name(pf_block)

                # Per-candidate `finish_reason` — set only on the last chunk
                # of that candidate's stream. STOP / FINISH_REASON_UNSPECIFIED
                # are normal terminations; anything else is an interruption
                # the operator needs to see (SAFETY mid-answer is the common
                # one — Gemini's filters trip more often than Anthropic's).
                for candidate in getattr(chunk, "candidates", []) or []:
                    fr = getattr(candidate, "finish_reason", None)
                    if fr is None:
                        continue
                    fr_name = _enum_name(fr)
                    if fr_name in {"STOP", "FINISH_REASON_UNSPECIFIED"}:
                        continue
                    terminal_reason = fr_name
                    terminal_message = (
                        getattr(candidate, "finish_message", None) or None
                    )

                # Usage metadata is cumulative; the last non-None reading
                # wins. Reading it on every chunk keeps the code simple.
                meta = getattr(chunk, "usage_metadata", None)
                if meta is not None:
                    usage = TokenUsage(
                        prompt_tokens=getattr(meta, "prompt_token_count", 0) or 0,
                        completion_tokens=getattr(meta, "candidates_token_count", 0) or 0,
                    )
        except Exception as exc:
            raise AIProviderError(f"gemini stream failed: {exc}") from exc

        if block_reason is not None:
            raise AIProviderError(
                f"gemini blocked the prompt (reason: {block_reason})"
            )
        if terminal_reason is not None:
            detail = f" — {terminal_message}" if terminal_message else ""
            raise AIProviderError(
                f"gemini stopped mid-response (finish_reason={terminal_reason}{detail})"
            )

        yield StreamDone(text="".join(full_text), usage=usage)
