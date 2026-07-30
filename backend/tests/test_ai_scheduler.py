"""Tests for the AI scheduler — due-check, webhook diff, payload shape.

The scheduler loop itself is an asyncio task that talks to a real session;
we test the pure helpers + the diff logic with mocked sessions.
"""

from __future__ import annotations

import asyncio
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


@pytest.mark.asyncio
async def test_run_log_cleanup_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retention sweep runs at most once per interval — the loop wakes
    every minute and must not scan `ai_run_logs` each tick."""
    from sqlalchemy.sql.dml import Delete

    monkeypatch.setattr(scheduler, "_last_run_log_cleanup_at", None)
    db = AsyncMock()

    await scheduler._maybe_cleanup_run_logs(db)
    deletes = [c.args[0] for c in db.execute.await_args_list if isinstance(c.args[0], Delete)]
    assert len(deletes) == 1
    db.commit.assert_awaited()
    # The DELETE must exclude the latest successful advisor run (its
    # infra_insights rows CASCADE away with it) — pinned via the compiled
    # SQL, which carries the NOT IN subquery on ai_run_logs.
    compiled = str(deletes[0].compile())
    assert "NOT IN" in compiled.upper()
    assert "created_at" in compiled

    # Second pass inside the throttle window: no further DELETE.
    db2 = AsyncMock()
    await scheduler._maybe_cleanup_run_logs(db2)
    db2.execute.assert_not_awaited()


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


# --- Per-schedule isolation in the tick loop (HIGH audit fix) ---------------


@pytest.mark.asyncio
async def test_loop_isolates_schedule_failures_and_still_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schedule whose bookkeeping crashes (previously: the last_run_at
    commit or `_maybe_notify` raising) used to propagate straight out of the
    `for schedule in due` loop, silently skipping every remaining due
    schedule for the tick AND the retention cleanup pass that follows.
    One schedule's bug must not starve the others."""
    calls: dict[str, list] = {"run_one": [], "cleanup": 0}

    class _FakeSessionCtx:
        async def __aenter__(self):
            return "fake-db"

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: _FakeSessionCtx())

    sched_a = SimpleNamespace(id=1, kind=AIRunKind.advisor)
    sched_b = SimpleNamespace(id=2, kind=AIRunKind.suggest_links)

    async def fake_list_due(_db, _now):
        return [sched_a, sched_b]

    monkeypatch.setattr(scheduler, "_list_due", fake_list_due)

    async def fake_run_one(_db, schedule):
        calls["run_one"].append(schedule.id)
        if schedule.id == 1:
            raise RuntimeError("bookkeeping blew up (e.g. commit() or _maybe_notify)")

    monkeypatch.setattr(scheduler, "_run_one", fake_run_one)

    async def fake_cleanup(_db):
        calls["cleanup"] += 1

    monkeypatch.setattr(scheduler, "_maybe_cleanup_run_logs", fake_cleanup)

    # Break out of the `while True` after exactly one tick — mirrors how
    # `stop_scheduler()` cancels the real background task, without needing
    # a real timer or a spawned task in the test.
    async def fake_sleep(_seconds):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await scheduler._loop()

    # Both schedules were attempted — schedule 1 crashing didn't stop 2.
    assert calls["run_one"] == [1, 2]
    # The retention cleanup still ran despite schedule 1's crash.
    assert calls["cleanup"] == 1


# --- Anti-overlap advisory lock (HIGH audit fix) ----------------------------


@pytest.mark.asyncio
async def test_try_acquire_schedule_lock_skips_for_non_postgres() -> None:
    """Unit tests (and any non-Postgres backend) don't have
    `pg_try_advisory_xact_lock` — the lock check must fail open (acquired)
    rather than error out."""
    db = AsyncMock()  # generic mock: no resolvable postgresql dialect
    acquired = await scheduler._try_acquire_schedule_lock(db, 42)
    assert acquired is True
    db.execute.assert_not_awaited()


def _fake_postgres_db(lock_result: bool) -> AsyncMock:
    db = AsyncMock()
    db.sync_session = SimpleNamespace(
        bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    result = MagicMock()
    result.scalar = MagicMock(return_value=lock_result)
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_try_acquire_schedule_lock_calls_pg_try_advisory_xact_lock() -> None:
    db = _fake_postgres_db(lock_result=True)
    acquired = await scheduler._try_acquire_schedule_lock(db, 42)
    assert acquired is True
    db.execute.assert_awaited_once()
    compiled = str(db.execute.await_args.args[0])
    assert "pg_try_advisory_xact_lock" in compiled


@pytest.mark.asyncio
async def test_try_acquire_schedule_lock_returns_false_when_already_held() -> None:
    """Another replica/worker already has this schedule's lock — must
    report "not acquired" rather than blocking or raising."""
    db = _fake_postgres_db(lock_result=False)
    acquired = await scheduler._try_acquire_schedule_lock(db, 42)
    assert acquired is False


# --- Outbound webhook HMAC signature (MEDIUM audit fix) ---------------------


@pytest.mark.asyncio
async def test_send_webhook_signs_body_when_secret_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.webhooks import sign_body

    captured: dict = {}

    async def fake_safe_post(url, *, content=None, json=None, headers=None, timeout=10.0, allow_private=False):
        captured["content"] = content
        captured["headers"] = headers
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("app.utils.ssrf.safe_post", fake_safe_post)
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(
            webhook_allow_private_targets=False,
            ai_webhook_signing_secret="s3cr3t",
        ),
    )

    await scheduler._send_webhook(
        "https://hooks.example/relay", {"event": "advisor.new_findings", "findings": []}
    )

    headers = captured["headers"]
    assert "X-Netforge-Signature" in headers
    assert headers["X-Netforge-Signature"].startswith("sha256=")
    # The signature must verify against the EXACT bytes that were sent —
    # not a re-serialisation that could reorder keys / change separators.
    assert sign_body("s3cr3t", captured["content"]) == headers["X-Netforge-Signature"]


@pytest.mark.asyncio
async def test_send_webhook_unsigned_when_no_secret_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `ai_webhook_signing_secret` field on `Settings` yet — must no-op
    (no signature header) rather than crash. Also pins the "unsigned by
    default" behaviour once the setting exists but is left empty."""
    captured: dict = {}

    async def fake_safe_post(url, *, content=None, json=None, headers=None, timeout=10.0, allow_private=False):
        captured["headers"] = headers
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("app.utils.ssrf.safe_post", fake_safe_post)
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(webhook_allow_private_targets=False),
    )

    await scheduler._send_webhook(
        "https://hooks.example/relay", {"event": "advisor.new_findings", "findings": []}
    )

    assert "X-Netforge-Signature" not in captured["headers"]
