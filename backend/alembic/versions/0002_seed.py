"""seed data — VLANs standards + site par défaut.

Revision ID: 0002_seed
Revises: 0001_initial
Create Date: 2026-04-24

Insère des données de départ pour qu'une install fraîche soit immédiatement
utilisable. Tout est idempotent (ON CONFLICT DO NOTHING) — jouer la migration
deux fois ne duplique pas.

Les valeurs sont des exemples génériques : renommer / étendre / supprimer
selon votre parc réel.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_seed"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Site par défaut
    op.execute(
        """
        INSERT INTO sites (code, name, address)
        VALUES ('SIEGE', 'Site principal', NULL)
        ON CONFLICT (code) DO NOTHING;
        """
    )

    # VLANs standards d'exemple
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
          (10, 'VLAN-SRV',   'Serveurs',             '#059669'),
          (20, 'VLAN-USERS', 'Postes utilisateurs',  '#2563eb'),
          (30, 'VLAN-VOIP',  'Téléphonie IP',        '#d97706'),
          (40, 'VLAN-WIFI',  'Wifi invités',         '#7c3aed'),
          (50, 'VLAN-DMZ',   'DMZ',                  '#dc2626')
        ON CONFLICT (vlan_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM vlans WHERE vlan_id IN (1, 10, 20, 30, 40, 50);")
    op.execute("DELETE FROM sites WHERE code = 'SIEGE';")
