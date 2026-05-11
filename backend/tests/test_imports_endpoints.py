"""HTTP-level checks on /api/imports and /api/exports.

We verify:
  - imports require admin
  - imports reject unknown entities and oversize uploads
  - dry-run imports return an `applied: false` report without committing
  - exports reject unknown entities (the full streaming path is covered by
    test_crud_auth_guards' auth checks and by the unit tests on csv_export
    once we have a real DB harness)

End-to-end mocking of `db.execute` for both the session lookup AND each
service-level query is brittle; the focused tests above are what matters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import get_session as get_db_session
from app.main import app
from app.models.user import Session, User, UserRole


def _viewer() -> User:
    return User(id=1, provider="github", subject="v", email="v@x", role=UserRole.viewer)


def _admin() -> User:
    return User(id=2, provider="github", subject="a", email="a@x", role=UserRole.admin)


def _session() -> Session:
    return Session(
        id="sess", user_id=1,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )


def _install_db(
    user: User | None,
    *,
    execute_returns: list | None = None,
) -> AsyncMock:
    """Wire a mock DB.

    `execute_returns`: optional list of values to return from successive
    `db.execute(...)` calls. The first call is the session lookup; subsequent
    calls hit whatever the endpoint runs (CSV upsert, export query, ...).
    """
    sess_result = MagicMock()
    sess_result.scalar_one_or_none = MagicMock(return_value=_session() if user else None)

    db = AsyncMock()
    if execute_returns is None:
        db.execute = AsyncMock(return_value=sess_result)
    else:
        db.execute = AsyncMock(side_effect=[sess_result, *execute_returns])
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
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


# --- /api/imports ---------------------------------------------------------- #


@pytest.mark.asyncio
async def test_import_rejects_anon(client: AsyncClient) -> None:
    _install_db(user=None)
    r = await client.post(
        "/api/imports/sites",
        files={"file": ("sites.csv", b"code;name\nX;Y\n", "text/csv")},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_import_rejects_viewer(client: AsyncClient) -> None:
    _install_db(user=_viewer())
    r = await client.post(
        "/api/imports/sites",
        files={"file": ("sites.csv", b"code;name\nX;Y\n", "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_import_unknown_entity_returns_400(client: AsyncClient) -> None:
    _install_db(user=_admin())
    r = await client.post(
        "/api/imports/widgets",
        files={"file": ("x.csv", b"a;b\n1;2\n", "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "UNKNOWN_ENTITY"


@pytest.mark.asyncio
async def test_import_size_cap_rejects_huge_upload(client: AsyncClient) -> None:
    _install_db(user=_admin())
    too_big = b"a;b\n" + (b"1;2\n" * 3_000_000)  # ~12 MB
    r = await client.post(
        "/api/imports/sites",
        files={"file": ("big.csv", too_big, "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "CSV_TOO_LARGE"


@pytest.mark.asyncio
async def test_import_admin_dry_run_returns_report(client: AsyncClient) -> None:
    # 1st execute: session lookup (handled by _install_db).
    # 2nd execute: csv_import upsert check — return None so the row is treated
    # as a new insert. The driver will then call db.flush() (mocked) and
    # db.rollback() (mocked) because dry_run=True.
    upsert_result = MagicMock()
    upsert_result.scalar_one_or_none = MagicMock(return_value=None)
    _install_db(user=_admin(), execute_returns=[upsert_result])

    r = await client.post(
        "/api/imports/sites",
        files={"file": ("sites.csv", "﻿code;name\nHQ;Headquarters\n".encode("utf-8"), "text/csv")},
        data={"dry_run": "true"},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parsed_rows"] == 1
    assert body["ok_rows"] == 1
    assert body["applied"] is False  # dry-run always rolls back
    assert body["error_rows"] == []


# --- /api/exports ---------------------------------------------------------- #


@pytest.mark.asyncio
async def test_export_unknown_entity_returns_400(client: AsyncClient) -> None:
    _install_db(user=_viewer())
    r = await client.get(
        "/api/exports/frobnicators", cookies={"netforge_session": "sess"}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "UNKNOWN_ENTITY"
