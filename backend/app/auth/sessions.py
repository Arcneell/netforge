"""Session lifecycle: create / load / sliding renewal / delete + cookie helpers.

The session cookie holds an opaque random token. The actual session data lives
in the `sessions` table — that gives us instant revocation (logout, force-out,
account disable) which JWTs do not.

Storage rule (same trick as `services/api_tokens.py`): the DB never stores the
cookie value itself, only its SHA-256 hex digest as the primary key. A leaked
DB dump (or an over-broad read grant) therefore can't be replayed as a login —
the digest is useless without its preimage, and every lookup/delete hashes the
incoming cookie value before touching the table.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.user import Session, User
from app.utils.request import client_ip

# Renew the session whenever less than this much time is left on the clock.
_RENEW_THRESHOLD = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def hash_session_id(session_id: str) -> str:
    """SHA-256 hex digest of the cookie token — 64 chars, fits the
    `sessions.id` String(64) column. Mirrors `api_tokens._hash`."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


async def create_session(
    db: AsyncSession,
    user: User,
    request: Request,
    settings: Settings,
) -> tuple[Session, str]:
    """Create a fresh session for `user` and persist it.

    Returns ``(session, token)`` — same contract as
    `api_tokens.create_token`: the row stores only the SHA-256 digest of
    the token, and the plaintext `token` (the future cookie value) is
    returned exactly once for the caller to hand to `set_session_cookie`.
    """
    # Opportunistic purge: expired rows are dead weight (lookups filter on
    # `expires_at` anyway) and nothing else deletes them, so the table
    # would grow forever. Logins are rare enough that sweeping here costs
    # nothing — same lazy-cleanup idea as the `webhook_deliveries` purge
    # in `services/webhooks.py`, without needing a background task.
    await db.execute(delete(Session).where(Session.expires_at <= _utcnow()))

    token = secrets.token_urlsafe(32)
    sess = Session(
        id=hash_session_id(token),
        user_id=user.id,
        expires_at=_utcnow() + timedelta(seconds=settings.session_max_age_seconds),
        # Use the same trust order as the audit log (X-Real-IP first,
        # immediate peer as fallback) so admins troubleshooting "where
        # did this login come from?" see the real client IP instead of
        # the nginx loopback peer behind a reverse proxy.
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess, token


async def get_active_session(db: AsyncSession, session_id: str) -> Session | None:
    """Return the session if it exists AND is not expired.

    `session_id` is the raw cookie value; it is hashed before the lookup
    because the table stores digests only.
    """
    result = await db.execute(
        select(Session).where(
            Session.id == hash_session_id(session_id),
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
    """Delete by raw cookie value — hashed to match the stored digest."""
    await db.execute(delete(Session).where(Session.id == hash_session_id(session_id)))
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
