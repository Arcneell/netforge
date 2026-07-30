"""Personal access tokens — issue, verify, revoke.

Plaintext format: ``nfp_<43 url-safe base64 chars>``. The ``nfp_`` prefix lets
log scrubbers grep for accidental leaks; the body is 32 bytes of CSPRNG so
brute force is impractical.

Storage: only the SHA-256 digest is persisted (`token_hash`). A leak of the
DB therefore can't be replayed against the API — same trick as GitHub PATs.
``prefix`` keeps the first ~8 visible chars (e.g. ``nfp_abcd``) for the
management UI so admins can recognise a token without seeing its secret.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.user import ApiToken, ApiTokenScope, User
from app.services.errors import not_found

TOKEN_PREFIX = "nfp_"
_BODY_BYTES = 32  # 32 raw bytes → 43 url-safe base64 chars
_PREFIX_VISIBLE_CHARS = 8  # "nfp_" + 4 more


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _hash(plaintext: str) -> str:
    """SHA-256 hex digest of the plaintext token."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_plaintext() -> tuple[str, str]:
    """Build a fresh plaintext token and return ``(plaintext, prefix)``."""
    plaintext = f"{TOKEN_PREFIX}{secrets.token_urlsafe(_BODY_BYTES)}"
    return plaintext, plaintext[:_PREFIX_VISIBLE_CHARS]


async def create_token(
    db: AsyncSession,
    user: User,
    name: str,
    expires_at: datetime | None = None,
    scope: ApiTokenScope = ApiTokenScope.full,
) -> tuple[ApiToken, str]:
    """Mint a token for ``user``. Returns the persisted row plus the *one
    and only* plaintext copy — caller is responsible for surfacing it.
    """
    plaintext, prefix = _generate_plaintext()
    row = ApiToken(
        user_id=user.id,
        name=name,
        token_hash=_hash(plaintext),
        prefix=prefix,
        expires_at=expires_at,
        scope=scope,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, plaintext


async def list_tokens(db: AsyncSession, user: User) -> list[ApiToken]:
    """Every token the user owns, most recent first. Includes revoked /
    expired entries on purpose: an admin reviewing history should still see
    what was issued, even after revocation."""
    rows = await db.execute(
        select(ApiToken)
        .where(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
    )
    return list(rows.scalars().all())


async def revoke_token(db: AsyncSession, user: User, token_id: int) -> None:
    """Mark a token as revoked. Idempotent: revoking twice is a no-op (the
    second call returns 404 only if the row never existed, not if it was
    already revoked)."""
    row = (
        await db.execute(
            select(ApiToken).where(
                ApiToken.id == token_id,
                ApiToken.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        not_found("API token", token_id)
    if row.revoked_at is None:
        row.revoked_at = _utcnow()
        await db.commit()


async def verify_token(
    db: AsyncSession, plaintext: str
) -> tuple[User, ApiTokenScope] | None:
    """Resolve a plaintext token to its owning user, or None if invalid.

    Returns the user alongside the token's `scope` — the caller
    (`app.auth.dependencies.get_current_user`) is responsible for capping
    the effective role to viewer when the scope is `read_only`; this
    function only reports what was stored, it never mutates the user.

    Best-effort updates `last_used_at` on a successful verify so admins
    can spot stale tokens. The update runs in its own short transaction
    via a side session — the enclosing request session is the read path
    for GET endpoints (the typical bearer-auth use case: scripts polling
    `/api/devices`), and `get_session` doesn't commit at teardown, so a
    plain `await db.execute(update(...))` was silently dropped on read
    endpoints. Side-session keeps the timestamp accurate regardless of
    what the surrounding handler decides to commit or roll back.
    """
    if not plaintext.startswith(TOKEN_PREFIX):
        return None

    digest = _hash(plaintext)
    now = _utcnow()
    row = (
        await db.execute(select(ApiToken).where(ApiToken.token_hash == digest))
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= now:
        return None

    user = await db.get(User, row.user_id)
    if user is None:
        # User deleted (CASCADE should have removed the token, but defend
        # against race conditions) — treat as unauthenticated.
        return None

    await _touch_last_used_at(row.id, now)
    # `row.scope` is only unset (None) for a bare in-memory ApiToken built
    # without going through a flush (e.g. older tests) — treat that the same
    # as the column's own default, `full`, rather than crashing the comparison
    # in the auth dependency.
    return user, (row.scope or ApiTokenScope.full)


async def _touch_last_used_at(token_id: int, when: datetime) -> None:
    """Side-session UPDATE for `last_used_at`. Best-effort: a transient
    DB error here must not deny an otherwise-valid bearer-auth request.
    """
    import contextlib

    with contextlib.suppress(Exception):
        async with SessionLocal() as side:
            await side.execute(
                update(ApiToken)
                .where(ApiToken.id == token_id)
                .values(last_used_at=when)
            )
            await side.commit()
