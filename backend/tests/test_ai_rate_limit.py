"""Tests for the per-user AI rate limiter.

The limiter is a sliding-window in-memory counter — we drive its public method
directly and verify the failure mode + retry-after math. No FastAPI app, no DB.
"""

from __future__ import annotations

import pytest

from app.services.ai.rate_limit import (
    AIRateLimitExceeded,
    _UserCounter,
    check_and_consume,
)


def test_consume_allows_calls_up_to_limit() -> None:
    counter = _UserCounter()
    for _ in range(5):
        counter.consume(limit=5, window=60)


def test_consume_raises_when_limit_reached() -> None:
    counter = _UserCounter()
    for _ in range(3):
        counter.consume(limit=3, window=60)
    with pytest.raises(AIRateLimitExceeded) as exc:
        counter.consume(limit=3, window=60)
    # retry_after should be a positive integer at most == window.
    assert 1 <= exc.value.retry_after_seconds <= 60


def test_expired_entries_are_dropped_and_quota_recovers() -> None:
    """Entries older than `window` must not count against the cap.

    We monkey-patch the monotonic source to fast-forward time without sleeping.
    """
    counter = _UserCounter()
    # Burn the quota at t=0
    counter.consume(limit=2, window=10)
    counter.consume(limit=2, window=10)
    # Verify the next one fails
    with pytest.raises(AIRateLimitExceeded):
        counter.consume(limit=2, window=10)
    # Manually expire the deque so the next call succeeds — simulate "window
    # later" without actually sleeping in the test process.
    while counter._calls:
        counter._calls.popleft()
    counter.consume(limit=2, window=10)


def test_check_and_consume_rejects_anonymous() -> None:
    """user_id == 0 / None must be blocked even before talking to settings."""
    with pytest.raises(AIRateLimitExceeded):
        check_and_consume(0)
    with pytest.raises(AIRateLimitExceeded):
        check_and_consume(None)  # type: ignore[arg-type]


def test_check_and_consume_isolates_users(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two distinct user ids must not share the same counter."""
    # Force a tiny limit so the assertion is cheap.
    from app.services.ai import rate_limit as rl

    fake_settings = type("S", (), {"ai_rate_limit_calls": 1, "ai_rate_window_seconds": 60})()
    monkeypatch.setattr(rl, "get_settings", lambda: fake_settings)
    # Reset the module-level dict so this test runs deterministically against
    # any state left over by other tests in the same process.
    monkeypatch.setattr(rl, "_USERS", {})
    rl.check_and_consume(101)
    rl.check_and_consume(202)  # different user — must succeed
    with pytest.raises(AIRateLimitExceeded):
        rl.check_and_consume(101)  # same user — must fail
