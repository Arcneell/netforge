"""Verify that every CRUD endpoint enforces the right auth/role.

We don't exercise the real DB here — only the auth wall. Reads must require
an authenticated user (any role); writes must require admin.
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
    return User(
        id=1, provider="github", subject="v",
        email="v@example.com", display_name="V", role=UserRole.viewer,
    )


def _admin() -> User:
    return User(
        id=2, provider="github", subject="a",
        email="a@example.com", display_name="A", role=UserRole.admin,
    )


def _session() -> Session:
    return Session(
        id="sess",
        user_id=1,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )


def _install_db(user: User | None) -> None:
    """Wire a mock DB that returns a session + the given user."""
    session_result = MagicMock()
    session_result.scalar_one_or_none = MagicMock(return_value=_session() if user else None)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=session_result)
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()

    async def _override() -> AsyncIterator:
        yield db

    app.dependency_overrides[get_db_session] = _override


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# Read endpoints — sample list, every one is identical structurally.
_READ_PATHS = [
    "/api/sites",
    "/api/rooms",
    "/api/vlans",
    "/api/subnets",
    "/api/ips",
    "/api/devices",
    "/api/switches",
    "/api/switches/1/ports",
    "/api/ports/1/vlans",
    "/api/links",
    "/api/audit",
    "/api/search?q=foo",
    "/api/topology",
    "/api/subnets/1/ips",
    "/api/exports/sites",
]

# Write endpoints — minimal payloads sufficient to trip the dependency chain.
_WRITE_CASES = [
    ("POST", "/api/sites", {"code": "X", "name": "X"}),
    ("POST", "/api/rooms", {"site_id": 1, "code": "X"}),
    ("POST", "/api/vlans", {"vlan_id": 100, "name": "X"}),
    ("POST", "/api/subnets", {"cidr": "10.0.99.0/24", "site_id": 1}),
    ("POST", "/api/ips", {"subnet_id": 1, "address": "10.0.99.1", "status": "reserved"}),
    ("POST", "/api/devices", {"name": "X", "type": "server"}),
    ("POST", "/api/switches", {"name": "SW-X", "port_count": 24}),
    ("POST", "/api/links", {"port_a_id": 1, "port_b_id": 2, "link_type": "copper"}),
    (
        "POST",
        "/api/links/by-name",
        {
            "switch_a": "SW-A",
            "port_a": 1,
            "switch_b": "SW-B",
            "port_b": 2,
            "link_type": "copper",
        },
    ),
    ("PUT", "/api/links/1", {"link_type": "fiber"}),
    ("PUT", "/api/ports/1", {"label": "x"}),
    ("POST", "/api/ports/1/vlans", {"vlan_id": 100}),
    ("DELETE", "/api/sites/1", None),
    ("DELETE", "/api/rooms/1", None),
    ("DELETE", "/api/vlans/1", None),
    ("DELETE", "/api/subnets/1", None),
    ("DELETE", "/api/ips/1", None),
    ("DELETE", "/api/devices/1", None),
    ("DELETE", "/api/switches/1", None),
    ("DELETE", "/api/links/1", None),
    ("DELETE", "/api/ports/1/vlans/2", None),
    # next-free is a POST that reads (no body) — viewer can call it; only
    # the anonymous case is rejected. Excluded from the "writes forbidden
    # to viewer" parametrisation below; covered by the dedicated test.
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _READ_PATHS)
async def test_reads_require_authentication(client: AsyncClient, path: str) -> None:
    _install_db(user=None)
    r = await client.get(path)
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", _WRITE_CASES)
async def test_writes_require_authentication(
    client: AsyncClient, method: str, path: str, body: dict | None
) -> None:
    _install_db(user=None)
    r = await client.request(method, path, json=body, cookies={"netforge_session": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", _WRITE_CASES)
async def test_writes_forbidden_for_viewer(
    client: AsyncClient, method: str, path: str, body: dict | None
) -> None:
    _install_db(user=_viewer())
    r = await client.request(method, path, json=body, cookies={"netforge_session": "sess"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_audit_endpoint_forbidden_for_viewer(client: AsyncClient) -> None:
    """Audit log is admin-only even on GET."""
    _install_db(user=_viewer())
    r = await client.get("/api/audit", cookies={"netforge_session": "sess"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_next_free_requires_authentication(client: AsyncClient) -> None:
    """`POST /api/subnets/{id}/next-free` is read-only conceptually,
    so a viewer is allowed but an anonymous request is rejected."""
    _install_db(user=None)
    r = await client.post("/api/subnets/1/next-free")
    assert r.status_code == 401
