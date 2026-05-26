"""add IPAM hot-path indexes (FK + pg_trgm for ILIKE search)

Revision ID: 0012_ipam_indexes
Revises: 0011_cables
Create Date: 2026-05-26

Two unrelated additions bundled to keep the migration count down:

1. **Missing FK index on `ips.subnet_id`.** SQLAlchemy declares the FK but
   never asks for an index — and Postgres, unlike MySQL, does NOT auto-index
   the referencing side of an FK. Every per-subnet IP listing, the subnet
   utilisation count, the tree builder's fill-rate query, and the cascade on
   subnet delete were all scanning `ips` in full. Same pattern as 0008
   already fixed for `devices.room_id` / `switches.room_id`.

2. **pg_trgm GIN indexes on the columns the global search ILIKEs.** The
   /api/search endpoint issues `column ILIKE '%term%'` against eight tables.
   Without a trigram index those degrade to seq scans on every entity type,
   so search latency grows linearly with the inventory size. We add GIN
   indexes on the user-facing free-text columns; the INET / MACADDR /
   integer columns get functional indexes on their text cast since ILIKE
   forces a cast there too (`cast(Ip.address, String).ilike(...)`).

   No-op on databases that already have `pg_trgm` enabled. `CREATE
   EXTENSION` requires superuser the first time — for managed Postgres
   instances where that isn't available, the operator should pre-enable
   the extension and re-run.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_ipam_indexes"
down_revision: str | None = "0011_cables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Plain text columns: GIN trigram is fine, no cast needed.
_TEXT_TRGM_INDEXES: list[tuple[str, str, str]] = [
    # (index name, table, column)
    ("ix_ips_hostname_trgm", "ips", "hostname"),
    ("ix_ips_description_trgm", "ips", "description"),
    ("ix_subnets_description_trgm", "subnets", "description"),
    ("ix_vlans_name_trgm", "vlans", "name"),
    ("ix_vlans_description_trgm", "vlans", "description"),
    ("ix_devices_name_trgm", "devices", "name"),
    ("ix_devices_serial_trgm", "devices", "serial"),
    ("ix_devices_model_trgm", "devices", "model"),
    ("ix_switches_name_trgm", "switches", "name"),
    ("ix_ports_label_trgm", "ports", "label"),
    ("ix_sites_code_trgm", "sites", "code"),
    ("ix_sites_name_trgm", "sites", "name"),
    ("ix_sites_address_trgm", "sites", "address"),
    ("ix_rooms_code_trgm", "rooms", "code"),
    ("ix_rooms_description_trgm", "rooms", "description"),
]

# Typed columns (INET / MACADDR / numeric) the search casts to text before
# ILIKE — index the cast so the planner can still use a GIN trgm scan.
_FUNCTIONAL_TRGM_INDEXES: list[tuple[str, str, str]] = [
    # (index name, table, expression)
    ("ix_ips_address_text_trgm", "ips", "(address::text)"),
    ("ix_ips_mac_text_trgm", "ips", "(mac::text)"),
    ("ix_switches_management_ip_trgm", "switches", "(management_ip::text)"),
    ("ix_subnets_cidr_text_trgm", "subnets", "(cidr::text)"),
    ("ix_vlans_vlan_id_text_trgm", "vlans", "(vlan_id::text)"),
]


def upgrade() -> None:
    # 1. FK index on ips.subnet_id — critical for per-subnet listings and
    #    the cascade on subnet delete. Cheap one-time build, huge payoff.
    op.create_index("ix_ips_subnet_id", "ips", ["subnet_id"])

    # 2. pg_trgm extension — required for the GIN gin_trgm_ops operator class
    #    used by every search index below. `IF NOT EXISTS` keeps the migration
    #    idempotent on databases where the extension is already present (e.g.
    #    when restoring a dump from a previous environment).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    for name, table, column in _TEXT_TRGM_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"USING gin ({column} gin_trgm_ops);"
        )

    for name, table, expression in _FUNCTIONAL_TRGM_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"USING gin ({expression} gin_trgm_ops);"
        )


def downgrade() -> None:
    for name, _, _ in _FUNCTIONAL_TRGM_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name};")
    for name, _, _ in _TEXT_TRGM_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name};")
    # Leave pg_trgm installed — other tooling may rely on it, and dropping
    # an extension that other objects depend on would fail anyway.
    op.drop_index("ix_ips_subnet_id", table_name="ips")
