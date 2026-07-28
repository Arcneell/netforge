"""Tests for session storage — hashed-at-rest ids + expired-row purge.

The DB stores sha256(cookie) as the primary key (same rule as API tokens),
so a leaked dump can't be replayed as a login. These tests pin the digest
round-trip on mocked sessions; the full HTTP flow stays covered by
tests/test_auth_endpoints.py.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Delete
from sqlalchemy.sql.selectable import Select

from app.auth.sessions import (
    create_session,
    delete_session,
    get_active_session,
    hash_session_id,
)
from app.config import Settings
from app.models.user import User, UserRole


def _settings() -> Settings:
    return Settings(session_max_age_seconds=3600)


def _user() -> User:
    return User(
        id=1,
        provider="github",
        subject="42",
        email="alice@example.com",
        role=UserRole.admin,
    )


def _request() -> MagicMock:
    request = MagicMock()
    request.client = None  # client_ip() then resolves to None — fine here
    request.headers = {"user-agent": "pytest"}
    return request


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


def test_hash_session_id_is_sha256_hex() -> None:
    digest = hash_session_id("tok-123")
    assert digest == hashlib.sha256(b"tok-123").hexdigest()
    assert len(digest) == 64  # fits the String(64) PK column


@pytest.mark.asyncio
async def test_create_session_stores_digest_and_returns_plaintext_once() -> None:
    db = _db()
    sess, token = await create_session(db, _user(), _request(), _settings())

    # The cookie value (token) is never what lands in the table.
    assert token != sess.id
    assert sess.id == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert len(sess.id) == 64
    db.add.assert_called_once_with(sess)
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_session_purges_expired_rows_opportunistically() -> None:
    """Nothing else deletes expired sessions — the login-time sweep is the
    growth bound for the table."""
    db = _db()
    await create_session(db, _user(), _request(), _settings())

    deletes = [c.args[0] for c in db.execute.await_args_list if isinstance(c.args[0], Delete)]
    assert len(deletes) == 1
    compiled = str(deletes[0].compile())
    assert "expires_at" in compiled


@pytest.mark.asyncio
async def test_get_active_session_looks_up_by_digest() -> None:
    db = _db()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=result)

    await get_active_session(db, "raw-cookie-token")

    stmt = db.execute.await_args.args[0]
    assert isinstance(stmt, Select)
    params = stmt.compile().params
    assert hash_session_id("raw-cookie-token") in params.values()
    # The raw cookie value must never reach the SQL layer.
    assert "raw-cookie-token" not in params.values()


@pytest.mark.asyncio
async def test_delete_session_deletes_by_digest() -> None:
    db = _db()

    await delete_session(db, "raw-cookie-token")

    stmt = db.execute.await_args.args[0]
    assert isinstance(stmt, Delete)
    params = stmt.compile().params
    assert hash_session_id("raw-cookie-token") in params.values()
    assert "raw-cookie-token" not in params.values()
    db.commit.assert_awaited()
