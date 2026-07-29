"""Tests for the shared rate-limit counter store.

The store is the piece both limiters delegate to. Here we pin its contract
against a fake engine that emulates the `ON CONFLICT DO UPDATE` counter:
the SQL shape (which is what makes concurrent increments safe), the
allow/reject boundary, the "a rejected call does not consume" rule, the
purge, and the process-local fallback window.

The real thing runs against PostgreSQL in
`tests/integration/test_rate_limit_shared_pg.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.services import rate_limit_store as store
from app.services.rate_limit_store import (
    SCOPE_AI_USER,
    SCOPE_WRITE_IP,
    CircuitBreaker,
    InProcessWindows,
    maybe_purge_expired,
    purge_expired,
    reset_purge_clock,
    seconds_until_next_bucket,
    try_consume,
)


class _Result:
    def __init__(self, row: tuple[int] | None, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    def first(self) -> tuple[int] | None:
        return self._row


class _Conn:
    def __init__(self, engine: FakeEngine) -> None:
        self._engine = engine

    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def execution_options(self, **kwargs: object) -> _Conn:
        self._engine.isolation_levels.append(kwargs.get("isolation_level"))
        return self

    async def execute(self, stmt: object) -> _Result:
        return self._engine.handle(stmt)


class FakeEngine:
    """Emulates the counter table well enough to exercise `try_consume`.

    Deliberately mirrors the semantics of the real statement rather than
    the storage: increment on conflict, refuse to increment past `limit`,
    return nothing when refused.
    """

    def __init__(self, *, limit: int, fail: bool = False) -> None:
        self.limit = limit
        self.fail = fail
        self.counts: dict[tuple[str, str], int] = {}
        self.sql: list[str] = []
        self.isolation_levels: list[object] = []
        self.deletes = 0
        self.connects = 0

    def connect(self) -> _Conn:
        self.connects += 1
        return _Conn(self)

    def handle(self, stmt: object) -> _Result:
        if self.fail:
            raise RuntimeError("connection refused")
        compiled = stmt.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
        sql = str(compiled)
        self.sql.append(sql)
        if sql.lstrip().upper().startswith("DELETE"):
            self.deletes += 1
            return _Result(None, rowcount=3)
        params = compiled.params
        key = (params["scope"], params["bucket_key"])
        current = self.counts.get(key, 0)
        if current >= self.limit:
            return _Result(None)
        self.counts[key] = current + 1
        return _Result((current + 1,))


# --- SQL shape -------------------------------------------------------------


async def test_consume_uses_a_single_atomic_upsert() -> None:
    """No read-modify-write: one statement that increments server-side.

    This is the property that makes two workers incrementing the same key
    concurrently safe, so it is worth asserting on the generated SQL.
    """
    engine = FakeEngine(limit=5)
    await try_consume(engine, scope=SCOPE_WRITE_IP, key="10.0.0.1", limit=5, window_seconds=60)

    assert len(engine.sql) == 1
    sql = " ".join(engine.sql[0].split())
    assert "INSERT INTO rate_limit_counters" in sql
    assert "ON CONFLICT (scope, bucket_key, window_start) DO UPDATE" in sql
    # The increment is computed by Postgres from the stored value...
    assert "SET hits = (rate_limit_counters.hits + " in sql
    # ...and the cap is enforced by the DO UPDATE's WHERE, so a rejected
    # call writes nothing and RETURNING yields no row.
    assert "WHERE rate_limit_counters.hits <" in sql
    assert "RETURNING rate_limit_counters.hits" in sql
    # Bucket boundary comes from the server clock, not the worker's.
    assert "now()" in sql


async def test_consume_runs_outside_a_transaction() -> None:
    """AUTOCOMMIT: one round trip, and the hit survives a rolled-back request."""
    engine = FakeEngine(limit=5)
    await try_consume(engine, scope=SCOPE_WRITE_IP, key="10.0.0.1", limit=5, window_seconds=60)
    assert engine.isolation_levels == ["AUTOCOMMIT"]


# --- Allow / reject boundary ----------------------------------------------


async def test_allows_exactly_limit_calls_then_rejects() -> None:
    engine = FakeEngine(limit=3)
    for expected in (1, 2, 3):
        decision = await try_consume(
            engine, scope=SCOPE_WRITE_IP, key="k", limit=3, window_seconds=60
        )
        assert decision.allowed is True
        assert decision.hits == expected

    blocked = await try_consume(engine, scope=SCOPE_WRITE_IP, key="k", limit=3, window_seconds=60)
    assert blocked.allowed is False
    assert blocked.retry_after_seconds >= 1


async def test_rejected_call_does_not_consume_budget() -> None:
    """Same semantics as the in-memory window it replaces: being refused
    must not push the recovery further out."""
    engine = FakeEngine(limit=2)
    await try_consume(engine, scope=SCOPE_WRITE_IP, key="k", limit=2, window_seconds=60)
    await try_consume(engine, scope=SCOPE_WRITE_IP, key="k", limit=2, window_seconds=60)
    for _ in range(5):
        assert not (
            await try_consume(engine, scope=SCOPE_WRITE_IP, key="k", limit=2, window_seconds=60)
        ).allowed
    assert engine.counts[(SCOPE_WRITE_IP, "k")] == 2


async def test_scopes_and_keys_are_isolated() -> None:
    engine = FakeEngine(limit=1)
    a = await try_consume(engine, scope=SCOPE_WRITE_IP, key="1", limit=1, window_seconds=60)
    b = await try_consume(engine, scope=SCOPE_WRITE_IP, key="2", limit=1, window_seconds=60)
    c = await try_consume(engine, scope=SCOPE_AI_USER, key="1", limit=1, window_seconds=60)
    assert (a.allowed, b.allowed, c.allowed) == (True, True, True)


async def test_non_positive_limit_rejects_without_touching_the_db() -> None:
    engine = FakeEngine(limit=10)
    decision = await try_consume(engine, scope=SCOPE_WRITE_IP, key="k", limit=0, window_seconds=60)
    assert decision.allowed is False
    assert engine.sql == []


async def test_db_errors_propagate_to_the_caller() -> None:
    """The store has no opinion on degradation — the two limiters choose
    fail-open / fail-closed for themselves."""
    engine = FakeEngine(limit=5, fail=True)
    with pytest.raises(RuntimeError):
        await try_consume(engine, scope=SCOPE_WRITE_IP, key="k", limit=5, window_seconds=60)


# --- Purge -----------------------------------------------------------------


async def test_purge_deletes_expired_rows() -> None:
    engine = FakeEngine(limit=5)
    deleted = await purge_expired(engine)
    assert deleted == 3
    assert engine.deletes == 1
    sql = " ".join(engine.sql[0].split())
    assert "DELETE FROM rate_limit_counters WHERE rate_limit_counters.expires_at <= now()" in sql


async def test_maybe_purge_is_throttled_and_never_raises() -> None:
    reset_purge_clock()
    engine = FakeEngine(limit=5)
    await maybe_purge_expired(engine)
    await maybe_purge_expired(engine)
    await maybe_purge_expired(engine)
    assert engine.deletes == 1  # only the first sweep in the interval runs

    reset_purge_clock()
    broken = FakeEngine(limit=5, fail=True)
    await maybe_purge_expired(broken)  # housekeeping must never fail a request
    reset_purge_clock()


def test_purge_interval_is_conservative() -> None:
    assert store.PURGE_INTERVAL_SECONDS >= 60


# --- Retry-After -----------------------------------------------------------


@pytest.mark.parametrize("window", [1, 10, 60, 3600])
def test_retry_after_is_within_the_window_and_never_zero(window: int) -> None:
    value = seconds_until_next_bucket(window)
    assert 1 <= value <= window


# --- Circuit breaker -------------------------------------------------------


def test_breaker_opens_on_failure_and_closes_after_cooldown() -> None:
    breaker = CircuitBreaker(cooldown_seconds=0.0)
    assert breaker.is_open() is False
    breaker.record_failure()
    # A zero cooldown means the very next probe is allowed through again.
    assert breaker.is_open() is False

    breaker = CircuitBreaker(cooldown_seconds=60.0)
    breaker.record_failure()
    assert breaker.is_open() is True
    breaker.record_success()
    assert breaker.is_open() is False


# --- In-process fallback window -------------------------------------------


def test_in_process_window_matches_the_legacy_semantics() -> None:
    windows = InProcessWindows()
    for _ in range(3):
        assert windows.consume("k", limit=3, window_seconds=60).allowed is True
    blocked = windows.consume("k", limit=3, window_seconds=60)
    assert blocked.allowed is False
    assert 1 <= blocked.retry_after_seconds <= 60
    # Another key keeps its own budget.
    assert windows.consume("other", limit=3, window_seconds=60).allowed is True


def test_in_process_window_gc_drops_idle_keys() -> None:
    """The sweep must not leak a deque per key that ever hit the limiter."""
    windows = InProcessWindows(gc_every=2)
    windows.consume("stale", limit=10, window_seconds=60)
    # Age the recorded hit past the window without sleeping in the test.
    windows._hits["stale"][0] -= 3600
    windows.consume("fresh", limit=10, window_seconds=60)  # 2nd consume → sweep
    assert "stale" not in windows._hits
    assert "fresh" in windows._hits
