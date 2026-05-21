"""Natural-language Q&A over the network inventory.

Stateless: one POST = one question = one answer. The frontend keeps the
conversation history locally; we don't store it server-side because:
- The answers reference live entity state, so replaying old answers is
  misleading once the topology changes.
- Stored chat history is a privacy footgun (user-typed text + entity data
  preserved indefinitely) and there's no operator workflow that needs it.

The model gets the same compact topology snapshot used by suggest_links
and the advisor, plus a stricter system prompt scoped to "answer or say
you don't know" — no creative recommendations here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai import AIRunKind, AIRunLog
from app.services.ai.context import build_topology_context_cached
from app.services.ai.providers import get_provider
from app.services.ai.types import (
    AIProviderError,
    StreamDelta,
    StreamDone,
    ToolDef,
)

SYSTEM_PROMPT = """You are NetForge's answer-the-network-question assistant.

You receive a compact JSON snapshot of the operator's network (sites, rooms,
switches, ports, vlans, subnets, devices, existing links), optionally the
prior turns of the current conversation, and ONE new question from the
operator.

How to answer:
- Stick strictly to information present in the snapshot. If the answer
  isn't derivable, say so explicitly ("the snapshot doesn't contain X").
  Never make up port counts, IPs, vendors, etc.
- When prior turns are present, use them to resolve "it" / "this switch" /
  "the same room" etc. — but ALWAYS re-check the live snapshot for current
  values (entities may have changed since the earlier reply).
- Be concise. Two paragraphs max. Bullet lists for enumerations.
- When you reference an entity, also include it in `referenced_entities`
  so the UI can render a clickable chip. Use the entity's real `id` and
  `name` from the snapshot.
- Format the answer in Markdown — bold for emphasis, backticks for IDs /
  ports / CIDRs, lists when appropriate.
- Do not invent recommendations. The advisor exists for that — if the
  operator is asking "should I…?", say "the advisor on /insights surfaces
  these recommendations" and stop.

Return your output via the `answer_question` tool.
"""


def _render_history(history: list[dict]) -> str:
    """Stringify the conversation history into the user prompt.

    Each provider supports a real multi-turn `messages` array, but our
    `AIProvider` interface only exposes a single `prompt` string today.
    Encoding the history into the prompt keeps that contract intact while
    still giving the model the context it needs to resolve pronouns and
    follow-ups. The capped length (≤ 10 turns, ≤ 4 KB each — see the
    pydantic schema) makes the resulting prompt bounded.
    """
    if not history:
        return ""
    lines: list[str] = ["Conversation so far:"]
    for turn in history:
        raw_role = (turn.get("role") or "user").lower()
        # Whitelist: anything that isn't a known role is treated as USER. The
        # schema already enforces this for HTTP callers, but defending in the
        # service layer keeps a future internal caller from injecting a fake
        # "system" turn through the prompt.
        role = "ASSISTANT" if raw_role == "assistant" else "USER"
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        # Truncate any single turn one more time defensively — the schema
        # caps at 4000 chars but the prompt prefers tight context.
        if len(text) > 2000:
            text = text[:2000] + "…"
        lines.append(f"{role}: {text}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines) + "\n\n"

QUERY_TOOL = ToolDef(
    name="answer_question",
    description=(
        "Return a Markdown answer to the operator's question, plus the list "
        "of entities you referenced so the UI can render chips."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {
            "answer": {"type": "string", "maxLength": 4000},
            "referenced_entities": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "id"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "site",
                                "room",
                                "switch",
                                "port",
                                "vlan",
                                "subnet",
                                "device",
                            ],
                        },
                        "id": {"type": "integer", "minimum": 1},
                        "name": {"type": "string", "maxLength": 200},
                    },
                },
            },
        },
    },
)


@dataclass
class QueryAnswer:
    answer: str
    referenced_entities: list[dict]
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


async def run_query(
    db: AsyncSession,
    *,
    user_id: int | None,
    question: str,
    language_instruction: str | None = None,
    history: list[dict] | None = None,
) -> QueryAnswer:
    """Answer one natural-language question grounded in the live inventory.

    `language_instruction` carries the user's UI locale so the markdown
    answer comes back in the same language the user is reading. `history`
    is an optional list of past `{role, text}` dicts (server-stateless —
    the client replays the conversation each turn).
    """
    settings = get_settings()
    provider = get_provider()
    context, _was_cached = await build_topology_context_cached(db)
    payload = json.dumps(context, separators=(",", ":"), default=str)
    system = SYSTEM_PROMPT + (f"\n\n{language_instruction}" if language_instruction else "")

    rendered_history = _render_history(history or [])

    # Split the user message: the snapshot prefix is stable across follow-up
    # questions in the same conversation, so it gets `cache_prefix` (which
    # Anthropic translates into a `cache_control` breakpoint, letting a
    # second call within the 5-minute TTL pay the cache-read rate instead
    # of re-billing the full snapshot). History + question stay in `prompt`.
    cache_prefix = f"Network snapshot:\n```json\n{payload}\n```"
    dynamic_suffix = f"{rendered_history}Question: {question}"

    t0 = time.monotonic()
    error: str | None = None
    try:
        completion = await provider.call(
            system=system,
            prompt=dynamic_suffix,
            cache_prefix=cache_prefix,
            tools=[QUERY_TOOL],
            max_tokens=settings.ai_max_output_tokens,
            temperature=0.2,
        )
    except AIProviderError as exc:
        error = str(exc)
        completion = None
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    run = AIRunLog(
        user_id=user_id,
        kind=AIRunKind.nl_query,
        provider=provider.name,
        model=provider.model,
        prompt_tokens=completion.usage.prompt_tokens if completion else 0,
        completion_tokens=completion.usage.completion_tokens if completion else 0,
        latency_ms=elapsed_ms,
        success=error is None,
        error=error,
    )
    db.add(run)
    await db.commit()

    if not completion or not completion.tool_call:
        if error:
            raise AIProviderError(error)
        raise AIProviderError("provider returned no tool call")

    answer = str(completion.tool_call.input.get("answer", "")).strip()
    entities = completion.tool_call.input.get("referenced_entities") or []
    if not isinstance(entities, list):
        entities = []

    return QueryAnswer(
        answer=answer,
        referenced_entities=entities,
        provider=provider.name,
        model=provider.model,
        latency_ms=elapsed_ms,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
    )


# --- Streaming variant -----------------------------------------------------


# A small extra suffix for the streaming system prompt: we don't pass a tool,
# the model just emits Markdown text and we render it progressively.
_STREAM_SYSTEM_SUFFIX = """

