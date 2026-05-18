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


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key:
            raise AIProviderError(
                "GEMINI_API_KEY is empty — set ai_gemini_api_key in settings"
            )
        self._api_key = api_key
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
        try:
            from google import genai
            from google.genai import types as gtypes
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise AIProviderError(
                "google-genai SDK not installed (`pip install google-genai`)"
            ) from exc

        client = genai.Client(api_key=self._api_key)

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
                            # Gemini accepts JSON Schema directly here, same as
                            # OpenAI's `parameters`.
                            parameters=t.input_schema,
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
        except Exception as exc:  # noqa: BLE001
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
