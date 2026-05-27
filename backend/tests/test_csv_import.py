"""Tests for the CSV import driver — parsing, validation, dispatch.

The DB layer is mocked because we focus on:
  - CSV parsing (delimiter, BOM, whitespace)
  - Per-row Pydantic validation
  - Report shape (parsed_rows, ok_rows, error_rows, applied)
  - Dry-run always rolls back

End-to-end upsert behaviour requires a real Postgres and is deferred to the
testcontainers-based suite (same gating as the audit listener tests).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.schemas.imports import ImportReport
from app.services import csv_import as service


def _fresh_db() -> AsyncMock:
    """A mock async session whose execute/flush/commit/rollback are no-ops."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = lambda *a, **kw: None
    return db


def _csv(*lines: str) -> bytes:
    # Excel-style export — UTF-8 BOM + ; separator
    return ("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8")


# --- CSV parser ----------------------------------------------------------- #


def test_parse_csv_strips_bom_and_whitespace() -> None:
    rows = service._parse_csv(_csv("code;name", "  HQ  ;  Headquarters  "))
    assert rows == [{"code": "HQ", "name": "Headquarters"}]


def test_parse_csv_handles_empty_payload() -> None:
    assert service._parse_csv(b"") == []


# --- Sites import: happy path + validation error ------------------------- #


@pytest.mark.asyncio
async def test_import_sites_ok_path_yields_applied_report() -> None:
    db = _fresh_db()
    # Persist function never finds an existing row → always inserts.
    scalar_result = AsyncMock()
    scalar_result.scalar_one_or_none = lambda: None
    db.execute = AsyncMock(return_value=scalar_result)

    report = await service.run_import(
        db, "sites", _csv("code;name;address", "HQ;Paris HQ;", "DC1;Datacenter 1;"), dry_run=False
    )
    assert isinstance(report, ImportReport)
    assert report.parsed_rows == 2
    assert report.ok_rows == 2
    assert report.error_rows == []
    assert report.applied is True
    db.commit.assert_awaited_once()
    db.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_import_validation_error_aborts_without_db_writes() -> None:
    db = _fresh_db()
    # `code` has an invalid character — fails Pydantic, never reaches DB.
    report = await service.run_import(
        db, "sites", _csv("code;name", "Hôtel de Ville;X"), dry_run=False
    )
    assert report.applied is False
    assert report.ok_rows == 0
    assert len(report.error_rows) == 1
    assert report.error_rows[0].line == 2
    assert report.error_rows[0].column == "code"
    db.flush.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_import_dry_run_rolls_back_even_on_success() -> None:
    db = _fresh_db()
    scalar_result = AsyncMock()
    scalar_result.scalar_one_or_none = lambda: None
    db.execute = AsyncMock(return_value=scalar_result)

    report = await service.run_import(
        db, "sites", _csv("code;name", "HQ;Paris HQ"), dry_run=True
    )
    assert report.parsed_rows == 1
    assert report.ok_rows == 1
    assert report.error_rows == []
    assert report.applied is False
    db.rollback.assert_awaited_once()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_import_unknown_entity_raises_400() -> None:
    from fastapi import HTTPException

    db = _fresh_db()
    with pytest.raises(HTTPException) as exc:
        await service.run_import(db, "frobnicators", _csv("a;b"), dry_run=False)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "UNKNOWN_ENTITY"


# --- Row model validation ------------------------------------------------- #


def test_vlan_row_rejects_out_of_range_id() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        service._VlanRow(vlan_id=5000, name="X")


def test_subnet_row_canonicalises_cidr() -> None:
    row = service._SubnetRow(cidr="10.0.30.5/24", site_code="HQ")
    assert row.cidr == "10.0.30.0/24"


def test_ip_row_normalises_mac_dash_form() -> None:
    row = service._IpRow(
        address="10.0.30.42", status="assigned", mac="AA-BB-CC-DD-EE-FF"
    )
    assert row.mac == "aa:bb:cc:dd:ee:ff"


def test_ip_row_normalises_mac_cisco_form() -> None:
    row = service._IpRow(
        address="10.0.30.42", status="assigned", mac="aabb.ccdd.eeff"
    )
    assert row.mac == "aa:bb:cc:dd:ee:ff"


def test_port_row_parses_trunk_vlans_csv_list() -> None:
    row = service._PortRow(
        switch_name="SW-A", number=14, trunk_vlans="10, 20 , 30"
    )
    assert row.trunk_vlans == [10, 20, 30]


