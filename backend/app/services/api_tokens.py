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

from app.models.user import ApiToken, User
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


async def verify_token(db: AsyncSession, plaintext: str) -> User | None:
    """Resolve a plaintext token to its owning user, or None if invalid.

    Best-effort updates `last_used_at` on a successful verify so admins can
    spot stale tokens. The write is fired in the same transaction as the
    enclosing request — a tiny cost but the call is on every API request
    using Bearer auth, so we keep it to a single UPDATE without re-SELECTing.
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

    # Single UPDATE, no SELECT round-trip. We commit at the end of the
    # request alongside any other writes the handler may have done.
    await db.execute(
        update(ApiToken).where(ApiToken.id == row.id).values(last_used_at=now)
    )
    return user
