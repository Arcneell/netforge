"""Tests for the AI scheduler — due-check, webhook diff, payload shape.

The scheduler loop itself is an asyncio task that talks to a real session;
we test the pure helpers + the diff logic with mocked sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.ai import AIRunKind, InsightCategory, InsightSeverity
from app.services.ai import scheduler


def _schedule(
    *,
    enabled: bool = True,
    last_run_at: datetime | None = None,
    interval_minutes: int = 60,
    kind: AIRunKind = AIRunKind.advisor,
    webhook_url: str | None = "https://hook.example/relay",
    threshold: InsightSeverity = InsightSeverity.warning,
    last_run_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        kind=kind,
        enabled=enabled,
        interval_minutes=interval_minutes,
        webhook_url=webhook_url,
        webhook_severity_threshold=threshold,
        last_run_at=last_run_at,
        last_run_id=last_run_id,
    )


def _insight(*, title: str, severity: InsightSeverity, category: InsightCategory) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        description="x",
        recommendation="y",
        severity=severity,
        category=category,
    )


def test_is_due_skips_disabled() -> None:
    s = _schedule(enabled=False)
    assert scheduler.is_due(s, datetime.now(UTC)) is False


def test_is_due_returns_true_when_never_run() -> None:
    s = _schedule(last_run_at=None)
    assert scheduler.is_due(s, datetime.now(UTC)) is True


def test_is_due_respects_interval() -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    just_ran = _schedule(last_run_at=now - timedelta(minutes=30), interval_minutes=60)
    long_ago = _schedule(last_run_at=now - timedelta(minutes=90), interval_minutes=60)
    assert scheduler.is_due(just_ran, now) is False
    assert scheduler.is_due(long_ago, now) is True


def test_payload_shape_includes_new_findings_capped_at_20() -> None:
    """The envelope ships event + run_id + threshold + findings list."""
    rows = [
        _insight(
            title=f"Finding {i}",
            severity=InsightSeverity.critical,
            category=InsightCategory.spof,
        )
        for i in range(25)
    ]
    sched = _schedule(last_run_id=42, threshold=InsightSeverity.warning)
    payload = scheduler._build_webhook_payload(schedule=sched, new_rows=rows)
    assert payload["source"] == "netforge"
    assert payload["event"] == "advisor.new_findings"
    assert payload["run_id"] == 42
    assert payload["threshold"] == "warning"
    assert len(payload["findings"]) == 20  # capped


@pytest.mark.asyncio
async def test_maybe_notify_skips_when_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """An info-only run with a `warning` threshold must not fire."""
    sched = _schedule(threshold=InsightSeverity.warning, last_run_id=10)
    info_rows = [
        _insight(title="Naming", severity=InsightSeverity.info, category=InsightCategory.naming)
    ]
    db = _mock_db_with_query_results({10: info_rows})
    sent: list[tuple[str, dict]] = []

    async def fake_send(url: str, payload: dict) -> None:
        sent.append((url, payload))

    monkeypatch.setattr(scheduler, "_send_webhook", fake_send)
    await scheduler._maybe_notify(
        db, schedule=sched, new_run_id=10, previous_run_id=None
    )
    assert sent == []


@pytest.mark.asyncio
async def test_maybe_notify_fires_only_for_newly_introduced(monkeypatch: pytest.MonkeyPatch) -> None:
    """A finding that was already present in the previous run must NOT
    re-trigger a webhook — only genuinely new findings do."""
    sched = _schedule(threshold=InsightSeverity.warning, last_run_id=10)
    old = _insight(
        title="Subnet 10.0.0.0/24 is 92% full",
        severity=InsightSeverity.warning,
        category=InsightCategory.capacity,
    )
    new = _insight(
        title="Switch SW-CORE-01 is the only path to room R-102",
        severity=InsightSeverity.critical,
        category=InsightCategory.spof,
    )
    # new run has both findings; previous run has only `old`.
    db = _mock_db_with_query_results({10: [old, new], 9: [old]})

    sent: list[tuple[str, dict]] = []

    async def fake_send(url: str, payload: dict) -> None:
        sent.append((url, payload))

    monkeypatch.setattr(scheduler, "_send_webhook", fake_send)
    await scheduler._maybe_notify(db, schedule=sched, new_run_id=10, previous_run_id=9)
    assert len(sent) == 1
    url, payload = sent[0]
    assert url == "https://hook.example/relay"
    titles = [f["title"] for f in payload["findings"]]
    assert titles == [new.title]


@pytest.mark.asyncio
async def test_maybe_notify_skips_when_no_url() -> None:
    """A schedule without a webhook url is silent regardless of findings."""
    sched = _schedule(webhook_url=None, last_run_id=10)
    crit = _insight(
        title="A",
        severity=InsightSeverity.critical,
        category=InsightCategory.spof,
    )
    db = _mock_db_with_query_results({10: [crit]})
    # Should be a no-op — _send_webhook would fail loudly if called with empty url.
    await scheduler._maybe_notify(db, schedule=sched, new_run_id=10, previous_run_id=None)


def _mock_db_with_query_results(by_run_id: dict[int, list]) -> AsyncMock:
    """Return an AsyncMock whose `execute(...)` returns the insight rows the
    `_maybe_notify` helper expects, keyed by the run_id condition baked into
    the WHERE clause.

    Match the call order: _maybe_notify queries new_run_id first, then
    previous_run_id (if any).
    """
    call_order = list(by_run_id.keys())
    results = []
    for rid in call_order:
        rows = by_run_id[rid]
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=rows)
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        results.append(result)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=results)
    return db
