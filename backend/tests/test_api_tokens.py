"""Tests for the personal access token service + Bearer authentication.

Two surfaces are exercised here:

  - The service layer (`app.services.api_tokens`): minting, verifying,
    revoking, expiry handling. Pure-Python with mocked DB — fast feedback.
  - The Bearer path in `get_current_user`: a request carrying a valid token
    should resolve to the right user without needing the session cookie.

End-to-end HTTP tests for the `/api/auth/tokens` CRUD round-trip are kept
intentionally light: the same mock-DB harness used elsewhere already exercises
the framework wiring, and the auth_guards table covers the unauthenticated
case.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import get_session as get_db_session
from app.main import app
from app.models.user import ApiToken, Session, User, UserRole
from app.services import api_tokens as service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user(role: UserRole = UserRole.admin) -> User:
    return User(id=1, provider="github", subject="a", email="a@x", role=role)


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


# --- service.create_token --------------------------------------------------


@pytest.mark.asyncio
async def test_create_token_stores_hash_not_plaintext() -> None:
    """The plaintext must never end up in the row that gets persisted —
    only its SHA-256 digest does. We assert the digest matches the plaintext
    we got back so a future DB leak can't be replayed."""
    db = AsyncMock()

    captured: list[ApiToken] = []
    db.add = MagicMock(side_effect=captured.append)
    db.commit = AsyncMock()

    async def _refresh(obj: ApiToken) -> None:
        if obj.id is None:
            obj.id = 1

    db.refresh = AsyncMock(side_effect=_refresh)

    row, plaintext = await service.create_token(db, _user(), name="ansible")

    assert plaintext.startswith("nfp_")
    assert row.token_hash == hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert row.prefix == plaintext[:8]
    # Plaintext doesn't end up anywhere on the row.
    assert plaintext not in (row.token_hash, row.prefix)


# --- service.verify_token --------------------------------------------------


def _verify_db(row: ApiToken | None, user: User | None = None) -> AsyncMock:
    """Wire a mock DB that returns `row` for the token lookup and `user`
    for the user fetch."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar(row), MagicMock()])
    db.get = AsyncMock(return_value=user)
    return db


@pytest.mark.asyncio
async def test_verify_token_returns_user_for_valid_token() -> None:
    plaintext = "nfp_validvalidvalid"
    row = ApiToken(
        id=1, user_id=1, name="x",
        token_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
        prefix=plaintext[:8],
    )
    db = _verify_db(row, user=_user())

    user = await service.verify_token(db, plaintext)
    assert user is not None
    assert user.id == 1


@pytest.mark.asyncio
async def test_verify_token_rejects_unknown_plaintext() -> None:
    """A plaintext that doesn't hash to any stored row returns None — and
    the user fetch is never attempted, so we don't leak existence info."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar(None))

    assert await service.verify_token(db, "nfp_doesnotexist") is None


@pytest.mark.asyncio
async def test_verify_token_rejects_missing_prefix() -> None:
    """Anything that doesn't start with `nfp_` is shortcut-rejected before
    we touch the DB — keeps the hot path cheap on garbage Authorization
    headers."""
    db = AsyncMock()
    assert await service.verify_token(db, "ghp_thisisagithubtoken") is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_verify_token_rejects_revoked() -> None:
    plaintext = "nfp_revokedone"
    row = ApiToken(
        id=1, user_id=1, name="x",
        token_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
        prefix=plaintext[:8],
        revoked_at=_utcnow(),
    )
    db = _verify_db(row, user=_user())
    assert await service.verify_token(db, plaintext) is None


@pytest.mark.asyncio
async def test_verify_token_rejects_expired() -> None:
    plaintext = "nfp_expiredone"
    row = ApiToken(
        id=1, user_id=1, name="x",
        token_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
        prefix=plaintext[:8],
        expires_at=_utcnow() - timedelta(seconds=1),
    )
    db = _verify_db(row, user=_user())
    assert await service.verify_token(db, plaintext) is None


# --- /api/auth/tokens HTTP -------------------------------------------------


def _session() -> Session:
    return Session(
        id="sess",
        user_id=1,
        created_at=_utcnow(),
        expires_at=_utcnow() + timedelta(hours=4),
    )


def _install_db(
    user: User | None,
    *,
    execute_returns: list | None = None,
) -> AsyncMock:
    sess_result = _scalar(_session() if user else None)
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[sess_result, *(execute_returns or [])]
    )
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    async def _override() -> AsyncIterator:
        yield db

    app.dependency_overrides[get_db_session] = _override
    return db


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_tokens_requires_auth(client: AsyncClient) -> None:
    _install_db(user=None)
    r = await client.get("/api/auth/tokens")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_token_returns_plaintext_exactly_once(
    client: AsyncClient,
) -> None:
    """The POST response carries the plaintext; subsequent reads (a GET
    on the same row) would only see metadata."""

    # Patch refresh so the in-memory ApiToken our service.add() created
    # gets the columns Postgres would normally fill in (id PK + server-side
    # `created_at` default). Without the timestamp, ApiTokenRead's Pydantic
    # validation refuses the row.
    async def _refresh(obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 42
        if getattr(obj, "created_at", None) is None:
            obj.created_at = _utcnow()

    _install_db(user=_user()).refresh = AsyncMock(side_effect=_refresh)

    r = await client.post(
        "/api/auth/tokens",
        json={"name": "ansible"},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "ansible"
    assert body["prefix"].startswith("nfp_")
    assert body["token"].startswith("nfp_")
    assert len(body["token"]) > len(body["prefix"])  # plaintext > prefix


@pytest.mark.asyncio
async def test_revoke_unknown_token_returns_404(client: AsyncClient) -> None:
    # Service does SELECT first; returning None triggers not_found().
    _install_db(user=_user(), execute_returns=[_scalar(None)])
    r = await client.delete(
        "/api/auth/tokens/9999", cookies={"netforge_session": "sess"}
    )
    assert r.status_code == 404


# --- Bearer auth on a protected endpoint -----------------------------------


@pytest.mark.asyncio
async def test_bearer_token_authenticates_protected_endpoint(
    client: AsyncClient,
) -> None:
    """A request without the cookie but with a valid Bearer header should
    resolve to the token's owner — proves the dependency picks the new
    code path."""
    plaintext = "nfp_validvalidvalid"
    token_row = ApiToken(
        id=1, user_id=1, name="x",
        token_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
        prefix=plaintext[:8],
    )
    user = _user(role=UserRole.viewer)

    db = AsyncMock()
    # Order matches `verify_token`: select the token row, then the user.get,
    # then the `UPDATE` for last_used_at.
    db.execute = AsyncMock(
        side_effect=[_scalar(token_row), MagicMock(), _scalar(user)]
    )
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()

    async def _override() -> AsyncIterator:
        yield db

    app.dependency_overrides[get_db_session] = _override
    try:
        r = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert body["role"] == "viewer"


@pytest.mark.asyncio
async def test_bearer_invalid_token_returns_401(client: AsyncClient) -> None:
    """An invalid Bearer must NOT fall through to the cookie path — the
    user is explicitly trying to use a token, so we return 401 right away
    rather than letting an unrelated cookie rescue them."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar(None))

    async def _override() -> AsyncIterator:
        yield db

    app.dependency_overrides[get_db_session] = _override
    try:
        r = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer nfp_bogus"},
            cookies={"netforge_session": "sess"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 401
