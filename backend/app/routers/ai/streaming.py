"""Streaming Ask AI — `POST /ai/query/stream`.

Server-Sent-Events transport for the same natural-language query surface
as `query.py`. Everything specific to SSE lives here: frame formatting,
the anti-buffering headers, and persisting the assistant turn once the
stream (or the client) is done.
"""

from __future__ import annotations

import asyncio as _asyncio
import json as _json

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.routers.ai.common import _require_ai_enabled, enforce_rate_limit, logger
from app.routers.ai.conversations import swap_in_persisted_history
from app.schemas.ai import QueryRequest
from app.services.ai.conversations import append_turn
from app.services.ai.locale import language_instruction as _lang_for
from app.services.ai.nl_query import run_query_streaming

router = APIRouter()


@router.post(
    "/query/stream",
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def ask_ai_stream(
    payload: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> StreamingResponse:
    """Server-Sent-Events variant of `/api/ai/query`.

    The client receives incremental `delta` frames as the model writes,
    plus a final `done` frame carrying token usage + latency. Tool calls
    are NOT used in this path — the answer is Markdown text only (entity
    references stay inline). The non-streaming endpoint remains available
    for callers that need the structured `referenced_entities` chips.
    """
    _require_ai_enabled()
    await enforce_rate_limit(user.id)

    # If a conversation_id is supplied, swap the client-supplied history
    # for the persisted turns and record the user prompt BEFORE the stream
    # starts. The assistant text is accumulated below from the delta
    # frames and persisted on the `done` event.
    history = [t.model_dump() for t in payload.history]
    if payload.conversation_id is not None:
        history = await swap_in_persisted_history(
            db,
            conversation_id=payload.conversation_id,
            user_id=user.id,
            question=payload.question,
        )

    async def _stream():
        # SSE preamble — a no-op comment frame (`: ...\n\n`) sent before any
        # real event. Forces the HTTP layer to flush response headers and the
        # 2-KB-or-so of headroom that some proxies (notably nginx with
        # `proxy_buffering` left on, and some Node http-proxy stacks)
        # accumulate before delivering the first byte to the client. Without
        # it, very small first deltas can sit in the pipeline until the next
        # one piles on top.
        yield ": ok\n\n"

        # Accumulate the assistant's emitted text so we can persist a
        # single AIConversationTurn on the `done` frame. The streaming
        # provider sends one `delta` frame per token chunk; concatenating
        # them reconstructs the full reply.
        assistant_text_parts: list[str] = []
        done_latency_ms: int | None = None
        try:
            async for event_name, data in run_query_streaming(
                db,
                user_id=user.id,
                question=payload.question,
                history=history,
                language_instruction=_lang_for(accept_language),
                lite_context=payload.lite_context,
            ):
                if event_name == "delta" and isinstance(data, dict):
                    delta_text = data.get("text") or data.get("delta") or ""
                    if isinstance(delta_text, str):
                        assistant_text_parts.append(delta_text)
                if event_name == "done" and isinstance(data, dict):
                    latency = data.get("latency_ms")
                    if isinstance(latency, int):
                        done_latency_ms = latency
                # SSE wire format: `event:` line is optional, `data:` line
                # carries the JSON body, blank line terminates the frame.
                yield f"event: {event_name}\ndata: {_json.dumps(data)}\n\n"
                # Cooperative yield: lets the StreamingResponse writer
                # actually drain the chunk to the socket before we wait on
                # the next provider delta. Cheap insurance against the event
                # loop holding multiple chunks in one tick.
                await _asyncio.sleep(0)
        except Exception as exc:
            logger.exception("nl-query stream crashed")
            yield f"event: error\ndata: {_json.dumps({'message': str(exc)})}\n\n"
        finally:
            # Persist the assistant turn even on partial / interrupted
            # streams — the operator sees what the model managed to
            # produce when they reload the conversation, and the
            # comparison with `expected length` lets them decide
            # whether to retry. Empty completions are skipped.
            if payload.conversation_id is not None:
                full_text = "".join(assistant_text_parts).strip()
                if full_text:
                    try:
                        await append_turn(
                            db,
                            conversation_id=payload.conversation_id,
                            role="assistant",
                            text=full_text,
                            latency_ms=done_latency_ms,
                        )
                    except Exception:
                        # The stream is already over from the client's
                        # POV — losing the persisted assistant turn is a
                        # bug but not a request-level error. Logged so
                        # ops can investigate without breaking the user
                        # response.
                        logger.exception(
                            "failed to persist assistant turn for "
                            "conversation_id=%s",
                            payload.conversation_id,
                        )

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            # Tell nginx (and any other reverse proxy) NOT to buffer — SSE
            # only works end-to-end when each frame is flushed immediately.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
