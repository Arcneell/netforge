"""Verify the HTTP middleware in main.py populates the audit ContextVars
so the SQLAlchemy listeners can read request IP + user-agent.

We don't exercise the listeners themselves here (that needs a real DB —
see services/audit.py docstring); we just probe the ContextVars from an
endpoint, which proves the wiring.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.audit import current_request_ip_var, current_request_ua_var

# Mount a probe endpoint at import time. FastAPI keeps the router list, but
# adding once and idempotency-checking guards against double-registration
# when the test module is collected with --reload-like behaviour.
_PROBE_PATH = "/__test_audit_probe__"
_probe = APIRouter()


@_probe.get(_PROBE_PATH)
async def _probe_endpoint() -> dict:
    return {
        "ip": current_request_ip_var.get(),
        "ua": current_request_ua_var.get(),
    }


if not any(getattr(r, "path", "") == _PROBE_PATH for r in app.routes):
    app.include_router(_probe)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, client=("203.0.113.42", 51234))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_middleware_captures_client_host_and_user_agent(
    client: AsyncClient,
) -> None:
    r = await client.get(_PROBE_PATH, headers={"user-agent": "TestAgent/1.0"})
    assert r.status_code == 200
    body = r.json()
    assert body["ip"] == "203.0.113.42"
    assert body["ua"] == "TestAgent/1.0"


@pytest.mark.asyncio
async def test_middleware_trusts_x_real_ip_not_x_forwarded_for(
    client: AsyncClient,
) -> None:
    """Behind nginx (which sets X-Real-IP unconditionally), the audit log
    must record the value nginx vouched for — not whatever the client
    placed in the X-Forwarded-For chain. XFF's first entry is fully
    attacker-controlled with our `$proxy_add_x_forwarded_for` config."""
    r = await client.get(
        _PROBE_PATH,
        headers={
            "x-real-ip": "198.51.100.7",
            # A malicious client trying to spoof a different identity in XFF.
            "x-forwarded-for": "1.2.3.4, 10.0.0.1",
            "user-agent": "TestAgent/1.0",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ip"] == "198.51.100.7"


@pytest.mark.asyncio
async def test_middleware_ignores_x_forwarded_for_without_x_real_ip(
    client: AsyncClient,
) -> None:
    """No X-Real-IP → fall back to the TCP peer, never trust XFF alone."""
    r = await client.get(
        _PROBE_PATH,
        headers={"x-forwarded-for": "1.2.3.4", "user-agent": "TestAgent/1.0"},
    )
    assert r.status_code == 200
    # The transport is configured with client=(203.0.113.42, 51234)
    assert r.json()["ip"] == "203.0.113.42"


@pytest.mark.asyncio
async def test_middleware_captures_whatever_user_agent_the_client_sends(
    client: AsyncClient,
) -> None:
    # We don't override the UA; httpx sends its own default. The middleware
    # has no business filtering it — whatever the client sends is what the
    # audit log should record.
    r = await client.get(_PROBE_PATH)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["ua"], str)
    assert body["ua"]  # non-empty
