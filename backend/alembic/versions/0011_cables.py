"""add cables table — cable metadata bag, one-to-one with links

Revision ID: 0011_cables
Revises: 0010_vrf_hierarchy
Create Date: 2026-05-21

A `cables` row carries the physical-cable metadata (label, length, color,
vendor, install date, …) that we want to track independently of the
`links` row. The relationship is one-to-one via `cables.link_id` —
UNIQUE on the column, NULLs allowed (= cable in stock, not patched).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_cables"
down_revision: str | None = "0010_vrf_hierarchy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column(
            "link_id",
            sa.Integer(),
            sa.ForeignKey("links.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("length_m", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(40), nullable=True),
        sa.Column("vendor", sa.String(100), nullable=True),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("serial", sa.String(120), nullable=True),
        sa.Column("installed_on", sa.Date(), nullable=True),
        sa.Column("last_tested_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        # NULL-tolerant unique — multiple in-stock cables (NULL link_id)
        # coexist; a patched cable enforces 1:1 with its link.
        sa.UniqueConstraint("link_id", name="cables_link_uniq"),
    )
    # Helpful index for the "cables in stock" filter used by the UI.
    op.create_index(
        "ix_cables_link_id",
        "cables",
        ["link_id"],
        postgresql_where=sa.text("link_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_cables_link_id", table_name="cables")
    op.drop_table("cables")
