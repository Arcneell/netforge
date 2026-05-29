"""enforce subnet parent/child containment at the database level

Revision ID: 0015_subnet_parent_containment
Revises: 0014_ai_draft_error_code
Create Date: 2026-05-29

The service layer (`app/services/subnets.py::_validate_parent`) already checks
that a child subnet is strictly contained in its parent and shares the same
VRF. But that check is app-side only: a CSV bulk path, a direct SQL fix-up, or
a future endpoint could insert a child that violates the hierarchy, and two
concurrent writes could interleave between the read and the insert.

This trigger makes the invariant authoritative in PostgreSQL — the same way
the GiST exclusion constraint already guarantees no-overlap. It mirrors the
service rules exactly:

  1. a subnet cannot be its own parent,
  2. parent and child must share the same VRF (NULL == NULL),
  3. the child CIDR must be STRICTLY contained in the parent CIDR
     (the `<<` operator: contained-by-and-not-equal).

The service-layer check stays — it returns a friendly 422 before we ever hit
the DB. The trigger is the backstop for everything that bypasses the service.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_subnet_parent_containment"
down_revision: str | None = "0014_ai_draft_error_code"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATE_FUNCTION = """
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

    -- `<<` is "strictly contained by": child must be inside parent and not
    -- equal to it, matching IPv4Network.subnet_of(...) and child != parent.
    IF NOT (NEW.cidr << parent_cidr) THEN
        RAISE EXCEPTION 'child % is not strictly contained in parent %',
            NEW.cidr, parent_cidr
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# BEFORE INSERT always; on UPDATE only when one of the three relevant columns
# changes, so unrelated updates (e.g. description) skip the parent lookup.
_CREATE_TRIGGER = """
CREATE TRIGGER subnets_validate_parent_trg
    BEFORE INSERT OR UPDATE OF cidr, vrf_id, parent_subnet_id ON subnets
    FOR EACH ROW EXECUTE FUNCTION subnets_validate_parent();
"""


def upgrade() -> None:
    op.execute(_CREATE_FUNCTION)
    op.execute(_CREATE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS subnets_validate_parent_trg ON subnets;")
    op.execute("DROP FUNCTION IF EXISTS subnets_validate_parent();")
