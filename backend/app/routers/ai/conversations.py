"""Ask-AI conversation history.

Conversations are per-user persistent threads. They sit alongside the
existing one-shot /query and /query/stream endpoints — neither route
requires a conversation_id, but when one is supplied the user + assistant
turns are persisted into the matching `ai_conversations` row and the
server uses the persisted history instead of the client-supplied one.

This module owns the conversation CRUD routes plus
`swap_in_persisted_history()`, the helper both /query and /query/stream
call to do exactly that swap.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.routers.ai.common import _require_ai_enabled
from app.schemas.ai import (
    ConversationDetailRead,
    ConversationRead,
    ConversationTurnRead,
    ConversationUpdate,
)
from app.services.ai.conversations import (
    append_turn,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_turns,
    rename_conversation,
)

router = APIRouter()

# How many past turns are replayed to the model. Mirrors the client-side
# cap so a stale/hostile client cannot inflate the prompt.
_HISTORY_TURNS = 10


async def swap_in_persisted_history(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    question: str,
) -> list[dict[str, str]]:
    """Replace the client-supplied history with the server-persisted turns.

    The persisted version is authoritative — the client may have been
    opened on a different machine or refreshed. Also records the incoming
    user prompt so it survives even if the answer never lands.

    Raises whatever `get_conversation` raises (404) when the conversation
    is not the caller's.
    """
    await get_conversation(
        db, conversation_id=conversation_id, user_id=user_id
    )  # 404 if not the user's
    persisted = await list_turns(db, conversation_id=conversation_id)
    history = [
        {"role": t.role, "text": t.text} for t in persisted[-_HISTORY_TURNS:]
    ]
    await append_turn(
        db,
        conversation_id=conversation_id,
        role="user",
        text=question,
    )
    return history


@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def list_user_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ConversationRead]:
    """Return the operator's most-recent conversations, newest first.

    Each row carries `turn_count` + a short preview so the sidebar can
    render without N+1 round-trips for the per-conversation details.
    """
    _require_ai_enabled()
    rows = await list_conversations(db, user_id=user.id, limit=limit)
    return [ConversationRead(**r) for r in rows]


@router.post(
    "/conversations",
    response_model=ConversationRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_user_conversation(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """Open a fresh empty conversation. Title is filled lazily when the
    first user turn lands via POST /api/ai/query{,/stream} with the new
    `conversation_id` parameter."""
    _require_ai_enabled()
    conv = await create_conversation(db, user_id=user.id)
    return ConversationRead(
        id=conv.id,
        title=conv.title or "",
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turn_count=0,
        preview=None,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def get_user_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailRead:
    """Load one conversation with every turn embedded."""
    _require_ai_enabled()
    conv = await get_conversation(
        db, conversation_id=conversation_id, user_id=user.id
    )
    turns = await list_turns(db, conversation_id=conversation_id)
    return ConversationDetailRead(
        id=conv.id,
        title=conv.title or "",
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turn_count=len(turns),
        preview=None,
        turns=[
            ConversationTurnRead(
                id=t.id,
                role=t.role,
                text=t.text,
                entities=t.entities or [],
                latency_ms=t.latency_ms,
                created_at=t.created_at,
            )
            for t in turns
        ],
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def rename_user_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """Rename a conversation. Only the title is editable today."""
    _require_ai_enabled()
    conv = await rename_conversation(
        db,
        conversation_id=conversation_id,
        user_id=user.id,
        title=payload.title,
    )
    return ConversationRead(
        id=conv.id,
        title=conv.title or "",
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turn_count=0,
        preview=None,
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_user_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Erase a conversation + every turn under it (CASCADE)."""
    _require_ai_enabled()
    await delete_conversation(
        db, conversation_id=conversation_id, user_id=user.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
