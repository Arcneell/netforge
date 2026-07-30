"""Tests for the webhook outbox — the durable handoff between "mutation
committed" and "dispatch fired".

See `app/models/webhook.py::WebhookOutbox` and the module docstring of
`services/webhooks.py` for the full rationale. `write_outbox_row`'s "same
transaction as the mutation" guarantee rides on reusing the exact
`Connection` the audit listener already has — structurally the same
guarantee `audit_log` has. That's exercised end-to-end (real commit vs.
real rollback) in `tests/integration/test_webhook_outbox_pg.py`; here we
pin the call shape with a mocked `Connection` and cover the sweep/backoff/
purge/advisory-lock logic with mocked sessions, the same style
`tests/test_ai_scheduler.py` uses for the analogous AI scheduler lock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Delete, Update

from app.services import webhooks as webhooks_module
from app.services.webhooks import (
    _OUTBOX_MAX_ATTEMPTS,
    WebhookEvent,
    _cumulative_backoff,
    _is_due_for_retry,
    _mark_outbox_dispatched,
    _maybe_cleanup_dispatched_outbox_rows,
    _ReplayEvent,
    _sweep_outbox_once,
    _try_acquire_outbox_sweep_lock,
    queue_event,
    take_pending,
    write_outbox_row,
)


@pytest.fixture(autouse=True)
def _drain_queue_before_each():
    """Same hygiene as `test_webhooks.py` — the pending-events ContextVar
    is process-wide when tests run synchronously."""
    take_pending()
    yield
    take_pending()


# --- write_outbox_row --------------------------------------------------------


def test_write_outbox_row_inserts_on_the_given_connection_and_sets_outbox_id() -> None:
    """Pins the call-shape contract: one INSERT ... RETURNING id on the
    caller's `Connection`, with `event.outbox_id` set from the result.
    Real transactional rollback semantics are covered by the Postgres
    integration test, not here — a mocked `Connection` can't demonstrate
    an actual rollback."""
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 42
    ev = WebhookEvent(
        entity="site", action="create", entity_id=7, before=None, after={"code": "HQ"}, user_id=3
    )

    write_outbox_row(conn, ev)

    conn.execute.assert_called_once()
    assert ev.outbox_id == 42

    stmt = conn.execute.call_args.args[0]
    params = stmt.compile().params
    assert params["event_type"] == "site.create"
    assert params["entity"] == "site"
    assert params["entity_id"] == 7
    assert params["payload"]["event"] == "site.create"
    assert params["payload"]["after"] == {"code": "HQ"}


def test_write_outbox_row_payload_is_json_round_tripped() -> None:
    """Same guard `_write_audit_row` applies to `audit_log.changes`: the
    payload is round-tripped through json.dumps/loads so nothing
    non-JSON-serialisable slips into the JSONB column."""
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 1
    occurred = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    ev = WebhookEvent(
        entity="port",
        action="update",
        entity_id=1,
        before=None,
        after=None,
        user_id=None,
        occurred_at=occurred,
    )

    write_outbox_row(conn, ev)

    stmt = conn.execute.call_args.args[0]
    payload = stmt.compile().params["payload"]
    assert payload["occurred_at"] == occurred.isoformat()


# --- queue_event returns the queued WebhookEvent ----------------------------


def test_queue_event_returns_the_queued_event_for_outbox_wiring() -> None:
    """`services/audit.py::_write_audit_row` needs the exact `WebhookEvent`
    instance back so it can hand it to `write_outbox_row` — the two must
    describe the same event, and `write_outbox_row` mutates `outbox_id` on
    the very instance sitting in the ContextVar bucket."""
    ev = queue_event("site", "create", 5, None, {"code": "HQ"}, user_id=2)
    assert ev.event_name == "site.create"
    assert ev.outbox_id is None
    assert take_pending() == [ev]


# --- _ReplayEvent -------------------------------------------------------------


def test_replay_event_returns_the_stored_payload_verbatim() -> None:
    """Replaying from the outbox must not re-run redaction / serialisation
    — the stored payload IS what the first attempt would have sent."""
    stored_payload = {"event": "switch.update", "after": {"snmp_community": "***"}}
    replay = _ReplayEvent(event_name="switch.update", payload=stored_payload)
    assert replay.event_name == "switch.update"
    assert replay.to_payload() is stored_payload


# --- _mark_outbox_dispatched --------------------------------------------------


@pytest.mark.asyncio
async def test_mark_outbox_dispatched_is_a_noop_without_any_outbox_id() -> None:
    """Events built outside the outbox path (e.g. a bare `WebhookEvent` in
    a test, or a future caller) must not trigger a query at all."""
    db = AsyncMock()
    ev = WebhookEvent(
        entity="site", action="create", entity_id=1, before=None, after=None, user_id=None
    )
    await _mark_outbox_dispatched(db, [ev])
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_outbox_dispatched_updates_and_commits_for_tagged_events() -> None:
    db = AsyncMock()
    ev1 = WebhookEvent(
        entity="site", action="create", entity_id=1, before=None, after=None, user_id=None
    )
    ev1.outbox_id = 10
    ev2 = WebhookEvent(
        entity="port", action="update", entity_id=2, before=None, after=None, user_id=None
    )
    ev2.outbox_id = 11
    # Mixed batch: one tagged, one not — only the tagged one should end up
    # in the UPDATE's WHERE ... IN (...).
    ev3 = WebhookEvent(
        entity="vlan", action="delete", entity_id=3, before=None, after=None, user_id=None
    )

    await _mark_outbox_dispatched(db, [ev1, ev2, ev3])

    db.execute.assert_awaited_once()
    stmt = db.execute.await_args.args[0]
    assert isinstance(stmt, Update)
    db.commit.assert_awaited_once()


# --- _cumulative_backoff / _is_due_for_retry ---------------------------------


def test_cumulative_backoff_matches_the_documented_schedule() -> None:
    """30s, then +2min, then +10min — matches the design's documented
    backoff steps. Beyond the schedule's length the longest step repeats
    rather than growing further."""
    assert _cumulative_backoff(0) == timedelta(seconds=30)
    assert _cumulative_backoff(1) == timedelta(seconds=30) + timedelta(minutes=2)
    assert _cumulative_backoff(2) == (
        timedelta(seconds=30) + timedelta(minutes=2) + timedelta(minutes=10)
    )
    assert _cumulative_backoff(3) == _cumulative_backoff(2) + timedelta(minutes=10)
    assert _cumulative_backoff(4) == _cumulative_backoff(3) + timedelta(minutes=10)


def test_is_due_for_retry_respects_the_30s_grace_window() -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    assert _is_due_for_retry(now - timedelta(seconds=29), attempts=0, now=now) is False
    assert _is_due_for_retry(now - timedelta(seconds=31), attempts=0, now=now) is True


def test_is_due_for_retry_respects_the_backoff_schedule_between_attempts() -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    # attempts=1 needs 30s + 2min == 2m30s since created_at.
    just_under = now - (timedelta(seconds=30) + timedelta(minutes=2) - timedelta(seconds=1))
    just_over = now - (timedelta(seconds=30) + timedelta(minutes=2) + timedelta(seconds=1))
    assert _is_due_for_retry(just_under, attempts=1, now=now) is False
    assert _is_due_for_retry(just_over, attempts=1, now=now) is True


def test_is_due_for_retry_abandons_at_max_attempts() -> None:
    """Even a row created a year ago is never retried once it's used up its
    budget — `last_error` stays as the operator-visible record."""
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    ancient = now - timedelta(days=365)
    assert _is_due_for_retry(ancient, attempts=_OUTBOX_MAX_ATTEMPTS, now=now) is False
    assert _is_due_for_retry(ancient, attempts=_OUTBOX_MAX_ATTEMPTS + 1, now=now) is False
    assert _is_due_for_retry(ancient, attempts=_OUTBOX_MAX_ATTEMPTS - 1, now=now) is True


# --- advisory lock (mirrors tests/test_ai_scheduler.py's schedule lock) -----


@pytest.mark.asyncio
async def test_try_acquire_outbox_sweep_lock_skips_for_non_postgres() -> None:
    db = AsyncMock()  # generic mock: no resolvable postgresql dialect
    acquired = await _try_acquire_outbox_sweep_lock(db)
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
async def test_try_acquire_outbox_sweep_lock_calls_pg_try_advisory_xact_lock() -> None:
    db = _fake_postgres_db(lock_result=True)
    acquired = await _try_acquire_outbox_sweep_lock(db)
    assert acquired is True
    db.execute.assert_awaited_once()
    compiled = str(db.execute.await_args.args[0])
    assert "pg_try_advisory_xact_lock" in compiled


@pytest.mark.asyncio
async def test_try_acquire_outbox_sweep_lock_returns_false_when_already_held() -> None:
    db = _fake_postgres_db(lock_result=False)
    acquired = await _try_acquire_outbox_sweep_lock(db)
    assert acquired is False


# --- purge throttling (mirrors _maybe_cleanup_old_deliveries / run-log purge)


@pytest.mark.asyncio
async def test_outbox_purge_runs_once_per_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhooks_module, "_last_outbox_cleanup_at", None)
    db = AsyncMock()

    await _maybe_cleanup_dispatched_outbox_rows(db)
    deletes = [c.args[0] for c in db.execute.await_args_list if isinstance(c.args[0], Delete)]
    assert len(deletes) == 1
    db.commit.assert_awaited()

    db2 = AsyncMock()
    await _maybe_cleanup_dispatched_outbox_rows(db2)
    db2.execute.assert_not_awaited()


# --- _sweep_outbox_once -------------------------------------------------------


class _FakeAsyncCtx:
    """Minimal `async with SessionLocal() as db:` stand-in around a
    pre-built fake session object."""

    def __init__(self, obj: object) -> None:
        self._obj = obj

    async def __aenter__(self) -> object:
        return self._obj

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _scalars_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    return result


@pytest.mark.asyncio
async def test_sweep_outbox_once_skips_entirely_when_lock_not_acquired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_db = AsyncMock()
    work_db = AsyncMock()
    sessions = iter([lock_db, work_db])
    monkeypatch.setattr(webhooks_module, "SessionLocal", lambda: _FakeAsyncCtx(next(sessions)))
    monkeypatch.setattr(
        webhooks_module, "_try_acquire_outbox_sweep_lock", AsyncMock(return_value=False)
    )

    await _sweep_outbox_once()

    work_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_outbox_once_dispatches_due_rows_and_marks_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    due_row = SimpleNamespace(
        id=1,
        event_type="port.update",
        entity="port",
        entity_id=5,
        payload={"event": "port.update"},
        created_at=now - timedelta(minutes=5),
        dispatched_at=None,
        attempts=0,
        last_error=None,
    )
    webhook = SimpleNamespace(
        id=9, url="https://hooks.example/x", secret="s", events=["port.*"], enabled=True
    )

    lock_db = AsyncMock()
    work_db = AsyncMock()
    work_db.execute = AsyncMock(
        side_effect=[_scalars_result([due_row]), _scalars_result([webhook])]
    )
    sessions = iter([lock_db, work_db])
    monkeypatch.setattr(webhooks_module, "SessionLocal", lambda: _FakeAsyncCtx(next(sessions)))
    monkeypatch.setattr(
        webhooks_module, "_try_acquire_outbox_sweep_lock", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(webhooks_module, "_maybe_cleanup_dispatched_outbox_rows", AsyncMock())

    delivered: list[tuple[int, str, dict]] = []

    async def fake_deliver_one(webhook_id, url, secret, ev):
        delivered.append((webhook_id, ev.event_name, ev.to_payload()))

    monkeypatch.setattr(webhooks_module, "_deliver_one", fake_deliver_one)

    await _sweep_outbox_once()

    assert delivered == [(9, "port.update", {"event": "port.update"})]
    assert due_row.dispatched_at is not None
    assert due_row.attempts == 1
    assert due_row.last_error is None
    work_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_sweep_outbox_once_records_last_error_without_marking_dispatched_on_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash in the fan-out (not an individual HTTP failure — those are
    `WebhookDelivery`'s job and never raise) leaves `dispatched_at` NULL,
    bumps `attempts`, and records `last_error` for the next pass / the
    operator."""
    now = datetime.now(UTC)
    due_row = SimpleNamespace(
        id=2,
        event_type="site.create",
        entity="site",
        entity_id=1,
        payload={"event": "site.create"},
        # attempts=2 requires >= 30s + 2min + 10min = 12m30s of age
        # (`_cumulative_backoff(2)`) before it's due — 20 minutes clears that.
        created_at=now - timedelta(minutes=20),
        dispatched_at=None,
        attempts=2,
        last_error=None,
    )
    webhook = SimpleNamespace(id=1, url="https://hooks.example/x", secret="s", events=["*"], enabled=True)

    lock_db = AsyncMock()
    work_db = AsyncMock()
    work_db.execute = AsyncMock(
        side_effect=[_scalars_result([due_row]), _scalars_result([webhook])]
    )
    sessions = iter([lock_db, work_db])
    monkeypatch.setattr(webhooks_module, "SessionLocal", lambda: _FakeAsyncCtx(next(sessions)))
    monkeypatch.setattr(
        webhooks_module, "_try_acquire_outbox_sweep_lock", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(webhooks_module, "_maybe_cleanup_dispatched_outbox_rows", AsyncMock())

    async def boom(*_a: object, **_kw: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(webhooks_module, "_deliver_one_bounded", boom)

    await _sweep_outbox_once()

    assert due_row.dispatched_at is None
    assert due_row.attempts == 3
    assert "RuntimeError" in (due_row.last_error or "")
    work_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_sweep_outbox_once_skips_rows_not_yet_due(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row created 10s ago is younger than the 30s grace window — even
    though the coarse SQL filter (`created_at < now - 30s`) already keeps
    it out in production, this pins the Python-side `_is_due_for_retry`
    double-check the test doubles below bypass."""
    now = datetime.now(UTC)
    too_young = SimpleNamespace(
        id=3,
        event_type="site.create",
        entity="site",
        entity_id=1,
        payload={},
        created_at=now - timedelta(seconds=5),
        dispatched_at=None,
        attempts=0,
        last_error=None,
    )

    lock_db = AsyncMock()
    work_db = AsyncMock()
    work_db.execute = AsyncMock(side_effect=[_scalars_result([too_young])])
    sessions = iter([lock_db, work_db])
    monkeypatch.setattr(webhooks_module, "SessionLocal", lambda: _FakeAsyncCtx(next(sessions)))
    monkeypatch.setattr(
        webhooks_module, "_try_acquire_outbox_sweep_lock", AsyncMock(return_value=True)
    )

    await _sweep_outbox_once()

    # Only the candidates query ran — no second `select(Webhook)` query,
    # because `due` ended up empty and the function returned early.
    assert work_db.execute.await_count == 1
    assert too_young.attempts == 0
