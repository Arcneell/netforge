"""ai_schedules — periodic advisor / suggest-links runs.

Revision ID: 0005_ai_schedules
Revises: 0004_infra_insights
Create Date: 2026-05-19

Adds the `ai_schedules` table — one row per recurring AI task (advisor or
suggest-links). The kind is unique: at most one schedule per feature.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_ai_schedules"
down_revision: str | None = "0004_infra_insights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reuse the existing `ai_run_kind` and `insight_severity` enums — they
    # already exist from earlier migrations. `create_type=False` makes
    # SQLAlchemy reference the existing type instead of redeclaring it.
    kind = postgresql.ENUM(name="ai_run_kind", create_type=False)
    severity = postgresql.ENUM(name="insight_severity", create_type=False)

    op.create_table(
        "ai_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", kind, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column(
            "webhook_severity_threshold",
            severity,
            nullable=False,
            server_default="warning",
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_run_id",
            sa.Integer(),
            sa.ForeignKey("ai_run_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        # At most one schedule per kind — the UI editor upserts on this.
        sa.UniqueConstraint("kind", name="ai_schedules_kind_uniq"),
        # interval is in minutes, ≥ 15 (keep providers happy + cost low).
        sa.CheckConstraint(
            "interval_minutes >= 15 AND interval_minutes <= 10080",
            name="ai_schedules_interval_bounds",
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_schedules")
