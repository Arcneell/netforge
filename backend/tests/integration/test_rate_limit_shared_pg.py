"""Rate-limit counters against a real PostgreSQL.

What the unit suite structurally cannot cover:

- Two *actually distinct* connections — the stand-in for two uvicorn
  workers or two replicas — sharing one budget. This is the entire point
  of migration 0019: before it, each process counted in its own `deque`
  and the effective cap was (processes x limit).
- That the `INSERT ... ON CONFLICT DO UPDATE ... WHERE` really is atomic
  under concurrency, i.e. that 40 simultaneous hits produce the numbers 1
  to 40 exactly once each with nothing lost to a read-modify-write race.
- That the bucket boundary computed server-side
  (`to_timestamp(floor(extract(epoch from now()) / w) * w)`) type-checks in
  Postgres and lands both workers on the same `window_start`.
- The purge range delete.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.services.rate_limit_store import (
    SCOPE_AI_USER,
    SCOPE_WRITE_IP,
    purge_expired,
    try_consume,
)

from .conftest import INTEGRATION_DB_URL_VAR, integration_db_url

if not integration_db_url():
    pytest.skip(
        f"{INTEGRATION_DB_URL_VAR} is not set — skipping Postgres integration tests",
        allow_module_level=True,
    )


@pytest.fixture
async def workers(migrated_database: str) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """Two independent engines on the same database.

    Separate engines, separate pools, separate connections: as close to two
    processes as a single test can get without forking. NullPool because
    asyncpg connections are bound to the event loop and pytest-asyncio
    gives each test its own.
    """
    a = create_async_engine(migrated_database, poolclass=NullPool)
    b = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        async with a.begin() as conn:
            await conn.execute(text("DELETE FROM rate_limit_counters"))
        yield a, b
    finally:
        await a.dispose()
        await b.dispose()


async def _hits(engine: AsyncEngine, scope: str, key: str) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT COALESCE(SUM(hits), 0) FROM rate_limit_counters "
                "WHERE scope = :scope AND bucket_key = :key"
            ),
            {"scope": scope, "key": key},
        )
        return int(result.scalar_one())


async def _sleep_until_next_second_boundary(engine: AsyncEngine) -> None:
    """Block until the *server* clock crosses the next whole epoch second.

    Bucket boundaries come from `now()` inside Postgres, so aligning on the
    client clock would be wrong by whatever skew exists between the two.
    Asking the server for the fraction of the current second it is in makes
    the alignment exact no matter where the database runs.
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 - (extract(epoch from now()) - floor(extract(epoch from now())))")
        )
        await asyncio.sleep(float(result.scalar_one()))


# --- The headline case -----------------------------------------------------


async def test_two_workers_share_one_budget(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """Alternating writes across two connections must trip at the configured
    limit, not at twice it."""
    a, b = workers
    limit = 5
    verdicts = []
    for i in range(8):
        engine = a if i % 2 == 0 else b
        decision = await try_consume(
            engine, scope=SCOPE_WRITE_IP, key="10.1.2.3", limit=limit, window_seconds=60
        )
        verdicts.append(decision.allowed)

    assert verdicts == [True] * limit + [False] * 3
    assert await _hits(a, SCOPE_WRITE_IP, "10.1.2.3") == limit


async def test_both_workers_land_in_the_same_bucket(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """The bucket boundary comes from the server clock, so two workers with
    slightly skewed local clocks still increment the same row."""
    a, b = workers
    await try_consume(a, scope=SCOPE_WRITE_IP, key="same", limit=10, window_seconds=60)
    await try_consume(b, scope=SCOPE_WRITE_IP, key="same", limit=10, window_seconds=60)

    async with a.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT window_start, hits FROM rate_limit_counters "
                    "WHERE scope = :scope AND bucket_key = 'same'"
                ),
                {"scope": SCOPE_WRITE_IP},
            )
        ).all()
    assert len(rows) == 1  # one bucket, not one per worker
    assert rows[0].hits == 2


