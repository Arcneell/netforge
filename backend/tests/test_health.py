"""Smoke tests for the healthcheck.

No real DB required: the `get_session` dependency is overridden with a mock
session that simulates the query. For a real integration test against a live
database see tests/integration/ (phase 3+).
"""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import app


@pytest.mark.asyncio
async def test_health_ok_with_db_up() -> None:
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=None)

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/health")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert isinstance(body["uptime_s"], int)


@pytest.mark.asyncio
async def test_health_db_down_returns_200_with_db_down() -> None:
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=RuntimeError("connection refused"))

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/health")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["db"] == "down"
