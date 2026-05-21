"""add FK indexes + asset tracking fields

Revision ID: 0008_fk_indexes_assets
Revises: 0007_add_timestamps
Create Date: 2026-05-20

Two unrelated additions bundled for migration economy:

1. **FK indexes Postgres doesn't auto-create.** SQLAlchemy declares
   `ForeignKey(...)` on `devices.room_id`, `switches.room_id`,
   `ports.connected_device_id`, `ports.connected_ip_id` but never asks
   for an index — and Postgres (unlike MySQL) does NOT auto-index the
   referencing side of an FK. The topology builder, ports-by-device
   reverse lookup, and any list view filtering by room currently scan
   the full table. Adding the four indexes turns those into log-N seeks.

2. **Asset tracking columns** on `devices` + `switches`:
   - `asset_tag` (str, 50) — physical asset label (sticker, barcode).
   - `warranty_expires_at` (date) — vendor warranty cutoff.
   - `eol_date` (date) — manufacturer end-of-life. Drives the advisor's
     future "aging hardware" insight (not surfaced yet, schema first).

   Both columns are nullable — existing rows keep working without any
   backfill. The advisor and capacity dashboard will consume them later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_fk_indexes_assets"
down_revision: str | None = "0007_add_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FK_INDEXES = [
    # (table, column, index name)
    ("devices", "room_id", "ix_devices_room_id"),
    ("switches", "room_id", "ix_switches_room_id"),
    ("ports", "connected_device_id", "ix_ports_connected_device_id"),
    ("ports", "connected_ip_id", "ix_ports_connected_ip_id"),
]

_ASSET_TABLES = ("devices", "switches")


def upgrade() -> None:
    for table, column, name in _FK_INDEXES:
        op.create_index(name, table, [column])

    for table in _ASSET_TABLES:
        op.add_column(table, sa.Column("asset_tag", sa.String(50), nullable=True))
        op.add_column(table, sa.Column("warranty_expires_at", sa.Date(), nullable=True))
        op.add_column(table, sa.Column("eol_date", sa.Date(), nullable=True))


def downgrade() -> None:
    for table in _ASSET_TABLES:
        op.drop_column(table, "eol_date")
        op.drop_column(table, "warranty_expires_at")
        op.drop_column(table, "asset_tag")

    for _, _, name in _FK_INDEXES:
        op.drop_index(name)
