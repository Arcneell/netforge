"""Integration tests for /api/auth/me and /api/auth/logout.

These exercise the full FastAPI stack — auth dependency, session lookup,
cookie handling — but with the DB and provider replaced by mocks.
End-to-end OAuth flow tests are out of scope here: that is authlib's
responsibility, not ours.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session as get_db_session
from app.main import app
from app.models.user import Session, User, UserRole


def _make_user() -> User:
    return User(
        id=1,
        provider="github",
        subject="42",
        email="alice@example.com",
        display_name="Alice",
        role=UserRole.admin,
    )


def _make_session(expires_in: timedelta = timedelta(hours=4)) -> Session:
    return Session(
        id="sess-abc",
        user_id=1,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + expires_in,
    )


def _install_db_mock(session: Session | None, user: User | None) -> AsyncMock:
    """Override get_db_session to return a mock that yields a `session` and a `user`."""
    session_result = MagicMock()
    session_result.scalar_one_or_none = MagicMock(return_value=session)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=session_result)
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()

    async def _override():
        yield db

    app.dependency_overrides[get_db_session] = _override
    return db


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_me_returns_401_without_cookie() -> None:
    _install_db_mock(session=None, user=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_me_returns_401_when_session_unknown() -> None:
    _install_db_mock(session=None, user=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/auth/me", cookies={"netforge_session": "bad-cookie"}
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user_info_with_valid_session() -> None:
    _install_db_mock(session=_make_session(), user=_make_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/auth/me", cookies={"netforge_session": "sess-abc"}
        )
    assert r.status_code == 200
    assert r.json() == {
        "id": 1,
        "email": "alice@example.com",
        "display_name": "Alice",
        "role": "admin",
        "provider": "github",
    }


@pytest.mark.asyncio
async def test_logout_clears_session_cookie() -> None:
    _install_db_mock(session=_make_session(), user=_make_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/logout", cookies={"netforge_session": "sess-abc"}
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    set_cookie = r.headers.get("set-cookie", "")
    assert "netforge_session=" in set_cookie
    assert ("Max-Age=0" in set_cookie) or ("expires=" in set_cookie.lower())


@pytest.mark.asyncio
async def test_logout_is_idempotent_without_cookie() -> None:
    _install_db_mock(session=None, user=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
