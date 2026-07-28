"""DB-level tests for the subnet hierarchy invariants — real Postgres.

Covers what the unit suite structurally cannot: the GiST exclusion
constraints (scoped to root subnets by migration 0017) and the
`subnets_validate_parent()` trigger (containment 0015, descendant guard
0016, sibling anti-overlap 0017). Rows are written through the ORM
directly — routing through the service layer would let its app-side
pre-checks mask a hole in the DB backstop, which is the thing under test.

The headline case is `test_child_strictly_contained_in_parent_is_accepted`:
before 0017 the `&&` exclusion also fired on strict containment, so every
legitimate parent/child pair bounced with SUBNET_OVERLAP and hierarchical
IPAM was unusable on a real PostgreSQL.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subnet import Subnet
from app.models.vrf import Vrf
from app.services.errors import match_constraint

from .conftest import INTEGRATION_DB_URL_VAR, integration_db_url

if not integration_db_url():
    pytest.skip(
        f"{INTEGRATION_DB_URL_VAR} is not set — skipping Postgres integration tests",
        allow_module_level=True,
    )


async def _add_subnet(
    db: AsyncSession,
    *,
    cidr: str,
    site_id: int,
    vrf_id: int | None = None,
    parent_subnet_id: int | None = None,
) -> Subnet:
    subnet = Subnet(
        cidr=cidr,
        site_id=site_id,
        vrf_id=vrf_id,
        parent_subnet_id=parent_subnet_id,
        dhcp_enabled=False,
    )
    db.add(subnet)
    await db.commit()
    await db.refresh(subnet)
    return subnet


async def _add_vrf(db: AsyncSession, name: str) -> Vrf:
    vrf = Vrf(name=name)
    db.add(vrf)
    await db.commit()
    await db.refresh(vrf)
    return vrf


# --- The bug: legitimate parent/child pairs must be storable ---------------


async def test_child_strictly_contained_in_parent_is_accepted(
    db: AsyncSession, site_id: int
) -> None:
    """Regression for the `&&`-also-matches-containment bug: a child
    strictly contained in its parent (same scope, global VRF here) must
    NOT trip the exclusion. Before 0017 this raised SUBNET_OVERLAP."""
    parent = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    child = await _add_subnet(
        db, cidr="10.0.1.0/24", site_id=site_id, parent_subnet_id=parent.id
    )
    # Deeper nesting works too (grandchild contained in both ancestors).
    grandchild = await _add_subnet(
        db, cidr="10.0.1.128/25", site_id=site_id, parent_subnet_id=child.id
    )
    assert grandchild.parent_subnet_id == child.id


async def test_child_contained_in_parent_same_vrf_is_accepted(
    db: AsyncSession, site_id: int
) -> None:
    """Same regression inside a named VRF — exercises the vrf-scoped
    exclusion (`subnets_no_overlap_vrf`) instead of the global one."""
    vrf = await _add_vrf(db, "blue")
    parent = await _add_subnet(db, cidr="172.16.0.0/12", site_id=site_id, vrf_id=vrf.id)
    child = await _add_subnet(
        db,
        cidr="172.16.10.0/24",
        site_id=site_id,
        vrf_id=vrf.id,
        parent_subnet_id=parent.id,
    )
    assert child.vrf_id == vrf.id


# --- Trigger: containment + sibling anti-overlap ----------------------------


async def test_child_outside_parent_is_rejected(
    db: AsyncSession, site_id: int
) -> None:
    parent = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    with pytest.raises(IntegrityError) as exc:
        await _add_subnet(
            db, cidr="192.168.0.0/24", site_id=site_id, parent_subnet_id=parent.id
        )
    assert "not strictly contained" in str(exc.value.orig)


async def test_child_equal_to_parent_cidr_is_rejected(
    db: AsyncSession, site_id: int
) -> None:
    """Containment is strict — a child identical to its parent is refused."""
    parent = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    with pytest.raises(IntegrityError):
        await _add_subnet(
            db, cidr="10.0.0.0/16", site_id=site_id, parent_subnet_id=parent.id
        )


async def test_overlapping_siblings_are_rejected_as_subnet_overlap(
    db: AsyncSession, site_id: int
) -> None:
    """Two children of the same parent may not overlap. The trigger raises
    23P01 with `subnets_no_overlap_siblings` in the message, which the
    service error mapper must translate to the same stable SUBNET_OVERLAP
    code the GiST exclusions produce."""
    parent = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    await _add_subnet(
        db, cidr="10.0.1.0/24", site_id=site_id, parent_subnet_id=parent.id
    )
    with pytest.raises(IntegrityError) as exc:
        await _add_subnet(
            db, cidr="10.0.1.128/25", site_id=site_id, parent_subnet_id=parent.id
        )
    message = str(exc.value.orig)
    assert "subnets_no_overlap_siblings" in message
    mapped = match_constraint(message)
    assert mapped is not None
    assert mapped[0] == "SUBNET_OVERLAP"


async def test_non_overlapping_siblings_are_accepted(
    db: AsyncSession, site_id: int
) -> None:
    parent = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    await _add_subnet(
        db, cidr="10.0.1.0/24", site_id=site_id, parent_subnet_id=parent.id
    )
    sibling = await _add_subnet(
        db, cidr="10.0.2.0/24", site_id=site_id, parent_subnet_id=parent.id
    )
    assert sibling.id is not None


# --- GiST exclusions: roots still get the concurrency-safe guarantee --------


async def test_overlapping_roots_same_scope_are_rejected(
    db: AsyncSession, site_id: int
) -> None:
    """Root-vs-root overlap in the global VRF still trips the exclusion —
    scoping it with `parent_subnet_id IS NULL` must not weaken it."""
    await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    with pytest.raises(IntegrityError) as exc:
        await _add_subnet(db, cidr="10.0.42.0/24", site_id=site_id)
    message = str(exc.value.orig)
    assert "subnets_no_overlap_global" in message
    mapped = match_constraint(message)
    assert mapped is not None
    assert mapped[0] == "SUBNET_OVERLAP"


async def test_overlapping_roots_same_vrf_are_rejected(
    db: AsyncSession, site_id: int
) -> None:
    vrf = await _add_vrf(db, "green")
    await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id, vrf_id=vrf.id)
    with pytest.raises(IntegrityError) as exc:
        await _add_subnet(db, cidr="10.0.0.0/24", site_id=site_id, vrf_id=vrf.id)
    assert "subnets_no_overlap_vrf" in str(exc.value.orig)


async def test_same_cidr_in_two_vrfs_is_accepted(
    db: AsyncSession, site_id: int
) -> None:
    """VRFs are isolated routing scopes — identical CIDRs may coexist."""
    vrf_a = await _add_vrf(db, "cust-a")
    vrf_b = await _add_vrf(db, "cust-b")
    await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id, vrf_id=vrf_a.id)
    twin = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id, vrf_id=vrf_b.id)
    assert twin.id is not None


async def test_detaching_child_that_overlaps_a_root_is_rejected(
    db: AsyncSession, site_id: int
) -> None:
    """Clearing `parent_subnet_id` promotes the row into the root scope,
    where the exclusion applies again — a child overlapping its (former)
    parent may not simply be detached."""
    parent = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    child = await _add_subnet(
        db, cidr="10.0.1.0/24", site_id=site_id, parent_subnet_id=parent.id
    )
    child.parent_subnet_id = None
    with pytest.raises(IntegrityError) as exc:
        await db.commit()
    await db.rollback()
    assert "subnets_no_overlap_global" in str(exc.value.orig)


# --- Trigger: parent-side updates (0016) and self-reference ------------------


async def test_parent_cidr_shrink_stranding_a_child_is_rejected(
    db: AsyncSession, site_id: int
) -> None:
    """Shrinking a parent's CIDR below an existing child must be refused by
    the parent-side branch of the trigger (migration 0016)."""
    parent = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    await _add_subnet(
        db, cidr="10.0.200.0/24", site_id=site_id, parent_subnet_id=parent.id
    )
    parent.cidr = "10.0.0.0/24"
    with pytest.raises(IntegrityError) as exc:
        await db.commit()
    await db.rollback()
    assert "would strand child" in str(exc.value.orig)


async def test_subnet_cannot_become_its_own_parent(
    db: AsyncSession, site_id: int
) -> None:
    subnet = await _add_subnet(db, cidr="10.0.0.0/16", site_id=site_id)
    subnet.parent_subnet_id = subnet.id
    with pytest.raises(IntegrityError) as exc:
        await db.commit()
    await db.rollback()
    assert "cannot be its own parent" in str(exc.value.orig)
