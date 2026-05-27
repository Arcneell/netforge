"""Tests for the JIT user upsert service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.base import UserInfo
from app.config import Settings
from app.models.user import User, UserRole
from app.services.users import upsert_user_from_provider


def _mock_db(existing_user: User | None, user_count: int = 0) -> AsyncMock:
    """Build an AsyncSession mock that returns the desired user-or-None
    on the first select and `user_count` on every subsequent count
    SELECT (the upsert path may call `_user_count` once or twice
    depending on which branch it lands in — bootstrap-match returns
    early; cold-start counts then re-counts after the advisory lock)."""
    user_result = MagicMock()
    user_result.scalar_one_or_none = MagicMock(return_value=existing_user)

    def _new_count_result() -> MagicMock:
        r = MagicMock()
        r.scalar = MagicMock(return_value=user_count)
        return r

    db = AsyncMock()
    call_idx = {"n": 0}

    async def _execute(*_a, **_kw) -> MagicMock:
        idx = call_idx["n"]
        call_idx["n"] += 1
        if idx == 0:
            return user_result
        return _new_count_result()

    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def _refresh(obj):
        # Simulate the DB assigning an id.
        if getattr(obj, "id", None) is None:
            obj.id = 1

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


@pytest.mark.asyncio
async def test_first_user_is_promoted_to_admin() -> None:
    db = _mock_db(existing_user=None, user_count=0)
    info = UserInfo(subject="42", email="alice@example.com", display_name="Alice")
    settings = Settings(bootstrap_admin_email="")

    user = await upsert_user_from_provider(db, "github", info, settings)

    assert user.role == UserRole.admin
    assert user.provider == "github"
    assert user.subject == "42"
    assert user.email == "alice@example.com"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_bootstrap_email_match_promotes_to_admin() -> None:
    db = _mock_db(existing_user=None, user_count=5)
    info = UserInfo(subject="99", email="ADMIN@example.com", display_name="Bob")
    settings = Settings(bootstrap_admin_email="admin@example.com")

    user = await upsert_user_from_provider(db, "github", info, settings)

    assert user.role == UserRole.admin


@pytest.mark.asyncio
async def test_regular_user_when_db_already_has_users() -> None:
    db = _mock_db(existing_user=None, user_count=3)
    info = UserInfo(subject="7", email="other@example.com", display_name="Other")
    settings = Settings(bootstrap_admin_email="admin@example.com")

    user = await upsert_user_from_provider(db, "github", info, settings)

    assert user.role == UserRole.viewer


@pytest.mark.asyncio
async def test_existing_user_gets_email_and_name_refreshed() -> None:
    existing = User(
        id=1,
        provider="github",
        subject="42",
        email="old@example.com",
        display_name="Old Name",
        role=UserRole.admin,
    )
    db = _mock_db(existing_user=existing)
    info = UserInfo(subject="42", email="new@example.com", display_name="New Name")
    settings = Settings()

    user = await upsert_user_from_provider(db, "github", info, settings)

    assert user is existing
    assert user.email == "new@example.com"
    assert user.display_name == "New Name"
    assert user.role == UserRole.admin  # unchanged
    db.add.assert_not_called()
