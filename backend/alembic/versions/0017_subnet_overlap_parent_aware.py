"""make the anti-overlap exclusion parent-aware so child subnets can exist

Revision ID: 0017
Revises: 0016_subnet_trigger_descendants
Create Date: 2026-07-28

The GiST exclusions from migration 0010 use `cidr inet_ops WITH &&`, and
`&&` ("overlaps") is also true for strict containment. So inserting a child
subnet strictly contained in its parent — the exact relationship the
`parent_subnet_id` hierarchy (migrations 0010/0015/0016 and
`services/subnets.py::_validate_parent`) requires — always collided with the
parent row and bounced with 409 SUBNET_OVERLAP. Hierarchical IPAM was
unusable on a real PostgreSQL.

Fix, in two coordinated moves:

1. Scope the GiST exclusions to ROOT subnets only. Both constraints are
   recreated with `parent_subnet_id IS NULL` added to their partial WHERE:
     - `subnets_no_overlap_global` — roots in the global VRF.
     - `subnets_no_overlap_vrf`    — roots inside one VRF.
   Root-vs-root overlap keeps the exact same concurrency-safe DB guarantee
   as before; child rows simply stop participating.

2. Extend the `subnets_validate_parent()` trigger (v2 from 0016 → v3) with
   the check the exclusion no longer performs for children: a child must not
   overlap any SIBLING (same `parent_subnet_id`, different id,
   `cidr && NEW.cidr`). The violation raises SQLSTATE 23P01
   (exclusion_violation) with constraint name `subnets_no_overlap_siblings`
   in both the CONSTRAINT field and the message text, so
   `services/errors.py::catch_integrity_errors` maps it to the same stable
   409 SUBNET_OVERLAP the real exclusions produce.

Why this is sufficient (induction over the forest): roots don't overlap each
other (GiST), every child is strictly contained in its parent (trigger, 0015)
and doesn't overlap its siblings (this trigger). Two subnets in different
root subtrees can't overlap because their roots don't. Within one subtree,
walk both nodes up to the children of their lowest common ancestor: those two
are siblings, so either they don't overlap (then neither do the descendants
they contain) or the two nodes sit on the same chain — i.e. one is an
ancestor of the other, which is exactly the containment the hierarchy is
about.

Concurrency: unlike a GiST exclusion, a trigger's SELECT only sees committed
rows, so two transactions inserting overlapping siblings in parallel could
both pass the scan. The parent lookup therefore takes `FOR UPDATE` on the
parent row: concurrent child writes under the same parent serialise, and the
second transaction's sibling scan (READ COMMITTED — fresh snapshot per
statement) sees the first one's committed row.

Downgrade restores the 0010 constraints and the 0016 function body. It will
(correctly) FAIL while parent/child rows exist — a child overlaps its parent
by construction, which is precisely what the old constraints reject. Detach
or delete child subnets before downgrading.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016_subnet_trigger_descendants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# v3: adds the sibling anti-overlap check + FOR UPDATE on the parent row.
# The child-side containment/VRF checks and the parent-side descendant guard
# are carried over from 0016 unchanged.
_FUNCTION_V3 = """
CREATE OR REPLACE FUNCTION subnets_validate_parent() RETURNS trigger AS $$
DECLARE
    parent_cidr cidr;
    parent_vrf  integer;
    sibling     RECORD;
    bad_child   RECORD;
BEGIN
    -- ---- Child side: this row points at a parent. ----
    IF NEW.parent_subnet_id IS NOT NULL THEN
        IF NEW.parent_subnet_id = NEW.id THEN
            RAISE EXCEPTION 'subnet % cannot be its own parent', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;

        -- FOR UPDATE serialises concurrent child writes under the same
        -- parent. Without it, two transactions inserting overlapping
        -- siblings in parallel would each scan a snapshot missing the
        -- other row and both commit — the GiST exclusion this replaces
        -- for child rows was concurrency-safe, so the trigger must be too.
        SELECT cidr, vrf_id INTO parent_cidr, parent_vrf
            FROM subnets WHERE id = NEW.parent_subnet_id
            FOR UPDATE;

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

        -- Sibling anti-overlap. This replaces the GiST exclusion for child
        -- rows (migration 0017 scoped the exclusions to roots only). Same
        -- SQLSTATE (23P01) and a recognisable constraint name so the
        -- service layer maps it to the same 409 SUBNET_OVERLAP.
        SELECT id, cidr INTO sibling
            FROM subnets
            WHERE parent_subnet_id = NEW.parent_subnet_id
              AND id IS DISTINCT FROM NEW.id
              AND cidr && NEW.cidr
            LIMIT 1;

        IF FOUND THEN
            RAISE EXCEPTION
                'cidr % conflicts with sibling subnet % (%) under parent % — violates exclusion constraint "subnets_no_overlap_siblings"',
                NEW.cidr, sibling.id, sibling.cidr, NEW.parent_subnet_id
                USING ERRCODE = 'exclusion_violation',
                      CONSTRAINT = 'subnets_no_overlap_siblings';
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

# The 0016 body, for downgrade.
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


def upgrade() -> None:
    # 1. Scope both GiST exclusions to root subnets. Recreating with a
    # strictly weaker predicate always succeeds on data the old constraints
    # accepted.
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap_global;")
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap_vrf;")
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap_global "
        "EXCLUDE USING gist (cidr inet_ops WITH &&) "
        "WHERE (vrf_id IS NULL AND parent_subnet_id IS NULL);"
    )
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap_vrf "
        "EXCLUDE USING gist (vrf_id WITH =, cidr inet_ops WITH &&) "
        "WHERE (vrf_id IS NOT NULL AND parent_subnet_id IS NULL);"
    )

    # 2. Child rows get their anti-overlap from the trigger instead
    # (sibling scan — see module docstring for the induction argument).
    op.execute(_FUNCTION_V3)


def downgrade() -> None:
    op.execute(_FUNCTION_V2)
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap_vrf;")
    op.execute("ALTER TABLE subnets DROP CONSTRAINT IF EXISTS subnets_no_overlap_global;")
    # NOTE: these fail while parent/child rows exist — a child overlaps its
    # parent by construction. Detach or delete children before downgrading.
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap_global "
        "EXCLUDE USING gist (cidr inet_ops WITH &&) "
        "WHERE (vrf_id IS NULL);"
    )
    op.execute(
        "ALTER TABLE subnets "
        "ADD CONSTRAINT subnets_no_overlap_vrf "
        "EXCLUDE USING gist (vrf_id WITH =, cidr inet_ops WITH &&) "
        "WHERE (vrf_id IS NOT NULL);"
    )
