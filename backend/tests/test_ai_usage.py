"""Tests for the AI Usage aggregation service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.ai import AIRunKind
from app.services.ai.usage import build_usage_report


def _row(
    *,
    when: datetime,
    kind: AIRunKind,
    provider: str,
    model: str,
    p: int = 100,
    c: int = 200,
    success: bool = True,
    latency: int = 1000,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        created_at=when,
        kind=kind,
        provider=provider,
        model=model,
        prompt_tokens=p,
        completion_tokens=c,
        success=success,
        latency_ms=latency,
    )


def _scalars(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _mock_db(rows: list) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars(rows))
    return db


@pytest.mark.asyncio
async def test_empty_window_returns_zeroed_report() -> None:
    db = _mock_db([])
    report = await build_usage_report(db, days=7)
    assert report.window_days == 7
    assert report.total.calls == 0
    assert report.total.cost_usd == 0.0
    # `by_day` is backfilled with zero-call buckets for every day in the
    # window — that's what lets the sparkline render the dead-flat line
    # instead of skipping days. Today + 7 days back = 8 buckets.
    assert len(report.by_day) == 8
    assert all(b.totals.calls == 0 for b in report.by_day)
    assert report.by_kind == []
    assert report.by_provider == []


@pytest.mark.asyncio
async def test_totals_accumulate_across_rows() -> None:
    now = datetime.now(UTC)
    rows = [
        _row(when=now - timedelta(hours=1), kind=AIRunKind.advisor, provider="anthropic",
             model="claude-sonnet-4-6", p=1_000_000, c=1_000_000, latency=2000),
        _row(when=now - timedelta(hours=2), kind=AIRunKind.nl_query, provider="anthropic",
             model="claude-sonnet-4-6", p=0, c=1_000_000, latency=1000, success=False),
    ]
    report = await build_usage_report(_mock_db(rows), days=7)
    assert report.total.calls == 2
    assert report.total.prompt_tokens == 1_000_000
    assert report.total.completion_tokens == 2_000_000
    assert report.total.success == 1
    assert report.total.failure == 1
    # 1M@3$ + 1M@15$ + 0 + 1M@15$ = $33 — covers in/out asymmetry.
    assert report.total.cost_usd == pytest.approx(33.0)
    assert report.total.avg_latency_ms == 1500


@pytest.mark.asyncio
async def test_by_day_bucket_is_sorted_ascending() -> None:
    """The UI draws a sparkline directly from `by_day` — order matters.
    With zero-day backfill we now also expect a contiguous run between
    `started_at` and today, so we assert the three days with traffic appear
    in ascending order rather than as the entire list."""
    base = datetime(2026, 5, 17, 12, tzinfo=UTC)
    rows = [
        _row(when=base + timedelta(days=2), kind=AIRunKind.advisor, provider="anthropic",
             model="claude-sonnet-4-6"),
        _row(when=base, kind=AIRunKind.advisor, provider="anthropic",
             model="claude-sonnet-4-6"),
        _row(when=base + timedelta(days=1), kind=AIRunKind.advisor, provider="anthropic",
             model="claude-sonnet-4-6"),
    ]
    report = await build_usage_report(_mock_db(rows), days=7)
    busy = {b.key: b.totals.calls for b in report.by_day if b.totals.calls > 0}
    assert busy == {"2026-05-17": 1, "2026-05-18": 1, "2026-05-19": 1}
    # Whole list must still be monotonically ascending on the date key.
    keys = [b.key for b in report.by_day]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_by_kind_and_by_provider_split_correctly() -> None:
    now = datetime.now(UTC)
    rows = [
        _row(when=now, kind=AIRunKind.advisor, provider="anthropic",
             model="claude-sonnet-4-6"),
        _row(when=now, kind=AIRunKind.advisor, provider="openai", model="gpt-4o"),
        _row(when=now, kind=AIRunKind.nl_query, provider="anthropic",
             model="claude-sonnet-4-6"),
    ]
    report = await build_usage_report(_mock_db(rows), days=1)
    kind_keys = {b.key: b.totals.calls for b in report.by_kind}
    assert kind_keys == {"advisor": 2, "nl_query": 1}
    provider_keys = {b.key: b.totals.calls for b in report.by_provider}
    assert provider_keys == {"anthropic": 2, "openai": 1}


@pytest.mark.asyncio
async def test_failed_call_with_zero_tokens_is_still_counted() -> None:
    """A 4xx from the provider stores a row with zero tokens; the dashboard
    must still count it as a failure so the operator can spot incidents."""
    now = datetime.now(UTC)
    rows = [
        _row(when=now, kind=AIRunKind.advisor, provider="anthropic",
             model="claude-sonnet-4-6", p=0, c=0, success=False, latency=500),
    ]
    report = await build_usage_report(_mock_db(rows), days=1)
    assert report.total.calls == 1
    assert report.total.failure == 1
    assert report.total.success == 0
    assert report.total.cost_usd == 0.0
