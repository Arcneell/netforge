"""Tests for the write-rate-limit middleware.

We build a tiny FastAPI app with a single POST/GET handler and the middleware
wired with very small limits — no need to spin up the full netforge app to
test the middleware contract.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware.rate_limit import WriteRateLimitMiddleware


def _make_app(max_per_window: int = 3, window_seconds: int = 60) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        WriteRateLimitMiddleware,
        max_per_window=max_per_window,
        window_seconds=window_seconds,
    )

    @app.get("/things")
    async def list_things() -> dict[str, str]:
        return {"ok": "read"}

    @app.post("/things")
    async def create_thing() -> dict[str, str]:
        return {"ok": "write"}

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/auth/login")
    async def login() -> dict[str, str]:
        return {"ok": "login"}

    return app


@pytest.mark.asyncio
async def test_write_methods_blocked_after_quota_exhausted() -> None:
    app = _make_app(max_per_window=3, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            r = await client.post("/things")
            assert r.status_code == 200
        blocked = await client.post("/things")
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_reads_are_not_rate_limited() -> None:
    # 10 reads with a max=1 limit must all pass — only writes are throttled.
    app = _make_app(max_per_window=1, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(10):
            r = await client.get("/things")
            assert r.status_code == 200


@pytest.mark.asyncio
async def test_health_and_auth_endpoints_are_exempt() -> None:
    # max=1 — health probes and the login redirect must never trip the limiter.
    app = _make_app(max_per_window=1, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(5):
            assert (await client.get("/api/health")).status_code == 200
            assert (await client.post("/api/auth/login")).status_code == 200


@pytest.mark.asyncio
async def test_per_ip_isolation_via_real_ip_header() -> None:
    # Two distinct X-Real-IP values share no bucket — one IP exhausting its
    # quota mustn't block another. X-Real-IP is nginx-set and trusted.
    app = _make_app(max_per_window=1, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        a1 = await client.post("/things", headers={"x-real-ip": "10.0.0.1"})
        a2 = await client.post("/things", headers={"x-real-ip": "10.0.0.1"})
        b1 = await client.post("/things", headers={"x-real-ip": "10.0.0.2"})
    assert a1.status_code == 200
    assert a2.status_code == 429
    assert b1.status_code == 200


@pytest.mark.asyncio
async def test_x_forwarded_for_is_not_trusted_for_key() -> None:
    # Regression for the Codex P1 finding on PR #6: a client that rotates
    # X-Forwarded-For per request must NOT get a fresh bucket each time.
    # Without X-Real-IP, every request hashes to the same TCP peer key.
    app = _make_app(max_per_window=2, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post("/things", headers={"x-forwarded-for": "1.1.1.1"})
        r2 = await client.post("/things", headers={"x-forwarded-for": "2.2.2.2"})
        r3 = await client.post("/things", headers={"x-forwarded-for": "3.3.3.3"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429  # would be 200 if XFF still keyed the bucket


@pytest.mark.asyncio
async def test_middleware_does_not_buffer_streaming_responses() -> None:
    """Regression: the middleware used to inherit from `BaseHTTPMiddleware`,
    which bridges the response through an anyio memory stream and breaks
    `text/event-stream` streaming (Ask AI rendered the answer all at once
    instead of token-by-token).

    Drive the ASGI app directly and assert that each `http.response.body`
    chunk emitted by the inner app reaches the outer `send` as a distinct
    frame, not coalesced into one big buffer.
    """
    chunks_received: list[bytes] = []

    async def streaming_app(scope, receive, send):
        # Three separate body chunks with `more_body=True` until the last.
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]}
        )
        await send({"type": "http.response.body", "body": b"chunk-1", "more_body": True})
        await send({"type": "http.response.body", "body": b"chunk-2", "more_body": True})
        await send({"type": "http.response.body", "body": b"chunk-3", "more_body": False})

    middleware = WriteRateLimitMiddleware(
        streaming_app, max_per_window=10, window_seconds=60
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body":
            chunks_received.append(message["body"])

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/things",
        "headers": [],
        "client": ("127.0.0.1", 0),
    }
    await middleware(scope, receive, send)
    # If the middleware buffered, we'd see one b"chunk-1chunk-2chunk-3".
    assert chunks_received == [b"chunk-1", b"chunk-2", b"chunk-3"]
