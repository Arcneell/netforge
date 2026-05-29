"""also validate descendants on parent-side subnet updates

Revision ID: 0016_subnet_trigger_descendants
Revises: 0015_subnet_parent_containment
Create Date: 2026-05-29

Migration 0015 only validated the *child* side: it ran when the row being
written pointed at a parent. But the trigger also fires on `UPDATE OF cidr,
vrf_id`, and a direct SQL edit that shrinks a parent's CIDR or moves it to
another VRF would commit even though its existing children are no longer
strictly contained / no longer share the VRF — the exact bypass the trigger
is meant to close.

Replace the function so it additionally rejects any INSERT/UPDATE that would
strand a child of the row being written. (A no-op on INSERT — nothing
references a brand-new id yet.)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_subnet_trigger_descendants"
down_revision: str | None = "0015_subnet_parent_containment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FUNCTION_V2 = """
CREATE OR REPLACE FUNCTION subnets_validate_parent() RETURNS trigger AS $$
DECLARE
    parent_cidr cidr;
    parent_vrf  integer;
    bad_child   RECORD;
BEGIN
    -- ---- Child side: this row points at a parent. ----
    IF NEW.parent_subnet_id IS NOT NULL THEN
        IF NEW.parent_subnet_id = NEW.id THEN
            RAISE EXCEPTION 'subnet % cannot be its own parent', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;

        SELECT cidr, vrf_id INTO parent_cidr, parent_vrf
            FROM subnets WHERE id = NEW.parent_subnet_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'parent subnet % does not exist', NEW.parent_subnet_id
                USING ERRCODE = 'foreign_key_violation';
        END IF;

        IF parent_vrf IS DISTINCT FROM NEW.vrf_id THEN
            RAISE EXCEPTION 'parent and child subnet must live in the same VRF'
                USING ERRCODE = 'check_violation';
        END IF;

        -- `<<` is "strictly contained by".
        IF NOT (NEW.cidr << parent_cidr) THEN
            RAISE EXCEPTION 'child % is not strictly contained in parent %',
                NEW.cidr, parent_cidr
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    -- ---- Parent side: this row may have children that a cidr/vrf change
    -- would strand. No-op on INSERT (nothing references a brand-new id yet). ----
    SELECT id, cidr, vrf_id INTO bad_child
        FROM subnets
        WHERE parent_subnet_id = NEW.id
          AND (NOT (cidr << NEW.cidr) OR vrf_id IS DISTINCT FROM NEW.vrf_id)
        LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION
            'updating subnet % would strand child % (cidr %, vrf %): no longer contained / same VRF',
            NEW.id, bad_child.id, bad_child.cidr, bad_child.vrf_id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# The original (child-side only) body, for downgrade.
_FUNCTION_V1 = """
CREATE OR REPLACE FUNCTION subnets_validate_parent() RETURNS trigger AS $$
DECLARE
    parent_cidr cidr;
    parent_vrf  integer;
BEGIN
    IF NEW.parent_subnet_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.parent_subnet_id = NEW.id THEN
        RAISE EXCEPTION 'subnet % cannot be its own parent', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT cidr, vrf_id INTO parent_cidr, parent_vrf
        FROM subnets WHERE id = NEW.parent_subnet_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'parent subnet % does not exist', NEW.parent_subnet_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF parent_vrf IS DISTINCT FROM NEW.vrf_id THEN
        RAISE EXCEPTION 'parent and child subnet must live in the same VRF'
            USING ERRCODE = 'check_violation';
    END IF;

    IF NOT (NEW.cidr << parent_cidr) THEN
        RAISE EXCEPTION 'child % is not strictly contained in parent %',
            NEW.cidr, parent_cidr
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_FUNCTION_V2)


def downgrade() -> None:
    op.execute(_FUNCTION_V1)
