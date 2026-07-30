"""FK indexes on subnets.site_id / subnets.vlan_id

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-29

`services/subnets.list_subnets` filters on `site_id` and `vlan_id` on
every call from the subnets list view, and neither column had an index —
Postgres doesn't auto-index the referencing side of a FK (same gap 0008
and 0012 already closed for other tables). Both filters were seq-scanning
`subnets` on every request.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = [
    ("ix_subnets_site_id", "subnets", "site_id"),
    ("ix_subnets_vlan_id", "subnets", "vlan_id"),
]


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _ in _INDEXES:
        op.drop_index(name, table_name=table)
