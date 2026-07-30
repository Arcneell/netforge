"""persistent outbox for outbound webhook events

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-29

Audit finding: committed webhook events used to live only in a
request-scoped ContextVar between the mutation's commit and the
fire-and-forget dispatch task (`services/webhooks.py`) — a process crash
in that window loses the event for good. This migration adds the durable
handoff: `webhook_outbox` gets one row per committed mutation, written on
the SAME `Connection`/transaction as the mutation itself (see
`services/audit.py::_write_audit_row`, which now calls
`services/webhooks.py::write_outbox_row` right next to the existing
`audit_log` insert). Row and mutation commit or roll back together.

Columns
-------
- `event_type`    — `{entity}.{action}` (e.g. `port.update`), same string
                    `WebhookEvent.event_name` / `WebhookDelivery.event` use.
- `entity` / `entity_id` — denormalised out of `event_type` purely so an
                    operator can filter without parsing the string.
- `payload`       — the exact dict `WebhookEvent.to_payload()` produced
                    (already redacted) — replaying it verbatim keeps a
                    retried delivery byte-identical to the first attempt.
- `dispatched_at` — NULL until a dispatch attempt (fast path or sweep)
                    completes without the fan-out itself crashing. Not
                    gated on every subscriber returning 2xx — per-endpoint
                    HTTP outcomes are `webhook_deliveries`' job, and that
                    table deliberately does not retry (see
                    `services/webhooks.py::_deliver_one`'s docstring).
- `attempts` / `last_error` — bookkeeping for the catch-up sweep
                    (`services/webhooks.py::_sweep_outbox_once`), which
                    backs off 30s / 2min / 10min between retries and gives
                    up after 5 attempts, leaving `last_error` for the
                    operator.

Indexes
-------
- `webhook_outbox_undispatched_idx (dispatched_at, created_at)` — the
  sweep's hot query is "dispatched_at IS NULL ORDER BY created_at".
- `webhook_outbox_dispatched_at_idx (dispatched_at)` — the purge's
  "dispatched_at IS NOT NULL AND dispatched_at < cutoff" range delete.

Downgrade drops the table — rows are an internal dispatch-durability
mechanism, not user-facing data, so nothing else references it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "webhook_outbox_undispatched_idx",
        "webhook_outbox",
        ["dispatched_at", "created_at"],
    )
    op.create_index(
        "webhook_outbox_dispatched_at_idx",
        "webhook_outbox",
        ["dispatched_at"],
    )


def downgrade() -> None:
    op.drop_index("webhook_outbox_dispatched_at_idx", table_name="webhook_outbox")
    op.drop_index("webhook_outbox_undispatched_idx", table_name="webhook_outbox")
    op.drop_table("webhook_outbox")
