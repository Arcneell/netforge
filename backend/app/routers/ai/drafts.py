"""NL-to-action drafts — draft, list, apply, reject.

The riskiest AI surface: `apply` actually mutates the inventory. Gated by
its own `AI_DRAFTS_ENABLED` sub-flag on top of the master switch, and the
model never executes anything itself — a draft sits at `status=pending`
until an admin explicitly applies it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.ai import AIActionDraft
from app.models.user import User, UserRole
from app.routers.ai.common import (
    _GENERIC_502_DETAIL,
    _require_drafts_enabled,
    enforce_rate_limit,
    logger,
)
from app.schemas.ai import ActionDraftCreate, ActionDraftRead
from app.services.ai import AIProviderError, AIUnsupportedFeatureError
from app.services.ai.actions import apply_draft, draft_action, reject_draft
from app.services.ai.locale import language_instruction as _lang_for
from app.services.errors import http_error, match_constraint

router = APIRouter()


@router.post(
    "/drafts",
    response_model=ActionDraftRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_draft(
    payload: ActionDraftCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> ActionDraftRead:
    """Ask the LLM to draft one CRUD action from a free-text prompt.

    NEVER executes the action — the resulting row sits at `status=pending`
    until an admin POSTs to `/drafts/{id}/apply`."""
    _require_drafts_enabled()
    await enforce_rate_limit(user.id)

    try:
        draft = await draft_action(
            db,
            user_id=user.id,
            prompt=payload.prompt,
            language_instruction=_lang_for(accept_language),
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        # 422 — the call itself worked, the model just couldn't produce a
        # valid draft. Keeping 502 for true provider/HTTP failures.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("draft_action crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=_GENERIC_502_DETAIL,
        ) from exc
    return ActionDraftRead.model_validate(draft)


@router.get(
    "/drafts",
    response_model=list[ActionDraftRead],
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def list_drafts(db: AsyncSession = Depends(get_db)) -> list[ActionDraftRead]:
    """Return drafts, newest first. The UI typically filters to pending."""
    rows = (
        (
            await db.execute(
                select(AIActionDraft).order_by(AIActionDraft.created_at.desc()).limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [ActionDraftRead.model_validate(r) for r in rows]


@router.post(
    "/drafts/{draft_id}/apply",
    response_model=ActionDraftRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def apply_draft_route(
    draft_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActionDraftRead:
    """Execute the draft against the inventory. Idempotent in the sense
    that the second call returns 409 — the first apply marks the row
    `applied`.

    Error mapping:
        404 — draft not found
        409 — draft already applied/rejected, OR a DB-level conflict raised
              by the applier (subnet overlap, duplicate site code, missing
              referenced VLAN, …). The draft row is marked `failed` and the
              `error_message` is surfaced to the operator.
        502 — anything else (transient DB error, unexpected internal bug).
              The draft is also marked `failed`; the message is in `detail`
              so the UI can show it.
    """
    _require_drafts_enabled()
    try:
        draft = await apply_draft(db, draft_id=draft_id, user_id=user.id)
    except LookupError as exc:
        http_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc))
    except ValueError as exc:
        http_error(status.HTTP_409_CONFLICT, "DRAFT_INVALID", str(exc))
    except IntegrityError as exc:
        # The applier already rolled back and marked the draft as
        # `failed`. Translate the constraint name into the same friendly
        # code+message pair that the canonical `catch_integrity_errors`
        # helper would have produced — operators see
        # "This CIDR overlaps an existing subnet" instead of the raw
        # asyncpg `ExclusionViolationError: ... subnets_no_overlap_global`
        # dump.
        raw = str(getattr(exc, "orig", exc)) or "database integrity violation"
        match = match_constraint(raw)
        if match:
            code, friendly = match
        else:
            code, friendly = "INTEGRITY_VIOLATION", "Data integrity violation."
        http_error(status.HTTP_409_CONFLICT, code, friendly, details={"raw": raw[:500]})
    except Exception:
        logger.exception("draft apply crashed (draft_id=%s)", draft_id)
        http_error(
            status.HTTP_502_BAD_GATEWAY,
            "AI_APPLY_FAILED",
            _GENERIC_502_DETAIL,
        )
    return ActionDraftRead.model_validate(draft)


@router.post(
    "/drafts/{draft_id}/reject",
    response_model=ActionDraftRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def reject_draft_route(
    draft_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActionDraftRead:
    """Mark the draft as rejected — the operator declined to apply it."""
    _require_drafts_enabled()
    try:
        draft = await reject_draft(db, draft_id=draft_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ActionDraftRead.model_validate(draft)
