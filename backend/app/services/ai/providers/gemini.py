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
from typing import Any

from app.services.ai.types import (
    AICompletion,
    AIProviderError,
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
