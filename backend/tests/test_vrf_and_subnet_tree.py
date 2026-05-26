"""VRF + subnet-hierarchy unit tests — pure-Python, no DB.

The DB-side bits (the per-VRF GiST exclusion that lets two CIDRs coexist in
different VRFs) need a real Postgres and are covered by the integration
suite. Here we exercise the service-layer guards:
  - parent must exist, live in the same VRF, contain the child CIDR;
  - a subnet cannot be its own parent;
  - the tree builder gathers depth-first roots and orders siblings by CIDR.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.subnet import Subnet
from app.services import subnets as service


def _subnet(
    *,
    id: int,
    cidr: str,
    vrf_id: int | None = None,
    parent_subnet_id: int | None = None,
    site_id: int = 1,
) -> Subnet:
    return Subnet(
        id=id,
        cidr=cidr,
        site_id=site_id,
        vrf_id=vrf_id,
        parent_subnet_id=parent_subnet_id,
        dhcp_enabled=False,
    )


# --- _validate_parent ------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_parent_noop_when_no_parent() -> None:
    db = AsyncMock()
    # Should not call db.get and must not raise.
    await service._validate_parent(
        db, cidr="10.0.0.0/24", vrf_id=None, parent_subnet_id=None
    )
    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_validate_parent_rejects_self_reference() -> None:
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await service._validate_parent(
            db,
            cidr="10.0.0.0/24",
            vrf_id=None,
            parent_subnet_id=42,
            self_id=42,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "INVALID_PARENT"


@pytest.mark.asyncio
async def test_validate_parent_rejects_missing_parent() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service._validate_parent(
            db, cidr="10.0.0.0/24", vrf_id=None, parent_subnet_id=99
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_parent_rejects_vrf_mismatch() -> None:
    parent = _subnet(id=1, cidr="10.0.0.0/16", vrf_id=2)
    db = AsyncMock()
    db.get = AsyncMock(return_value=parent)
    with pytest.raises(HTTPException) as exc:
        await service._validate_parent(
            db, cidr="10.0.1.0/24", vrf_id=3, parent_subnet_id=1
        )
    assert exc.value.detail["error"]["code"] == "INVALID_PARENT"


@pytest.mark.asyncio
async def test_validate_parent_rejects_non_contained_child() -> None:
    parent = _subnet(id=1, cidr="10.0.0.0/24", vrf_id=None)
    db = AsyncMock()
    db.get = AsyncMock(return_value=parent)
    with pytest.raises(HTTPException) as exc:
        await service._validate_parent(
            db, cidr="192.168.0.0/24", vrf_id=None, parent_subnet_id=1
        )
    assert exc.value.detail["error"]["code"] == "INVALID_PARENT"


@pytest.mark.asyncio
async def test_validate_parent_rejects_identical_cidr() -> None:
    """Containment is *strict* — a child must be smaller than its parent."""
    parent = _subnet(id=1, cidr="10.0.0.0/24", vrf_id=None)
    db = AsyncMock()
    db.get = AsyncMock(return_value=parent)
    with pytest.raises(HTTPException):
        await service._validate_parent(
            db, cidr="10.0.0.0/24", vrf_id=None, parent_subnet_id=1
        )


@pytest.mark.asyncio
async def test_validate_parent_accepts_strictly_contained_child() -> None:
    parent = _subnet(id=1, cidr="10.0.0.0/16", vrf_id=None)
    db = AsyncMock()
    db.get = AsyncMock(return_value=parent)
    # Should not raise.
    await service._validate_parent(
        db, cidr="10.0.5.0/24", vrf_id=None, parent_subnet_id=1
    )


# --- build_subnet_tree -----------------------------------------------------


def _mock_db_with_subnets(
    subnets: list[Subnet],
    ip_counts: dict[int, int] | None = None,
    boundary_rows: list[tuple[int, str]] | None = None,
) -> AsyncMock:
    """Mock the SELECTs `build_subnet_tree` issues:
      1. Subnet rows in scope.
      2. Aggregated COUNT(*) GROUP BY subnet_id from `_per_subnet_used_counts`.
      3. Optional boundary-row subtract query — only fires when at least one
         subnet in the batch has prefixlen < 31 (i.e. has a network /
         broadcast address worth excluding).

    Tests that don't care about counts can omit `ip_counts` and the second
    call resolves to an empty mapping; the boundary call resolves to an
    empty list too. Mirrors the production query sequence so test
    coverage matches the real wire shape."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=subnets)
    subnet_result = MagicMock()
    subnet_result.scalars = MagicMock(return_value=scalars)

    counts_result = MagicMock()
    counts_result.all = MagicMock(return_value=list((ip_counts or {}).items()))

    boundary_result = MagicMock()
    boundary_result.all = MagicMock(return_value=list(boundary_rows or []))

    db = AsyncMock()
    # Order matches `build_subnet_tree` → `_per_subnet_used_counts`:
    #   subnets → raw counts → boundary rows. Empty subnet scope skips
    #   the helper entirely (early return on no items).
    db.execute = AsyncMock(side_effect=[subnet_result, counts_result, boundary_result])
    return db


@pytest.mark.asyncio
async def test_tree_empty_when_no_subnets_in_scope() -> None:
    db = _mock_db_with_subnets([])
    assert await service.build_subnet_tree(db, vrf_id=None, auto_group_prefix=None) == []


# --- auto-group: synthetic /N supernets when no explicit parents exist ----


