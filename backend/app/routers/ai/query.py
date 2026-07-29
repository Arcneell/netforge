"""Natural-language query — the non-streaming `POST /ai/query`.

One free-text question, one structured answer (text + `referenced_entities`
chips), grounded in the live inventory. The Server-Sent-Events variant of
the same surface lives in `streaming.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.routers.ai.common import (
    _GENERIC_502_DETAIL,
    _require_ai_enabled,
    enforce_rate_limit,
    logger,
)
from app.routers.ai.conversations import swap_in_persisted_history
from app.schemas.ai import QueryAnswerRead, QueryRequest
from app.services.ai import AIProviderError, AIUnsupportedFeatureError
from app.services.ai.conversations import append_turn
from app.services.ai.locale import language_instruction as _lang_for
from app.services.ai.nl_query import run_query

router = APIRouter()


@router.post(
    "/query",
    response_model=QueryAnswerRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def ask_ai(
    payload: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> QueryAnswerRead:
    """Ask one free-text question grounded in the live inventory."""
    _require_ai_enabled()
    await enforce_rate_limit(user.id)

    # When a conversation_id is supplied, swap the client-supplied history
    # for the server-persisted turns of that conversation (the persisted
    # version is authoritative — the client may have been opened on a
    # different machine or refreshed). Server-side also enforces the same
    # 10-turn cap as the client.
    history = [t.model_dump() for t in payload.history]
    if payload.conversation_id is not None:
        history = await swap_in_persisted_history(
            db,
            conversation_id=payload.conversation_id,
            user_id=user.id,
            question=payload.question,
        )

    try:
        result = await run_query(
            db,
            user_id=user.id,
            question=payload.question,
            language_instruction=_lang_for(accept_language),
            history=history,
            lite_context=payload.lite_context,
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("nl-query crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=_GENERIC_502_DETAIL,
        ) from exc

    if payload.conversation_id is not None:
        await append_turn(
            db,
            conversation_id=payload.conversation_id,
            role="assistant",
            text=result.answer,
            entities=result.referenced_entities,
            latency_ms=result.latency_ms,
        )

    return QueryAnswerRead(**result.__dict__)