def test_subnet_row_parses_boolean_yes_no() -> None:
    yes = service._SubnetRow(cidr="10.0.0.0/24", site_code="HQ", dhcp_enabled="yes")
    no = service._SubnetRow(cidr="10.0.0.0/24", site_code="HQ", dhcp_enabled="non")
    blank = service._SubnetRow(cidr="10.0.0.0/24", site_code="HQ", dhcp_enabled="")
    assert yes.dhcp_enabled is True
    assert no.dhcp_enabled is False
    assert blank.dhcp_enabled is None


@pytest.mark.asyncio
async def test_persist_subnet_keeps_existing_dhcp_enabled_when_csv_cell_blank() -> None:
    """Re-importing a CSV that lacks (or has a blank) `dhcp_enabled` cell
    must NOT disable DHCP on existing subnets. The previous logic coerced
    blank → False at the data-dict step, and the setattr branch ran on
    any non-None value, so every round-trip silently flipped DHCP off
    across the inventory.
    """
    from app.models.core import Site
    from app.models.subnet import Subnet

    existing = Subnet(
        id=42,
        cidr="10.0.0.0/24",
        site_id=1,
        dhcp_enabled=True,
        dhcp_range_start="10.0.0.50",
        dhcp_range_end="10.0.0.100",
    )

    # _site_by_code is the first lookup. We control the result sequence so
    # the second execute() returns our pre-existing subnet.
    site_result = AsyncMock()
    site_result.scalar_one_or_none = lambda: Site(id=1, code="HQ", name="HQ")
    subnet_result = AsyncMock()
    subnet_result.scalar_one_or_none = lambda: existing

    db = _fresh_db()
    db.execute = AsyncMock(side_effect=[site_result, subnet_result])

    row = service._SubnetRow(cidr="10.0.0.0/24", site_code="HQ", dhcp_enabled="")
    assert row.dhcp_enabled is None
    await service._persist_subnet(db, row)

    # The whole point: existing.dhcp_enabled must NOT have flipped to False.
    assert existing.dhcp_enabled is True


@pytest.mark.asyncio
async def test_persist_port_replaces_trunk_vlans_via_symmetric_diff() -> None:
    """The trunk replacement used to delete every existing PortVlan row
    and re-add every wanted vlan, which trips port_vlan_pk when the two
    sets overlap (Postgres can flush the INSERT before the matching
    DELETE in the same unit-of-work). Pin the new symmetric-diff path:
    only delete rows that are leaving the set, only add rows that are
    joining it.
    """
    from app.models.port import Port, PortVlan
    from app.models.switch import Switch
    from app.models.vlan import Vlan

    switch = Switch(id=1, name="SW-A", port_count=24)
    port = Port(id=10, switch_id=1, number=2, native_vlan_id=None)
    # PortVlan.vlan_id is FK → vlans.id (the row PK), not the 802.1Q
    # public VLAN number. Existing tagged set holds Vlan PKs 100 & 200
    # (i.e. public VLAN ids 10 & 20). Wanted set after the CSV will be
    # Vlan PKs 200 & 300 (public 20 & 30): expect 1 delete (PK 100)
    # and 1 add (PK 300); the row for PK 200 stays.
    existing_pvs = [
        PortVlan(port_id=10, vlan_id=100),
        PortVlan(port_id=10, vlan_id=200),
    ]
    vlans = {
        10: Vlan(id=100, vlan_id=10, name="legacy"),
        20: Vlan(id=200, vlan_id=20, name="keep"),
        30: Vlan(id=300, vlan_id=30, name="new"),
    }

    async def fake_switch_by_name(_db, name, column="switch_name"):
        assert name == "SW-A"
        return switch

    async def fake_port_on_switch(_db, sw, num, column="number"):
        assert sw is switch and num == 2
        return port

    async def fake_vlan_by_id(_db, vid, column=None):
        if vid is None:
            return None
        return vlans[vid]

    pv_scalars = AsyncMock()
    pv_scalars.all = lambda: existing_pvs
    pv_result = AsyncMock()
    pv_result.scalars = lambda: pv_scalars

    db = _fresh_db()
    db.execute = AsyncMock(return_value=pv_result)
    db.delete = AsyncMock()
    added: list[PortVlan] = []
    db.add = lambda obj: added.append(obj)  # type: ignore[assignment]

    monkey_patches = {
        "_switch_by_name": fake_switch_by_name,
        "_port_on_switch": fake_port_on_switch,
        "_vlan_by_id": fake_vlan_by_id,
    }
    orig = {k: getattr(service, k) for k in monkey_patches}
    try:
        for k, v in monkey_patches.items():
            setattr(service, k, v)
        row = service._PortRow(
            switch_name="SW-A",
            number=2,
            trunk_vlans="20, 30",
        )
        await service._persist_port(db, row)
    finally:
        for k, v in orig.items():
            setattr(service, k, v)

    # Exactly one delete (for Vlan PK 100 / public id 10) — the row
    # for PK 200 / public id 20 stays put.
    assert db.delete.await_count == 1
    deleted_pv = db.delete.await_args_list[0].args[0]
    assert deleted_pv.vlan_id == 100
    # Exactly one add (for Vlan PK 300 / public id 30 — public id 20
    # is reused from the existing row).
    assert len(added) == 1
    assert added[0].vlan_id == 300