In this STREAMING mode you DO NOT call a tool — write a Markdown answer
directly. Entity references are inline only; the UI renders the text but
does not pull out a separate chips list.
"""


def _lite_snapshot(context: dict) -> dict:
    """Reshape the full topology snapshot into an identifier-only summary.

    Drops free-text (descriptions, notes, vendor/model/serial, addresses)
    and most relational metadata; keeps just enough for the model to answer
    structural questions ("how many switches in site PAR?", "what's on
    VLAN 10?"). The token cost is roughly 10× smaller than the verbose
    snapshot — and operators who don't want sensitive fields leaving their
    network can flip this on per-question.
    """
    return {
        "sites": [{"id": s["id"], "name": s["name"], "code": s["code"]} for s in context.get("sites", [])],
        "rooms": [{"id": r["id"], "site_id": r["site_id"], "code": r["code"]} for r in context.get("rooms", [])],
        "switches": [
            {"id": s["id"], "name": s["name"], "room_id": s.get("room_id"), "site_id": s.get("site_id")}
            for s in context.get("switches", [])
        ],
        "vlans": [{"id": v["id"], "vlan_id": v["vlan_id"], "name": v["name"]} for v in context.get("vlans", [])],
        "subnets": [
            {"id": s["id"], "cidr": s["cidr"], "vlan_id": s.get("vlan_id"), "site_id": s.get("site_id")}
            for s in context.get("subnets", [])
        ],
        # Counts replace per-row lists for the high-cardinality tables —
        # the model rarely needs every device by name in lite mode.
        "device_count": len(context.get("devices", [])),
        "port_count": len(context.get("ports", [])),
        "existing_link_count": len(context.get("existing_links", [])),
    }


async def run_query_streaming(
    db: AsyncSession,
    *,
    user_id: int | None,
    question: str,
    history: list[dict] | None = None,
    language_instruction: str | None = None,
    lite_context: bool = False,
):
    """Async generator yielding `(event_name, payload)` pairs.

    The route layer wraps each yielded item into one SSE frame. We persist
    an `AIRunLog` row at the END of the stream so the Usage dashboard
    accounts for streaming calls just like one-shots; latency is the time
    until the LAST chunk arrives.

    `lite_context` swaps the full inventory snapshot for an identifier-only
    summary — see `_lite_snapshot` for the trade-off.
    """
    settings = get_settings()
    provider = get_provider()
    context, _was_cached = await build_topology_context_cached(db)
    if lite_context:
        context = _lite_snapshot(context)
    payload = json.dumps(context, separators=(",", ":"), default=str)

    system = SYSTEM_PROMPT + _STREAM_SYSTEM_SUFFIX
    if language_instruction:
        system = system + "\n\n" + language_instruction
    rendered_history = _render_history(history or [])
    cache_prefix = f"Network snapshot:\n```json\n{payload}\n```"
    dynamic_suffix = f"{rendered_history}Question: {question}"

    t0 = time.monotonic()
    full_text = ""
    final_usage = None
    error: str | None = None
    try:
        async for chunk in provider.stream_call(
            system=system,
            prompt=dynamic_suffix,
            cache_prefix=cache_prefix,
            max_tokens=settings.ai_max_output_tokens,
            temperature=0.2,
        ):
            if isinstance(chunk, StreamDelta):
                full_text += chunk.text
                yield ("delta", {"text": chunk.text})
            elif isinstance(chunk, StreamDone):
                final_usage = chunk.usage
                full_text = chunk.text or full_text
    except AIProviderError as exc:
        error = str(exc)
        yield ("error", {"message": error})
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Persist the run log — same shape as the non-streaming endpoint so the
    # Usage dashboard accounts for streaming + non-streaming calls together.
    run = AIRunLog(
        user_id=user_id,
        kind=AIRunKind.nl_query,
        provider=provider.name,
        model=provider.model,
        prompt_tokens=final_usage.prompt_tokens if final_usage else 0,
        completion_tokens=final_usage.completion_tokens if final_usage else 0,
        latency_ms=elapsed_ms,
        success=error is None,
        error=error,
    )
    db.add(run)
    await db.commit()

    if error is None:
        yield (
            "done",
            {
                "answer": full_text,
                "provider": provider.name,
                "model": provider.model,
                "latency_ms": elapsed_ms,
                "prompt_tokens": final_usage.prompt_tokens if final_usage else 0,
                "completion_tokens": final_usage.completion_tokens if final_usage else 0,
            },
        )
