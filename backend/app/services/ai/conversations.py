"""Persistent storage for Ask-AI conversation threads.

Each conversation belongs to exactly one user (or to nobody if the user
was deleted — CASCADE wipes the rows). The service layer takes care of
the implicit "first user prompt becomes the title" convention so the
router doesn't have to special-case the first turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIConversation, AIConversationTurn
from app.services.errors import not_found


def _derive_title_from_prompt(prompt: str) -> str:
    """First user prompt → conversation title.

    Trims to 80 chars + ellipsis. Operators can rename via PATCH if the
    auto-derived title is awkward. We strip newlines so multi-line
    prompts collapse into a single sidebar entry.
    """
    text = " ".join((prompt or "").split())
    if len(text) <= 80:
        return text or "(empty conversation)"
    return text[:77] + "…"


async def create_conversation(
    db: AsyncSession, *, user_id: int | None
) -> AIConversation:
    """Open a fresh empty thread. Title is filled lazily when the first
    user turn lands (see `append_turns`)."""
    conv = AIConversation(user_id=user_id, title="")
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def get_conversation(
    db: AsyncSession, *, conversation_id: int, user_id: int | None
) -> AIConversation:
    """Fetch a conversation, scoped to the calling user.

    A conversation belongs to exactly one user — anyone else trying to
    load it (even another admin) gets 404. The intent here isn't
    paranoid access control (every authenticated user already has wide
    read access elsewhere), it's that chat threads are personal: an
    admin's prompts often expose ops-intent that other admins shouldn't
    casually browse.
    """
    conv = await db.get(AIConversation, conversation_id)
    if conv is None or (user_id is not None and conv.user_id != user_id):
        not_found("Conversation", conversation_id)
    return conv


async def list_conversations(
    db: AsyncSession, *, user_id: int | None, limit: int = 50
) -> list[dict[str, Any]]:
    """Return one row per conversation, ordered most-recent-first, with
    `turn_count` and `preview` populated server-side so the sidebar
    doesn't need a follow-up call per conversation.
    """
    # Subquery: (conversation_id, count(*), max(created_at) of last turn,
    # first user prompt for the preview).
    turn_stats = (
        select(
            AIConversationTurn.conversation_id.label("cid"),
            func.count(AIConversationTurn.id).label("turn_count"),
            func.min(AIConversationTurn.created_at)
                .filter(AIConversationTurn.role == "user")
                .label("first_user_at"),
        )
        .group_by(AIConversationTurn.conversation_id)
        .subquery()
    )

    base = (
        select(
            AIConversation.id,
            AIConversation.title,
            AIConversation.created_at,
            AIConversation.updated_at,
            func.coalesce(turn_stats.c.turn_count, 0).label("turn_count"),
        )
        .select_from(
            AIConversation.__table__.outerjoin(
                turn_stats, AIConversation.id == turn_stats.c.cid
            )
        )
        .order_by(AIConversation.updated_at.desc())
        .limit(limit)
    )
    if user_id is not None:
        base = base.where(AIConversation.user_id == user_id)

    rows = (await db.execute(base)).all()
    if not rows:
        return []

    # Second pass: pull the first user turn's text for each surfaced
    # conversation in one round-trip. Keeps the list endpoint at O(2)
    # queries regardless of result size.
    conv_ids = [r.id for r in rows]
    previews_rows = (
        await db.execute(
            select(
                AIConversationTurn.conversation_id,
                AIConversationTurn.text,
            )
            .where(
                AIConversationTurn.conversation_id.in_(conv_ids),
                AIConversationTurn.role == "user",
            )
            .order_by(
                AIConversationTurn.conversation_id,
                AIConversationTurn.created_at,
            )
        )
    ).all()
    # Dedup by conversation_id — only keep the earliest (first) user turn.
    preview_by_id: dict[int, str] = {}
    for cid, text in previews_rows:
        if cid not in preview_by_id:
            preview_by_id[cid] = text[:200]

    return [
        {
            "id": r.id,
            "title": r.title or preview_by_id.get(r.id, "")[:80] or "(empty)",
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "turn_count": int(r.turn_count or 0),
            "preview": preview_by_id.get(r.id),
        }
        for r in rows
    ]


async def list_turns(
    db: AsyncSession, *, conversation_id: int
) -> Sequence[AIConversationTurn]:
    """Return every turn of `conversation_id`, oldest first."""
    rows = await db.execute(
        select(AIConversationTurn)
        .where(AIConversationTurn.conversation_id == conversation_id)
        .order_by(AIConversationTurn.created_at, AIConversationTurn.id)
    )
    return rows.scalars().all()


async def append_turn(
    db: AsyncSession,
    *,
    conversation_id: int,
    role: str,
    text: str,
    entities: list[dict] | None = None,
    latency_ms: int | None = None,
) -> AIConversationTurn:
    """Persist one turn and bump the conversation's `updated_at`.

    Side-effect on user turns: if the conversation title is still empty,
    derive it from the prompt. This keeps the create-then-first-turn
    flow ergonomic — clients don't have to PATCH the title themselves.
    """
    if role not in ("user", "assistant"):
        raise ValueError(f"unsupported role: {role!r}")
    turn = AIConversationTurn(
        conversation_id=conversation_id,
        role=role,
        text=text,
        entities=entities,
        latency_ms=latency_ms,
    )
    db.add(turn)
    await db.flush()  # need turn.id to round-trip back to the API

    # Bump the parent's updated_at so list-by-recency works. Also set
    # the auto-title on the first user prompt.
    conv = await db.get(AIConversation, conversation_id)
    if conv is not None:
        if role == "user" and not conv.title:
            conv.title = _derive_title_from_prompt(text)
        # Updated_at is on the model's `onupdate=func.now()`, so any
        # column assignment triggers it. Touch `title` to None and back
        # if there's nothing else to set — but the title path above
        # already does that. For pure assistant appends, force-bump:
        if role == "assistant":
            conv.title = conv.title  # no-op assignment to fire onupdate
    await db.commit()
    await db.refresh(turn)
    return turn


async def rename_conversation(
    db: AsyncSession, *, conversation_id: int, user_id: int | None, title: str
) -> AIConversation:
    conv = await get_conversation(
        db, conversation_id=conversation_id, user_id=user_id
    )
    conv.title = title.strip()[:200]
    await db.commit()
    await db.refresh(conv)
    return conv


async def delete_conversation(
    db: AsyncSession, *, conversation_id: int, user_id: int | None
) -> None:
    conv = await get_conversation(
        db, conversation_id=conversation_id, user_id=user_id
    )
    await db.delete(conv)
    await db.commit()
