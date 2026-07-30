"""ips_check_in_subnet trigger: raise with a mapped SQLSTATE

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-29

`netforge_check_ip_in_subnet()` (migration 0001) uses plain `RAISE
EXCEPTION 'IP % not in subnet %', ...` with no `USING ERRCODE`. Postgres
defaults an unqualified `RAISE EXCEPTION` to SQLSTATE `P0001`
("raise_exception"), which asyncpg surfaces as `RaiseError` — a subclass
of `PostgresError`, NOT of `IntegrityConstraintViolationError`. SQLAlchemy
only translates the latter into `sqlalchemy.exc.IntegrityError`
(`AsyncAdapt_asyncpg_dbapi._asyncpg_error_translate`), so the trigger's
exception blew straight past every `catch_integrity_errors()` in
`app/services/errors.py` (which only catches `IntegrityError`) and
surfaced as an unhandled 500 instead of a clean 409.

Fix: re-raise with `USING ERRCODE = 'check_violation'` (SQLSTATE 23514,
class 23 = integrity constraint violation). asyncpg maps that to
`CheckViolationError`, a subclass of `IntegrityConstraintViolationError`,
so SQLAlchemy now raises `IntegrityError` and `catch_integrity_errors()`
catches it — falling back to the generic `INTEGRITY_VIOLATION` 409 since
the message carries no named constraint for `_match_constraint` to key
on. Same function body (same trigger, same subnet lookup), only the
RAISE clause changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION netforge_check_ip_in_subnet()
        RETURNS trigger AS $$
        DECLARE
          subnet_cidr cidr;
        BEGIN
          SELECT cidr INTO subnet_cidr FROM subnets WHERE id = NEW.subnet_id;
          IF subnet_cidr IS NULL THEN
            RAISE EXCEPTION 'subnet % not found', NEW.subnet_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF NOT (NEW.address <<= subnet_cidr) THEN
            RAISE EXCEPTION 'IP % not in subnet %', NEW.address, subnet_cidr
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    # Restore the original body (no ERRCODE) exactly as created in 0001.
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
