"""add timestamps to Port / Room / Vlan / Device

Revision ID: 0007_add_timestamps
Revises: 0006_ai_action_drafts
Create Date: 2026-05-19

Adds `created_at` + `updated_at` (server-managed) to the four tables that
the AI snapshot cache was previously fingerprinting by row-count only.
Without per-row timestamps, a pure UPDATE (e.g. `update_port` flipping
`admin_status` or rewriting `notes`) didn't change the count and slipped
past the 5-minute TTL — an AI feature would serve a stale snapshot.

The new columns let `services/ai/snapshot_cache._compute_fingerprint`
include `max(updated_at)` for these tables, closing the staleness window.
Existing rows get `now()` as a one-shot default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_add_timestamps"
down_revision: str | None = "0006_ai_action_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = ("ports", "rooms", "vlans", "devices")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        # Postgres trigger to bump `updated_at` on every UPDATE — matches
        # the SQLAlchemy `onupdate=func.now()` behaviour but is enforced at
        # the DB layer, so writes that bypass the ORM (e.g. raw SQL bulk
        # imports) still trigger the bump.
        trigger_name = f"trg_{table}_set_updated_at"
        op.execute(
            f"""
            CREATE OR REPLACE FUNCTION set_updated_at_{table}()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = now();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at_{table}();
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table};")
        op.execute(f"DROP FUNCTION IF EXISTS set_updated_at_{table}();")
        op.drop_column(table, "updated_at")
        op.drop_column(table, "created_at")