async def test_rejected_calls_do_not_consume_budget(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    a, b = workers
    for _ in range(2):
        await try_consume(a, scope=SCOPE_WRITE_IP, key="k", limit=2, window_seconds=60)
    for _ in range(5):
        decision = await try_consume(
            b, scope=SCOPE_WRITE_IP, key="k", limit=2, window_seconds=60
        )
        assert decision.allowed is False
    assert await _hits(a, SCOPE_WRITE_IP, "k") == 2


async def test_scopes_and_keys_do_not_collide(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    a, _b = workers
    for scope, key in ((SCOPE_WRITE_IP, "7"), (SCOPE_AI_USER, "7"), (SCOPE_WRITE_IP, "8")):
        assert (
            await try_consume(a, scope=scope, key=key, limit=1, window_seconds=60)
        ).allowed is True
    assert await _hits(a, SCOPE_WRITE_IP, "7") == 1
    assert await _hits(a, SCOPE_AI_USER, "7") == 1


# --- Concurrency -----------------------------------------------------------


async def test_concurrent_increments_never_lose_a_count(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """40 simultaneous hits on the same key, split across two engines.

    A read-modify-write implementation loses updates here (two readers see
    the same value and both write value+1). The single-statement UPSERT
    cannot: every caller gets a distinct number and the row ends at 40.
    """
    a, b = workers
    total = 40

    async def hit(i: int) -> int:
        engine = a if i % 2 == 0 else b
        decision = await try_consume(
            engine, scope=SCOPE_WRITE_IP, key="race", limit=1000, window_seconds=60
        )
        assert decision.allowed is True
        return decision.hits

    seen = await asyncio.gather(*(hit(i) for i in range(total)))
    assert sorted(seen) == list(range(1, total + 1))
    assert await _hits(a, SCOPE_WRITE_IP, "race") == total


async def test_concurrent_hits_cannot_overshoot_the_limit(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """The cap holds under a concurrent burst — exactly `limit` winners."""
    a, b = workers
    limit = 6

    async def hit(i: int) -> bool:
        engine = a if i % 2 == 0 else b
        decision = await try_consume(
            engine, scope=SCOPE_AI_USER, key="burst", limit=limit, window_seconds=60
        )
        return decision.allowed

    verdicts = await asyncio.gather(*(hit(i) for i in range(30)))
    assert sum(verdicts) == limit
    assert await _hits(a, SCOPE_AI_USER, "burst") == limit


# --- Windowing -------------------------------------------------------------


async def test_budget_recovers_in_the_next_bucket(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """Tumbling bucket: once the window rolls over, a fresh row is created
    and the budget is back. Uses a 1s window so the test is quick.

    Buckets are aligned on absolute epoch seconds, so the two calls that
    must share a bucket have to start just after a boundary — otherwise a
    second can tick between them, they land in different buckets, and the
    second call is legitimately allowed. Waiting for the next boundary
    first buys them very nearly the full window of headroom.
    """
    a, b = workers
    await _sleep_until_next_second_boundary(a)

    assert (
        await try_consume(a, scope=SCOPE_WRITE_IP, key="roll", limit=1, window_seconds=1)
    ).allowed is True
    assert (
        await try_consume(b, scope=SCOPE_WRITE_IP, key="roll", limit=1, window_seconds=1)
    ).allowed is False

    await asyncio.sleep(1.2)
    assert (
        await try_consume(b, scope=SCOPE_WRITE_IP, key="roll", limit=1, window_seconds=1)
    ).allowed is True


# --- Purge -----------------------------------------------------------------


async def test_purge_removes_only_expired_buckets(
    workers: tuple[AsyncEngine, AsyncEngine],
) -> None:
    a, _b = workers
    # A live bucket, written the normal way.
    await try_consume(a, scope=SCOPE_WRITE_IP, key="live", limit=5, window_seconds=3600)
    # And a bucket whose window closed an hour ago.
    async with a.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO rate_limit_counters "
                "(scope, bucket_key, window_start, hits, expires_at) VALUES "
                "(:scope, 'stale', now() - interval '2 hours', 9, now() - interval '1 hour')"
            ),
            {"scope": SCOPE_WRITE_IP},
        )

    deleted = await purge_expired(a)

    assert deleted == 1
    assert await _hits(a, SCOPE_WRITE_IP, "stale") == 0
    assert await _hits(a, SCOPE_WRITE_IP, "live") == 1


# --- The AI limiter on top of the same store -------------------------------


async def test_ai_quota_is_shared_across_workers(
    workers: tuple[AsyncEngine, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`consume_ai_quota` is the async API the AI router should adopt; its
    budget must survive a process boundary the same way."""
    from app.services.ai import rate_limit as rl

    a, b = workers
    monkeypatch.setattr(
        rl,
        "get_settings",
        lambda: SimpleNamespace(
            rate_limit_store="database",
            ai_rate_limit_calls=2,
            ai_rate_window_seconds=3600,
            database_url="unused",
        ),
    )

    await rl.consume_ai_quota(1234, engine=a)
    await rl.consume_ai_quota(1234, engine=b)  # "other worker", same budget
    with pytest.raises(rl.AIRateLimitExceeded) as exc:
        await rl.consume_ai_quota(1234, engine=a)
    assert exc.value.retry_after_seconds >= 1
    assert await _hits(a, SCOPE_AI_USER, "1234") == 2
