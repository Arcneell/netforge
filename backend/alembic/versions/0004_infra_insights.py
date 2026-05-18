"""infra_insights — AI advisor recommendations.

Revision ID: 0004_infra_insights
Revises: 0003_ai_tables
Create Date: 2026-05-18

Adds the `infra_insights` table. Each row is one AI-generated recommendation
attached to an `ai_run_logs` row — the "active" set is whatever shares the
latest run_id, older rows stay for history but the UI filters on the most
recent run.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_infra_insights"
down_revision: str | None = "0003_ai_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    severity = sa.Enum(
        "info",
        "warning",
        "critical",
        name="insight_severity",
        native_enum=True,
    )
    severity.create(op.get_bind(), checkfirst=True)

    category = sa.Enum(
        "spof",
        "capacity",
        "security",
        "segmentation",
        "naming",
        "redundancy",
        "other",
        name="insight_category",
        native_enum=True,
    )
    category.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "infra_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("ai_run_logs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", severity, nullable=False),
        sa.Column("category", category, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False, server_default=""),
        sa.Column("affected_entities", postgresql.JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("infra_insights_run_idx", "infra_insights", ["run_id", "severity"])
    op.create_index("infra_insights_category_idx", "infra_insights", ["category"])


def downgrade() -> None:
    op.drop_index("infra_insights_category_idx", table_name="infra_insights")
    op.drop_index("infra_insights_run_idx", table_name="infra_insights")
    op.drop_table("infra_insights")
    sa.Enum(name="insight_category").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="insight_severity").drop(op.get_bind(), checkfirst=True)
