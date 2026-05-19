"""Session lifecycle: create / load / sliding renewal / delete + cookie helpers.

The session cookie holds an opaque random token. The actual session data lives
in the `sessions` table — that gives us instant revocation (logout, force-out,
account disable) which JWTs do not.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.user import Session, User

# Renew the session whenever less than this much time is left on the clock.
_RENEW_THRESHOLD = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def create_session(
    db: AsyncSession,
    user: User,
    request: Request,
    settings: Settings,
) -> Session:
    """Create a fresh session for `user` and persist it."""
    sess = Session(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=_utcnow() + timedelta(seconds=settings.session_max_age_seconds),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess


async def get_active_session(db: AsyncSession, session_id: str) -> Session | None:
    """Return the session if it exists AND is not expired."""
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.expires_at > _utcnow(),
        )
    )
    return result.scalar_one_or_none()


async def touch_session(
    db: AsyncSession, session: Session, settings: Settings
) -> None:
    """Sliding renewal: push `expires_at` back if we're close to expiry."""
    if session.expires_at - _utcnow() >= _RENEW_THRESHOLD:
        return
    new_expires = _utcnow() + timedelta(seconds=settings.session_max_age_seconds)
    await db.execute(
        update(Session).where(Session.id == session.id).values(expires_at=new_expires)
    )
    await db.commit()


async def delete_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


# --- Cookie helpers --------------------------------------------------------


def get_session_id_from_cookie(request: Request, settings: Settings) -> str | None:
    return request.cookies.get(settings.session_cookie_name)


def set_session_cookie(response: Response, session_id: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
