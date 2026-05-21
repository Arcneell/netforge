"""add VRFs + subnet hierarchy + per-VRF overlap exclusion

Revision ID: 0010_vrf_hierarchy
Revises: 0009_webhooks
Create Date: 2026-05-21

Three coordinated changes:

1. New `vrfs` table — routing-table isolation units. A row in this table
   defines a scope inside which subnet CIDRs may not overlap; subnets in
   different VRFs are free to share a CIDR. `vrf_id IS NULL` represents
   the global VRF (legacy behaviour).

2. Two new columns on `subnets`:
   - `vrf_id` (nullable FK → vrfs.id): scope assignment, NULL = global.
   - `parent_subnet_id` (nullable self-FK): hierarchical IPAM. The
     service layer enforces that a child CIDR is contained within its
     parent — the DB only checks the FK target exists.

3. The global `subnets_no_overlap` GiST exclusion is replaced with
   TWO exclusions:
     - `subnets_no_overlap_global` — fires only when `vrf_id IS NULL`.
     - `subnets_no_overlap_vrf` — adds `vrf_id WITH =` so collisions
       are scoped to one VRF.
   We migrate atomically: drop the old constraint, add the two new ones.
   Existing rows all have `vrf_id IS NULL` so the global exclusion
   takes over with identical semantics.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_vrf_hierarchy"
down_revision: str | None = "0009_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. vrfs table -----------------------------------------------------
    op.create_table(
        "vrfs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("rd", sa.String(32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("name", name="vrfs_name_uniq"),
        sa.UniqueConstraint("rd", name="vrfs_rd_uniq"),
    )

    # 2. subnets columns ------------------------------------------------
    op.add_column(
        "subnets",
        sa.Column(
            "vrf_id",
            sa.Integer(),
            sa.ForeignKey("vrfs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "subnets",
        sa.Column(
            "parent_subnet_id",
            sa.Integer(),
            sa.ForeignKey("subnets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_subnets_vrf_id", "subnets", ["vrf_id"])
    op.create_index("ix_subnets_parent_id", "subnets", ["parent_subnet_id"])

    # 3. Replace the global GiST exclusion with two scoped exclusions.
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap;")
    # Global scope: vrf_id IS NULL. Partial index so VRF-bound subnets
    # don't trip it.
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap_global "
        "EXCLUDE USING gist (cidr inet_ops WITH &&) "
        "WHERE (vrf_id IS NULL);"
    )
    # VRF-scoped: `vrf_id WITH =` ensures two rows only collide when
    # they share the same vrf_id. The partial WHERE keeps NULL rows
    # out (they're covered by the global exclusion above).
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap_vrf "
        "EXCLUDE USING gist (vrf_id WITH =, cidr inet_ops WITH &&) "
        "WHERE (vrf_id IS NOT NULL);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap_vrf;")
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap_global;")
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap "
        "EXCLUDE USING gist (cidr inet_ops WITH &&);"
    )
    op.drop_index("ix_subnets_parent_id", table_name="subnets")
    op.drop_index("ix_subnets_vrf_id", table_name="subnets")
    op.drop_column("subnets", "parent_subnet_id")
    op.drop_column("subnets", "vrf_id")
    op.drop_table("vrfs")
