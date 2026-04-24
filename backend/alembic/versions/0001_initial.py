"""initial schema — toutes les tables + GiST + triggers métier.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-24

Ce qu'on crée ici, dans l'ordre :

1. Enums PostgreSQL natifs (ip_status, device_type, port_mode, ...).
2. Tables `sites`, `rooms` (coeur du parc physique).
3. `vlans`.
4. `subnets` avec contrainte d'exclusion GiST empêchant le chevauchement de CIDR.
5. `devices`, `switches`, `ports` (avec UNIQUE(switch_id, number)), `port_vlan`.
6. `ips` avec trigger vérifiant que l'adresse appartient bien au subnet.
7. `links` (port_a_id < port_b_id garanti par CHECK).
8. `users`, `sessions`, `audit_log`.
9. Triggers updated_at.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extension pour GiST sur inet (fournit la classe d'opérateurs inet_ops)
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    ip_status = postgresql.ENUM("reserved", "assigned", "dhcp", name="ip_status")
    device_type = postgresql.ENUM(
        "server", "desktop", "laptop", "printer", "phone", "ap", "camera", "ups", "other",
        name="device_type",
    )
    port_mode = postgresql.ENUM("access", "trunk", "hybrid", "disabled", name="port_mode")
    port_admin_status = postgresql.ENUM("up", "down", name="port_admin_status")
    link_type = postgresql.ENUM("copper", "fiber", "dac", "virtual", name="link_type")
    user_role = postgresql.ENUM("viewer", "admin", name="user_role")
    audit_action = postgresql.ENUM("create", "update", "delete", name="audit_action")

    bind = op.get_bind()
    for enum in (
        ip_status, device_type, port_mode, port_admin_status,
        link_type, user_role, audit_action,
    ):
        enum.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # sites, rooms
    # ------------------------------------------------------------------
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("description", sa.Text()),
        sa.UniqueConstraint("site_id", "code", name="rooms_site_code_uniq"),
    )

    # ------------------------------------------------------------------
    # vlans
    # ------------------------------------------------------------------
    op.create_table(
        "vlans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vlan_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("color", sa.String(7)),
        sa.CheckConstraint("vlan_id BETWEEN 1 AND 4094", name="vlans_id_range"),
    )

    # ------------------------------------------------------------------
    # subnets — avec GiST pour exclure les chevauchements de CIDR
    # ------------------------------------------------------------------
    op.create_table(
        "subnets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cidr", postgresql.CIDR(), nullable=False),
        sa.Column("gateway", postgresql.INET()),
        sa.Column("vlan_id", sa.Integer(), sa.ForeignKey("vlans.id", ondelete="SET NULL")),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("dhcp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dhcp_range_start", postgresql.INET()),
        sa.Column("dhcp_range_end", postgresql.INET()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Exclusion de chevauchement : `&&` teste si deux CIDR se recouvrent.
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap "
        "EXCLUDE USING gist (cidr inet_ops WITH &&);"
    )

    # ------------------------------------------------------------------
    # devices, switches, ports, port_vlan
    # ------------------------------------------------------------------
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", postgresql.ENUM(name="device_type", create_type=False), nullable=False),
        sa.Column("vendor", sa.String(100)),
        sa.Column("model", sa.String(100)),
        sa.Column("serial", sa.String(100)),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id", ondelete="SET NULL")),
        sa.Column("description", sa.Text()),
    )

    op.create_table(
        "switches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("vendor", sa.String(50)),
        sa.Column("model", sa.String(100)),
        sa.Column("serial", sa.String(100)),
        sa.Column("management_ip", postgresql.INET()),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id", ondelete="RESTRICT")),
        sa.Column("rack_position", sa.String(20)),
        sa.Column("port_count", sa.Integer(), nullable=False),
        sa.Column("firmware_version", sa.String(50)),
        sa.Column("snmp_community", sa.String(100)),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("port_count > 0", name="switches_port_count_positive"),
    )

    # ips — créée avant ports pour que la FK ports.connected_ip_id puisse pointer dessus
    op.create_table(
        "ips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subnet_id", sa.Integer(), sa.ForeignKey("subnets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("address", postgresql.INET(), nullable=False, unique=True),
        sa.Column("hostname", sa.String(255)),
        sa.Column("mac", postgresql.MACADDR()),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL")),
        sa.Column("status", postgresql.ENUM(name="ip_status", create_type=False), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "ports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("switch_id", sa.Integer(), sa.ForeignKey("switches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(100)),
        sa.Column("mode", postgresql.ENUM(name="port_mode", create_type=False), nullable=False, server_default="access"),
        sa.Column("native_vlan_id", sa.Integer(), sa.ForeignKey("vlans.id", ondelete="SET NULL")),
        sa.Column("admin_status", postgresql.ENUM(name="port_admin_status", create_type=False), nullable=False, server_default="up"),
        sa.Column("connected_device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL")),
        sa.Column("connected_ip_id", sa.Integer(), sa.ForeignKey("ips.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        sa.UniqueConstraint("switch_id", "number", name="ports_switch_number_uniq"),
    )

    op.create_table(
        "port_vlan",
        sa.Column("port_id", sa.Integer(), sa.ForeignKey("ports.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("vlan_id", sa.Integer(), sa.ForeignKey("vlans.id", ondelete="CASCADE"), primary_key=True),
    )

    # ------------------------------------------------------------------
    # links — canoniques : port_a_id < port_b_id
    # ------------------------------------------------------------------
    op.create_table(
        "links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("port_a_id", sa.Integer(), sa.ForeignKey("ports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("port_b_id", sa.Integer(), sa.ForeignKey("ports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_type", postgresql.ENUM(name="link_type", create_type=False), nullable=False),
        sa.Column("speed_mbps", sa.Integer()),
        sa.Column("description", sa.Text()),
        sa.CheckConstraint("port_a_id <> port_b_id", name="links_distinct_ports"),
        sa.CheckConstraint("port_a_id < port_b_id", name="links_canonical_order"),
        sa.UniqueConstraint("port_a_id", "port_b_id", name="links_ports_uniq"),
    )

    # ------------------------------------------------------------------
    # users, sessions, audit_log
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entra_oid", postgresql.UUID(as_uuid=False), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("role", postgresql.ENUM(name="user_role", create_type=False), nullable=False, server_default="viewer"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
    )
    op.create_index("sessions_user_idx", "sessions", ["user_id"])
    op.create_index("sessions_expires_idx", "sessions", ["expires_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", postgresql.ENUM(name="audit_action", create_type=False), nullable=False),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer()),
        sa.Column("changes", postgresql.JSONB()),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("audit_log_entity_idx", "audit_log", ["entity", "entity_id"])
    op.create_index("audit_log_user_idx", "audit_log", ["user_id"])
    op.create_index("audit_log_created_at_idx", "audit_log", [sa.text("created_at DESC")])

    # ------------------------------------------------------------------
    # Trigger : une IP doit être contenue dans le CIDR de son subnet
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION netforge_check_ip_in_subnet()
        RETURNS trigger AS $$
        DECLARE
          subnet_cidr cidr;
        BEGIN
          SELECT cidr INTO subnet_cidr FROM subnets WHERE id = NEW.subnet_id;
          IF subnet_cidr IS NULL THEN
            RAISE EXCEPTION 'subnet % not found', NEW.subnet_id;
          END IF;
          IF NOT (NEW.address <<= subnet_cidr) THEN
            RAISE EXCEPTION 'IP % not in subnet %', NEW.address, subnet_cidr;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ips_check_in_subnet
        BEFORE INSERT OR UPDATE OF address, subnet_id ON ips
        FOR EACH ROW EXECUTE FUNCTION netforge_check_ip_in_subnet();
        """
    )

    # ------------------------------------------------------------------
    # Trigger générique updated_at = now()
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION netforge_touch_updated_at()
        RETURNS trigger AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for tbl in ("sites", "subnets", "switches", "ips"):
        op.execute(
            f"""
            CREATE TRIGGER {tbl}_touch_updated_at
            BEFORE UPDATE ON {tbl}
            FOR EACH ROW EXECUTE FUNCTION netforge_touch_updated_at();
            """
        )


