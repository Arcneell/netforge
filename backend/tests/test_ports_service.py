"""Service-layer tests for ports — invariants enforced outside the schema.

Schema-level checks (field types, ranges) live in `test_schemas*`. This file
covers the cross-row invariants that need a DB lookup, mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.port import Port
from app.schemas.port import PortUpdate
from app.services import ports as service


def _mock_db_for_update(port: Port, clash_present: bool) -> AsyncMock:
    """db.get → port; db.execute → row(vlan_id) if clash_present, else None."""
    clash_result = MagicMock()
    clash_result.scalar_one_or_none = MagicMock(
        return_value=1 if clash_present else None
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=port)
    db.execute = AsyncMock(return_value=clash_result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_update_port_rejects_native_vlan_already_tagged() -> None:
    """`add_tagged_vlan` already refuses to tag the native VLAN; mirror the
    invariant on the update path. Without this guard an admin could PUT
    `native_vlan_id` to a VLAN already in the port's tagged set, producing
    a port that simultaneously has the same VLAN as native AND tagged —
    CSV exports, the topology graph, and the AI snapshot all carry that
    inconsistency downstream.
    """
    port = Port(id=10, switch_id=1, number=2, native_vlan_id=None)
    db = _mock_db_for_update(port, clash_present=True)

    with pytest.raises(HTTPException) as exc:
        await service.update_port(db, 10, PortUpdate(native_vlan_id=42))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "VLAN_IS_NATIVE"
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_update_port_allows_native_vlan_not_in_tagged_set() -> None:
    """Happy path: the new native VLAN is not already tagged, so the
    update goes through and the value lands on the port row.
    """
    port = Port(id=10, switch_id=1, number=2, native_vlan_id=None)
    db = _mock_db_for_update(port, clash_present=False)

    out = await service.update_port(db, 10, PortUpdate(native_vlan_id=42))
    assert out is port
    assert port.native_vlan_id == 42
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_port_keeps_existing_native_vlan_when_payload_omits_it() -> None:
    """`exclude_unset` semantics: a PATCH that doesn't mention
    native_vlan_id must NOT trigger the clash check (and must not touch
    the value on the port). Pins that we're inspecting the payload, not
    the resulting port.
    """
    port = Port(id=10, switch_id=1, number=2, native_vlan_id=7)
    db = _mock_db_for_update(port, clash_present=True)

    await service.update_port(db, 10, PortUpdate(label="uplink"))
    # No SELECT on PortVlan for the clash check — we only ran the get/commit.
    db.execute.assert_not_called()
    assert port.label == "uplink"
    assert port.native_vlan_id == 7
