"""ORM relationship cascade vs. FK `ondelete` consistency (Fix #1).

`Site.rooms` used to declare `cascade="all, delete-orphan"` while
`rooms.site_id` is `ON DELETE RESTRICT` at the DB level — the ORM would
try to delete every room when its site was deleted, racing (and
sometimes masking) the DB's own RESTRICT, and `services/sites.py::
delete_site` relies on the DB raising IntegrityError -> 409 to refuse
deleting a site that still has rooms.

These are pure introspection tests — no DB connection needed — so the
whole audited pattern (cascade must match the FK's ondelete; CASCADE FKs
should set `passive_deletes=True` so the ORM doesn't also try to delete
children Postgres will delete anyway) is pinned without touching
Postgres.
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect

from app.models.core import Room, Site
from app.models.port import Port, PortVlan
from app.models.subnet import Subnet
from app.models.switch import Switch


def _fk_ondelete(table, column: str) -> str | None:
    fks = table.columns[column].foreign_keys
    fk = next(iter(fks))
    return fk.ondelete


def test_site_rooms_relationship_has_no_delete_cascade() -> None:
    """`rooms.site_id` is ON DELETE RESTRICT — the ORM must not attempt to
    delete rooms itself; the DB has to be the one refusing the site
    delete so `delete_site` gets an IntegrityError to turn into a 409."""
    assert _fk_ondelete(Room.__table__, "site_id") == "RESTRICT"
    rel = sa_inspect(Site).relationships["rooms"]
    assert "delete" not in rel.cascade
    assert "delete-orphan" not in rel.cascade


def test_subnet_ips_cascade_matches_fk_cascade_and_is_passive() -> None:
    """`ips.subnet_id` is ON DELETE CASCADE — the ORM cascade may mirror
    that, but `passive_deletes=True` must be set so Postgres does the
    actual child-row deletion in one statement instead of the ORM issuing
    one DELETE per IP first."""
    assert _fk_ondelete(Subnet.__table__.metadata.tables["ips"], "subnet_id") == "CASCADE"
    rel = sa_inspect(Subnet).relationships["ips"]
    assert "delete-orphan" in rel.cascade
    assert rel.passive_deletes is True


def test_switch_ports_cascade_matches_fk_cascade_and_is_passive() -> None:
    assert _fk_ondelete(Port.__table__, "switch_id") == "CASCADE"
    rel = sa_inspect(Switch).relationships["ports"]
    assert "delete-orphan" in rel.cascade
    assert rel.passive_deletes is True


def test_port_tagged_vlans_cascade_matches_fk_cascade_and_is_passive() -> None:
    assert _fk_ondelete(PortVlan.__table__, "port_id") == "CASCADE"
    rel = sa_inspect(Port).relationships["tagged_vlans"]
    assert "delete-orphan" in rel.cascade
    assert rel.passive_deletes is True


def test_subnet_children_relationship_has_no_delete_cascade() -> None:
    """`subnets.parent_subnet_id` is ON DELETE SET NULL — a parent delete
    must NOT cascade-delete its children (they become orphaned root
    subnets instead), so the relationship only carries `save-update`."""
    assert _fk_ondelete(Subnet.__table__, "parent_subnet_id") == "SET NULL"
    rel = sa_inspect(Subnet).relationships["children"]
    assert "delete" not in rel.cascade
    assert "delete-orphan" not in rel.cascade
