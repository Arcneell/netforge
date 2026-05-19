"""Provider-agnostic types — kept tiny so providers stay easy to add.

The shape mirrors what every major chat-completion API exposes:
- A `system` prompt
- A user `prompt`
- Optional `tools` (function calling) with a JSON-Schema input
- A response that either holds free `text` or a parsed `tool_call`

Streaming, multi-turn conversations, vision and structured output beyond a
single tool call are intentionally out of scope for v1 — every feature
NetForge needs (suggest_links, advisor, nl_query) fits this minimal shape
and adding more later is additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AIProviderError(RuntimeError):
    """Wraps any provider-side failure (network, auth, rate limit, parse).

    Always raised from inside `AIProvider.call()` / `stream_call()`;
    routers translate it to a 502 so the operator can tell "the LLM call
    failed" from "your business rules rejected the input".
    """


class AIUnsupportedFeatureError(AIProviderError):
    """Raised by stub providers (or providers missing a capability) so the
    caller can either fall back to another provider or surface a clear
    "this provider does not support tools" message.
    """


@dataclass(frozen=True)
class ToolDef:
    """A function the LLM is allowed to call.

    `input_schema` is a JSON Schema object — keep it strict (additionalProperties:
    false, every field required if you mean it) so the model has unambiguous
    instructions and we can validate the output against it before persisting.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class AICompletion:
    """Either `text` is set (free-text answer) or `tool_call` is set.

    We don't expose multi-tool-call chains in v1 — the contract is "either
    talk to me or pick one tool". This keeps the surface tiny and matches
    how all three providers behave when you only give them one tool.
    """

    text: str | None = None
    tool_call: ToolCall | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    # Provider-specific raw response, kept for debugging. Never persisted.
    raw: Any = None


@dataclass(frozen=True)
class StreamDelta:
    """One incremental text chunk yielded by a streaming provider call."""

    text: str


@dataclass(frozen=True)
class StreamDone:
    """Final marker emitted once the stream is exhausted. Carries the
    aggregated usage + the full text (cheaper than re-assembling client-
    side from the deltas)."""

    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)


# A streaming call yields a sequence of `StreamDelta` followed by exactly
# one `StreamDone` at the end. Errors raise `AIProviderError` directly —
# the route layer catches and translates them into an SSE `error` frame.
StreamChunk = StreamDelta | StreamDone
