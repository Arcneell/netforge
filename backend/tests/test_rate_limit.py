"""Tests for the write / expensive-export-GET rate-limit middleware.

We build a tiny FastAPI app with a handful of POST/GET handlers and the
middleware wired with very small limits — no need to spin up the full
netforge app to test the middleware contract.

Two wirings are covered:

- `engine=None` — the process-local fallback window (`RATE_LIMIT_STORE=memory`).
  Most of the behavioural contract (which methods/paths are limited, the 429
  shape, per-IP keying, SSE pass-through) is identical in both modes and is
  asserted here because it needs no database.
- `engine=<fake counter>` — the shared DB-backed counter, including the two
  things that only matter there: two "workers" sharing one budget, and the
  fail-open degradation when the counter is unreachable.

The DB path runs against real PostgreSQL in
`tests/integration/test_rate_limit_shared_pg.py`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware.rate_limit import WriteRateLimitMiddleware
from app.services import rate_limit_store as store

from .test_rate_limit_store import FakeEngine


def _make_app(
    max_per_window: int = 3,
    window_seconds: int = 60,
    engine: object | None = None,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        WriteRateLimitMiddleware,
        max_per_window=max_per_window,
        window_seconds=window_seconds,
        engine=engine,
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

    @app.get("/api/exports/devices")
    async def export_devices() -> dict[str, str]:
        return {"ok": "export"}

    @app.get("/api/ai/insights/export.pdf")
    async def export_pdf() -> dict[str, str]:
        return {"ok": "pdf"}

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
async def test_expensive_export_gets_are_rate_limited() -> None:
    # /api/exports/* is a GET but expensive enough to be capped like a write.
    app = _make_app(max_per_window=2, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/exports/devices")).status_code == 200
        assert (await client.get("/api/exports/devices")).status_code == 200
        blocked = await client.get("/api/exports/devices")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_ai_pdf_export_get_is_rate_limited() -> None:
    app = _make_app(max_per_window=1, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/ai/insights/export.pdf")).status_code == 200
        blocked = await client.get("/api/ai/insights/export.pdf")
    assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_export_get_budget_is_independent_from_write_budget() -> None:
    # Same IP, same worker: exhausting the write bucket must not touch the
    # separate export-GET bucket, and vice versa.
    app = _make_app(max_per_window=1, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/things")).status_code == 200
        blocked_write = await client.post("/things")
        assert (await client.get("/api/exports/devices")).status_code == 200
        blocked_export = await client.get("/api/exports/devices")
    assert blocked_write.status_code == 429
    assert blocked_export.status_code == 429


@pytest.mark.asyncio
async def test_ordinary_gets_outside_expensive_prefixes_stay_unthrottled() -> None:
    app = _make_app(max_per_window=1, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(5):
            assert (await client.get("/things")).status_code == 200


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


# --- Shared DB-backed counter ---------------------------------------------


@pytest.mark.asyncio
async def test_two_workers_share_one_budget() -> None:
    """The headline reason the counter moved to Postgres.

    Two middleware instances stand in for two uvicorn workers / replicas.
    With the old per-process deque each would have granted 3 writes (6
    total); against the shared counter the 4th write anywhere is refused.
    """
    store.reset_purge_clock()
    engine = FakeEngine(limit=3)
    worker_a = _make_app(max_per_window=3, window_seconds=60, engine=engine)
    worker_b = _make_app(max_per_window=3, window_seconds=60, engine=engine)

    statuses = []
    async with (
        AsyncClient(transport=ASGITransport(app=worker_a), base_url="http://a") as ca,
        AsyncClient(transport=ASGITransport(app=worker_b), base_url="http://b") as cb,
    ):
        for client in (ca, cb, ca, cb):
            r = await client.post("/things", headers={"x-real-ip": "10.0.0.9"})
            statuses.append(r.status_code)

    assert statuses == [200, 200, 200, 429]


@pytest.mark.asyncio
async def test_db_mode_429_shape_matches_memory_mode() -> None:
    store.reset_purge_clock()
    engine = FakeEngine(limit=1)
    app = _make_app(max_per_window=1, window_seconds=60, engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/things")).status_code == 200
        blocked = await client.post("/things")

    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["details"]["retry_after_seconds"] >= 1
    assert int(blocked.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_reads_and_exempt_paths_never_touch_the_counter() -> None:
    """Perf guard: the DB round trip is only paid by limited write methods."""
    store.reset_purge_clock()
    engine = FakeEngine(limit=1)
    app = _make_app(max_per_window=1, window_seconds=60, engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(5):
            await client.get("/things")
            await client.get("/api/health")
            await client.post("/api/auth/login")
    assert engine.sql == []


@pytest.mark.asyncio
async def test_one_round_trip_per_write() -> None:
    store.reset_purge_clock()
    engine = FakeEngine(limit=10)
    app = _make_app(max_per_window=10, window_seconds=60, engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(3):
            await client.post("/things")
    # 3 counter statements + the single throttled purge sweep.
    assert len(engine.sql) == 4
    assert engine.deletes == 1


@pytest.mark.asyncio
async def test_fails_open_when_the_counter_is_unavailable() -> None:
    """A dead counter must not turn into a total write outage — but the
    process-local fallback still caps a runaway script."""
    store.reset_purge_clock()
    engine = FakeEngine(limit=100, fail=True)
    app = _make_app(max_per_window=2, window_seconds=60, engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/things")
        second = await client.post("/things")
        third = await client.post("/things")

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429  # fallback window, not the DB counter


@pytest.mark.asyncio
async def test_circuit_breaker_stops_hammering_a_dead_counter() -> None:
    """One failure parks the DB path so a Postgres outage doesn't cost every
    write a connection timeout."""
    store.reset_purge_clock()
    engine = FakeEngine(limit=100, fail=True)
    app = _make_app(max_per_window=50, window_seconds=60, engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(10):
            assert (await client.post("/things")).status_code == 200
    assert engine.connects == 1
