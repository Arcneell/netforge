"""Tests for the per-user AI rate limiter.

Two things are being pinned here:

- The public contract `app/routers/ai/common.py::enforce_rate_limit`
  depends on — `await consume_ai_quota(user_id)` raising
  `AIRateLimitExceeded` with a usable `retry_after_seconds`.
- The fail-CLOSED degradation policy, which is the opposite of the write
  limiter's. This limiter guards spend: a call we cannot account for is an
  unbounded bill, so an unreachable counter means 429, not "let it through".

The real shared counter runs against PostgreSQL in
`tests/integration/test_rate_limit_shared_pg.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai import rate_limit as rl
from app.services.ai.rate_limit import AIRateLimitExceeded, consume_ai_quota

from .test_rate_limit_store import FakeEngine


def _settings(store: str, *, calls: int = 3, window: int = 3600) -> SimpleNamespace:
    return SimpleNamespace(
        rate_limit_store=store,
        ai_rate_limit_calls=calls,
        ai_rate_window_seconds=window,
        database_url="postgresql+asyncpg://unused/unused",
    )


@pytest.fixture(autouse=True)
def _clean_memory_window() -> None:
    """The fallback window is module-global — don't leak state across tests."""
    rl._MEMORY.clear()


# --- Anonymous guard (unchanged, backend-independent) ----------------------


async def test_consume_rejects_anonymous() -> None:
    """user_id == 0 / None must be blocked before we even read settings."""
    with pytest.raises(AIRateLimitExceeded):
        await consume_ai_quota(0)
    with pytest.raises(AIRateLimitExceeded):
        await consume_ai_quota(None)  # type: ignore[arg-type]


# --- RATE_LIMIT_STORE=memory (single-worker opt-out / unit-suite default) --


async def test_memory_store_allows_up_to_the_limit_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rl, "get_settings", lambda: _settings("memory", calls=3, window=60))
    for _ in range(3):
        await consume_ai_quota(42)
    with pytest.raises(AIRateLimitExceeded) as exc:
        await consume_ai_quota(42)
    assert 1 <= exc.value.retry_after_seconds <= 60


async def test_memory_store_isolates_users(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rl, "get_settings", lambda: _settings("memory", calls=1))
    await consume_ai_quota(101)
    await consume_ai_quota(202)  # different user — must succeed
    with pytest.raises(AIRateLimitExceeded):
        await consume_ai_quota(101)  # same user — must fail


async def test_memory_store_never_touches_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-out path must stay cheap: no engine, no statement."""
    monkeypatch.setattr(rl, "get_settings", lambda: _settings("memory", calls=1))
    monkeypatch.setattr(
        rl, "try_consume", lambda *_a, **_k: pytest.fail("memory mode hit the DB")
    )
    await consume_ai_quota(7)


# --- RATE_LIMIT_STORE=database (default) -----------------------------------


async def test_shared_counter_is_per_user_and_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rl, "get_settings", lambda: _settings("database", calls=2))
    engine = FakeEngine(limit=2)

    await consume_ai_quota(11, engine=engine)
    await consume_ai_quota(11, engine=engine)
    await consume_ai_quota(22, engine=engine)  # other user, own budget
    with pytest.raises(AIRateLimitExceeded) as exc:
        await consume_ai_quota(11, engine=engine)
    assert exc.value.retry_after_seconds >= 1
    assert engine.counts[("ai_user", "11")] == 2


async def test_two_workers_share_one_ai_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug this replaces: N workers used to grant N x the quota, and a
    restart handed everyone a fresh one. Same counter row, one budget."""
    monkeypatch.setattr(rl, "get_settings", lambda: _settings("database", calls=2))
    shared = FakeEngine(limit=2)
    # Distinct engine handles standing in for two processes talking to the
    # same row would be indistinguishable here; what matters is that the
    # state lives in the store, not in either caller.
    await consume_ai_quota(5, engine=shared)
    await consume_ai_quota(5, engine=shared)
    with pytest.raises(AIRateLimitExceeded):
        await consume_ai_quota(5, engine=shared)


async def test_fails_closed_when_the_counter_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spend guard: no counter means no call, not a free call."""
    monkeypatch.setattr(rl, "get_settings", lambda: _settings("database", calls=20))
    broken = FakeEngine(limit=20, fail=True)
    with pytest.raises(AIRateLimitExceeded) as exc:
        await consume_ai_quota(5, engine=broken)
    assert exc.value.retry_after_seconds == rl._FAIL_CLOSED_RETRY_AFTER


async def test_fail_closed_does_not_fall_back_to_a_per_process_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for the obvious "just degrade gracefully" mistake:
    falling back in-process would silently restore the N x quota bug."""
    monkeypatch.setattr(rl, "get_settings", lambda: _settings("database", calls=20))
    broken = FakeEngine(limit=20, fail=True)
    for _ in range(3):
        with pytest.raises(AIRateLimitExceeded):
            await consume_ai_quota(5, engine=broken)
    assert rl._MEMORY._hits == {}
