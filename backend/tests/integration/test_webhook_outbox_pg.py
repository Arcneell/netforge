"""DB-level tests for the webhook outbox durability guarantee — real Postgres.

Covers what the unit suite (`test_webhooks.py::write_outbox_row`,
`test_audit.py`) can only approximate with a mocked `Connection`: that
`write_outbox_row` genuinely shares the mutation's transaction rather than
merely being called with the right arguments. A `flush()` without a
`commit()` must leave zero `webhook_outbox` rows once rolled back — the
exact CSV dry-run scenario `services/webhooks.py`'s module docstring calls
out (Codex P1 on PR #62), now extended to the durable outbox that sits
ahead of the ContextVar-based committed bucket.

Filters every assertion by the specific row's `entity_id` rather than
scanning the whole table — `webhook_outbox` isn't wiped between tests (only
`ips`/`subnets`/`vrfs`/`sites` are, per `conftest.db`), and other
integration modules in this package mutate `sites`/`subnets`/`vrfs` too,
which the same audit listeners also turn into outbox rows.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Site
from app.models.webhook import WebhookOutbox
from app.services.audit import register_audit_listeners

from .conftest import INTEGRATION_DB_URL_VAR, integration_db_url

if not integration_db_url():
    pytest.skip(
        f"{INTEGRATION_DB_URL_VAR} is not set — skipping Postgres integration tests",
        allow_module_level=True,
    )

# Idempotent (see `register_audit_listeners`'s docstring) — safe to call
# even though `app.main` importing `create_app()` at module scope already
# does this for any process that also imported the unit suite.
register_audit_listeners()


async def _outbox_rows_for(db: AsyncSession, *, entity: str, entity_id: int) -> list[WebhookOutbox]:
    rows = await db.execute(
        select(WebhookOutbox).where(
            WebhookOutbox.entity == entity, WebhookOutbox.entity_id == entity_id
        )
    )
    return list(rows.scalars().all())


async def test_rollback_after_flush_leaves_no_outbox_row(db: AsyncSession) -> None:
    """Mirrors the CSV `dry_run=true` path: flush (fires the audit/outbox
    listener on the `Connection` beneath this session), then roll back
    instead of committing. The outbox row must not survive — same contract
    `audit_log` already has, now shared by `webhook_outbox`."""
    site = Site(code="RBOX", name="Rollback outbox co")
    db.add(site)
    await db.flush()  # Assigns site.id and fires the after_insert listener.
    site_id = site.id
    assert site_id is not None

    await db.rollback()

    # New session so we're not just reading back the rolled-back
    # transaction's own (uncommitted) view.
    rows = await _outbox_rows_for(db, entity="site", entity_id=site_id)
    assert rows == []


async def test_commit_after_flush_persists_matching_outbox_row(db: AsyncSession) -> None:
    """The row committed alongside the mutation carries the same event
    shape `WebhookEvent.to_payload()` would have produced."""
    site = Site(code="CBOX", name="Commit outbox co")
    db.add(site)
    await db.commit()
    await db.refresh(site)

    rows = await _outbox_rows_for(db, entity="site", entity_id=site.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == "site.create"
    assert row.dispatched_at is None
    assert row.attempts == 0
    assert row.last_error is None
    assert row.payload["event"] == "site.create"
    assert row.payload["after"]["code"] == "CBOX"