def downgrade() -> None:
    # Ordre inverse de création (FKs obligent)
    for tbl in ("sites", "subnets", "switches", "ips"):
        op.execute(f"DROP TRIGGER IF EXISTS {tbl}_touch_updated_at ON {tbl};")
    op.execute("DROP FUNCTION IF EXISTS netforge_touch_updated_at;")

    op.execute("DROP TRIGGER IF EXISTS ips_check_in_subnet ON ips;")
    op.execute("DROP FUNCTION IF EXISTS netforge_check_ip_in_subnet;")

    op.drop_index("audit_log_created_at_idx", table_name="audit_log")
    op.drop_index("audit_log_user_idx", table_name="audit_log")
    op.drop_index("audit_log_entity_idx", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("sessions_expires_idx", table_name="sessions")
    op.drop_index("sessions_user_idx", table_name="sessions")
    op.drop_table("sessions")

    op.drop_table("users")
    op.drop_table("links")
    op.drop_table("port_vlan")
    op.drop_table("ports")
    op.drop_table("ips")
    op.drop_table("switches")
    op.drop_table("devices")
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap;")
    op.drop_table("subnets")
    op.drop_table("vlans")
    op.drop_table("rooms")
    op.drop_table("sites")

    for enum_name in (
        "audit_action", "user_role", "link_type", "port_admin_status",
        "port_mode", "device_type", "ip_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name};")