def test_friendly_integrity_recognises_known_constraints() -> None:
    assert "overlaps" in service._friendly_integrity(
        "violates exclusion constraint subnets_no_overlap"
    )
    assert "VLAN id" in service._friendly_integrity(
        "duplicate key vlans_vlan_id_key"
    )
    assert "constraint violation" in service._friendly_integrity("???")


# --- Regression: round-trip blank optional fields ------------------------- #


def test_vlan_row_accepts_blank_color() -> None:
    # Blank cells in the exported CSV used to be rejected by the hex pattern,
    # breaking export → import round-trips for VLANs with no color set.
    row = service._VlanRow(vlan_id=10, name="users", color="")
    assert row.color is None


def test_switch_row_accepts_blank_site_and_room_codes() -> None:
    # `room_id` is nullable on Switch — roomless switches must round-trip.
    row = service._SwitchRow(name="SW-A", site_code="", room_code="", port_count=24)
    assert row.site_code is None
    assert row.room_code is None


def test_switch_row_rejects_partial_location() -> None:
    # Only one of (site_code, room_code) blank is a user error, not roomless.
    # Without this check, the supplied code would silently be ignored.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        service._SwitchRow(name="SW-A", site_code="PAR", room_code="", port_count=24)
    with pytest.raises(ValidationError):
        service._SwitchRow(name="SW-A", site_code="", room_code="SRV-01", port_count=24)


# --- Regression: blank cells coerce to None for every optional int field --- #
# Reported during a real customer CSV import: subnets without an assigned
# VLAN exported as `vlan_id=""` and the importer crashed on Pydantic's int
# parsing instead of treating the blank as "no VLAN". Same pattern applied
# to every other Optional[int] field on the row models.


def test_subnet_row_accepts_blank_vlan_id() -> None:
    row = service._SubnetRow(cidr="10.0.0.0/24", site_code="HQ", vlan_id="")
    assert row.vlan_id is None


def test_port_row_accepts_blank_native_vlan() -> None:
    row = service._PortRow(switch_name="SW-A", number=1, native_vlan="")
    assert row.native_vlan is None


def test_link_row_accepts_blank_speed_mbps() -> None:
    row = service._LinkRow(
        switch_a="SW-A", port_a=1, switch_b="SW-B", port_b=1, speed_mbps=""
    )
    assert row.speed_mbps is None


# --- Regression: ok_rows reflects rows actually attempted ----------------- #


@pytest.mark.asyncio
async def test_ok_rows_only_counts_rows_persisted_before_failure() -> None:
    # Apply phase: first row succeeds, second hits a _RefError, third+ never
    # attempted. Buggy code reported `ok_rows = len(parsed) - 1` (i.e. 2 of 3
    # "ok"), miscounting the third row that never even ran.
    db = _fresh_db()
    scalar_result = AsyncMock()
    scalar_result.scalar_one_or_none = lambda: None
    db.execute = AsyncMock(return_value=scalar_result)

    call_count = {"n": 0}

    async def fake_persist(_db: object, _model: object) -> None:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise service._RefError("code", "X", "boom")

    monkeyed = service._ImportSpec(service._SiteRow, fake_persist)
    original = service.SPECS["sites"]
    service.SPECS["sites"] = monkeyed
    try:
        report = await service.run_import(
            db,
            "sites",
            _csv("code;name", "A;Alpha", "B;Bravo", "C;Charlie"),
            dry_run=False,
        )
    finally:
        service.SPECS["sites"] = original

    assert report.parsed_rows == 3
    assert report.ok_rows == 1
    assert len(report.error_rows) == 1
    assert report.error_rows[0].line == 3  # 2nd data row = file line 3
    assert report.applied is False
    db.rollback.assert_awaited_once()
