"""add outbound webhooks tables

Revision ID: 0009_webhooks
Revises: 0008_fk_indexes_assets
Create Date: 2026-05-21

Two new tables:

  - `webhooks`: operator-defined HTTP subscribers. One row = one URL +
    a JSONB list of event-pattern strings (`*`, `port.*`, `port.update`).
    The shared `secret` is generated at create time and used to sign
    every outbound POST with HMAC-SHA256 over the body.

  - `webhook_deliveries`: one row per dispatch attempt. Kept on a rolling
    30-day window — the scheduler trims older rows so this table never
    grows unbounded under high-mutation workloads.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_webhooks"
down_revision: str | None = "0008_fk_indexes_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("secret", sa.String(64), nullable=False),
        sa.Column(
            "events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "total_deliveries", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "total_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="webhooks_name_uniq"),
    )
    op.create_index("webhooks_enabled_idx", "webhooks", ["enabled"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "webhook_id",
            sa.Integer(),
            sa.ForeignKey("webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "webhook_deliveries_webhook_idx",
        "webhook_deliveries",
        ["webhook_id", "created_at"],
    )
    op.create_index(
        "webhook_deliveries_created_at_idx",
        "webhook_deliveries",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("webhook_deliveries_created_at_idx", table_name="webhook_deliveries")
    op.drop_index("webhook_deliveries_webhook_idx", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("webhooks_enabled_idx", table_name="webhooks")
    op.drop_table("webhooks")