@pytest.mark.asyncio
async def test_auto_group_wraps_flat_roots_sharing_a_slash16() -> None:
    """Two flat /24 roots that share the same /16 supernet must be wrapped
    under a synthetic /16 parent so the tree view shows real hierarchy
    even on deployments that never set `parent_subnet_id`."""
    a = _subnet(id=1, cidr="10.10.10.0/24")
    b = _subnet(id=2, cidr="10.10.20.0/24")
    db = _mock_db_with_subnets([a, b])

    tree = await service.build_subnet_tree(db, vrf_id=None, auto_group_prefix=16)
    assert len(tree) == 1
    parent = tree[0]
    assert parent["cidr"] == "10.10.0.0/16"
    assert parent["synthetic"] is True
    assert parent["id"] < 0  # synthetic ids stay negative
    assert [c["id"] for c in parent["children"]] == [1, 2]


@pytest.mark.asyncio
async def test_auto_group_keeps_singletons_at_the_root() -> None:
    """A single subnet in a /16 has nothing to group with — wrapping it
    in a synthetic supernet would just add visual noise."""
    a = _subnet(id=1, cidr="10.10.10.0/24")
    db = _mock_db_with_subnets([a])

    tree = await service.build_subnet_tree(db, vrf_id=None, auto_group_prefix=16)
    assert len(tree) == 1
    assert tree[0]["id"] == 1
    assert tree[0].get("synthetic", False) is False


@pytest.mark.asyncio
async def test_auto_group_disabled_returns_flat_roots() -> None:
    a = _subnet(id=1, cidr="10.10.10.0/24")
    b = _subnet(id=2, cidr="10.10.20.0/24")
    db = _mock_db_with_subnets([a, b])

    tree = await service.build_subnet_tree(db, vrf_id=None, auto_group_prefix=None)
    assert [n["id"] for n in tree] == [1, 2]


@pytest.mark.asyncio
async def test_tree_groups_children_under_parent() -> None:
    root = _subnet(id=1, cidr="10.0.0.0/16")
    child_a = _subnet(id=2, cidr="10.0.1.0/24", parent_subnet_id=1)
    child_b = _subnet(id=3, cidr="10.0.2.0/24", parent_subnet_id=1)
    grandchild = _subnet(id=4, cidr="10.0.1.128/25", parent_subnet_id=2)
    db = _mock_db_with_subnets([root, child_a, child_b, grandchild])

    tree = await service.build_subnet_tree(db, vrf_id=None, auto_group_prefix=None)
    assert len(tree) == 1
    assert tree[0]["id"] == 1
    assert [c["id"] for c in tree[0]["children"]] == [2, 3]
    assert tree[0]["children"][0]["children"][0]["id"] == 4


@pytest.mark.asyncio
async def test_tree_promotes_orphaned_children_to_roots() -> None:
    """When a child's parent is outside the current scope (e.g. a deleted
    parent), the tree builder should still surface the child as a root —
    otherwise it'd disappear from the UI."""
    orphan = _subnet(id=5, cidr="10.0.3.0/24", parent_subnet_id=999)
    db = _mock_db_with_subnets([orphan])

    tree = await service.build_subnet_tree(db, vrf_id=None, auto_group_prefix=None)
    assert len(tree) == 1
    assert tree[0]["id"] == 5


@pytest.mark.asyncio
async def test_tree_sorts_siblings_by_cidr() -> None:
    root = _subnet(id=1, cidr="10.0.0.0/16")
    child_b = _subnet(id=2, cidr="10.0.5.0/24", parent_subnet_id=1)
    child_a = _subnet(id=3, cidr="10.0.1.0/24", parent_subnet_id=1)
    db = _mock_db_with_subnets([root, child_b, child_a])

    tree = await service.build_subnet_tree(db, vrf_id=None, auto_group_prefix=None)
    ordered = [c["cidr"] for c in tree[0]["children"]]
    assert ordered == ["10.0.1.0/24", "10.0.5.0/24"]


# --- _reject_vrf_move_with_children (Codex P1 on PR #64) -------------------


def _mock_db_with_children_query(children_rows: list) -> AsyncMock:
    """Mock returning `children_rows` for the SELECT inside
    `_reject_vrf_move_with_children` — query shape doesn't matter here."""
    children_result = MagicMock()
    children_result.all = MagicMock(return_value=children_rows)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=children_result)
    return db


@pytest.mark.asyncio
async def test_reject_vrf_move_when_subnet_has_children() -> None:
    """Moving a parent subnet to a new VRF while children still point to it
    would silently violate the same-VRF invariant on those children. The
    service must refuse the move with INVALID_PARENT."""
    from types import SimpleNamespace

    parent = _subnet(id=10, cidr="10.0.0.0/16", vrf_id=1)
    db = _mock_db_with_children_query(
        [SimpleNamespace(id=11, cidr="10.0.1.0/24"), SimpleNamespace(id=12, cidr="10.0.2.0/24")]
    )
    with pytest.raises(HTTPException) as exc:
        await service._reject_vrf_move_with_children(db, parent, new_vrf=2)
    assert exc.value.status_code == 400
    detail = exc.value.detail["error"]
    assert detail["code"] == "INVALID_PARENT"
    assert detail["details"]["child_ids"] == [11, 12]


@pytest.mark.asyncio
async def test_vrf_move_allowed_when_subnet_has_no_children() -> None:
    parent = _subnet(id=10, cidr="10.0.0.0/16", vrf_id=1)
    db = _mock_db_with_children_query([])
    # Should not raise.
    await service._reject_vrf_move_with_children(db, parent, new_vrf=2)
