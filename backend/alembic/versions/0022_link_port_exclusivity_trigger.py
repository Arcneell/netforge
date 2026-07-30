"""enforce "one physical port, at most one link" at the database level

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-29

`services/links.py::create_link` refuses to attach a second link to a port
that's already an endpoint of another one — a physical port can only ever
realise one cable. That check is a plain `SELECT` run BEFORE the `INSERT`,
with no lock: two concurrent requests wiring the same port to two different
peers can both pass the SELECT before either commits, and both then insert.
The existing `UniqueConstraint(port_a_id, port_b_id)` (`links_ports_uniq`)
only rejects the exact same PAIR reinserted — it does nothing for a port
that shows up once as `port_a_id` in one row and once as `port_b_id` in
another, which is exactly the cross-side race described in the
`create_link` docstring ("long-term fix is two partial unique indexes on
port_a_id / port_b_id"). Two plain per-column unique indexes would still
miss that cross-side case (unique(port_a_id) alone doesn't stop a port from
also appearing as somebody else's port_b_id), so this migration uses a
trigger instead — the same pattern already used for the subnet hierarchy
invariants (migrations 0015/0016/0017) where a single-column/GiST
constraint can't express the rule.

The trigger:
  1. Locks the two `ports` rows referenced by `NEW` (in ascending id order,
     matching the deadlock-avoidance convention `services/links.py` already
     uses for the canonical `port_a_id < port_b_id` ordering) with
     `SELECT ... FOR UPDATE`. Two concurrent transactions that both touch an
     overlapping port serialise on that lock instead of both racing the
     SELECT below to completion.
  2. Re-checks (now serialised, so this sees the other transaction's
     committed result once its lock is released) whether any OTHER link row
     already references either port, on either side.
  3. Raises with SQLSTATE `unique_violation` and a constraint name
     (`links_port_exclusivity`) in the message, so `services/links.py` can
     recognise it and map it to the same 400 `PORT_ALREADY_LINKED` the
     non-racing pre-check already returns — `catch_integrity_errors()`
     (services/errors.py) still gets a generic 409 fallback for anything
     that isn't caught explicitly first.

Fires on INSERT and on UPDATE OF the two port columns — `update_link`
never touches them today (endpoints are immutable after creation, per its
docstring), but the guard shouldn't silently stop applying if that changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION links_validate_port_exclusivity() RETURNS trigger AS $$
DECLARE
    clash RECORD;
BEGIN
    -- Lock the two port rows in ascending id order so two concurrent
    -- inserts/updates that share a port serialise instead of both racing
    -- the SELECT below to completion (mirrors subnets_validate_parent's
    -- FOR UPDATE, migration 0017).
    PERFORM 1 FROM ports
        WHERE id IN (NEW.port_a_id, NEW.port_b_id)
        ORDER BY id
        FOR UPDATE;

    SELECT id INTO clash
        FROM links
        WHERE id IS DISTINCT FROM NEW.id
          AND (port_a_id IN (NEW.port_a_id, NEW.port_b_id)
               OR port_b_id IN (NEW.port_a_id, NEW.port_b_id))
        LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION
            'port % or % is already an endpoint of link % — violates unique constraint "links_port_exclusivity"',
            NEW.port_a_id, NEW.port_b_id, clash.id
            USING ERRCODE = 'unique_violation',
                  CONSTRAINT = 'links_port_exclusivity';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_CREATE_TRIGGER = """
CREATE TRIGGER links_validate_port_exclusivity_trg
    BEFORE INSERT OR UPDATE OF port_a_id, port_b_id ON links
    FOR EACH ROW EXECUTE FUNCTION links_validate_port_exclusivity();
"""


def upgrade() -> None:
    op.execute(_CREATE_FUNCTION)
    op.execute(_CREATE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS links_validate_port_exclusivity_trg ON links;")
    op.execute("DROP FUNCTION IF EXISTS links_validate_port_exclusivity();")
