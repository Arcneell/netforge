"""seed data — standard VLANs + default site.

Revision ID: 0002_seed
Revises: 0001_initial
Create Date: 2026-04-24

Insert starter data so that a fresh install is immediately usable. Everything
is idempotent (ON CONFLICT DO NOTHING), so re-running the migration does not
duplicate anything.

The values are generic examples: rename / extend / remove them to match your
actual network.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_seed"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Default site
    op.execute(
        """
        INSERT INTO sites (code, name, address)
        VALUES ('HQ', 'Headquarters', NULL)
        ON CONFLICT (code) DO NOTHING;
        """
    )

    # Example standard VLANs
    # 1   = management / default
    # 10  = servers
    # 20  = users
    # 30  = voip
    # 40  = wifi guest
    # 50  = dmz
    op.execute(
        """
        INSERT INTO vlans (vlan_id, name, description, color)
        VALUES
          (1,  'VLAN-MGMT',  'Management / default', '#6b7280'),
          (10, 'VLAN-SRV',   'Servers',              '#059669'),
          (20, 'VLAN-USERS', 'User workstations',    '#2563eb'),
          (30, 'VLAN-VOIP',  'IP telephony',         '#d97706'),
          (40, 'VLAN-WIFI',  'Guest wifi',           '#7c3aed'),
          (50, 'VLAN-DMZ',   'DMZ',                  '#dc2626')
        ON CONFLICT (vlan_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM vlans WHERE vlan_id IN (1, 10, 20, 30, 40, 50);")
    op.execute("DELETE FROM sites WHERE code = 'HQ';")
