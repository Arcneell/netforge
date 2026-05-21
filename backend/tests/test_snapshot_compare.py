"""Snapshot compare — pure-function tests on the aggregation logic.

The router-side window validation is exercised through the schema layer in
the OpenAPI test pass; here we focus on `compare_window` and the helper
`_derive_status` which encode the actual business rules (what counts as
"created" vs "updated" vs "transient", etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.snapshots import (
    _derive_status,
    _extract_field_names,
    compare_window,
)

# --- _derive_status --------------------------------------------------------


def test_status_created_when_only_create_actions() -> None:
    assert _derive_status(["create"]) == "created"
    assert _derive_status(["create", "update", "update"]) == "created"


def test_status_deleted_when_window_ends_on_delete() -> None:
    assert _derive_status(["update", "delete"]) == "deleted"


def test_status_transient_when_created_and_deleted_in_window() -> None:
    assert _derive_status(["create", "delete"]) == "transient"
    assert _derive_status(["create", "update", "delete"]) == "transient"


def test_status_updated_when_no_create_no_terminal_delete() -> None:
    assert _derive_status(["update"]) == "updated"
    assert _derive_status(["update", "update"]) == "updated"


def test_status_defensive_on_empty_input() -> None:
    """Shouldn't ever happen in practice but the helper is defensive."""
    assert _derive_status([]) == "updated"


# --- _extract_field_names --------------------------------------------------


def test_extract_fields_handles_none() -> None:
    assert _extract_field_names(None) == set()


def test_extract_fields_returns_union_of_before_and_after_keys() -> None:
    payload = {
        "before": {"name": "old", "color": "#abc"},
        "after": {"name": "new", "dhcp_enabled": True},
    }
    assert _extract_field_names(payload) == {"name", "color", "dhcp_enabled"}


def test_extract_fields_ignores_non_dict_buckets() -> None:
    payload = {"after": {"only_key": 1}, "before": "weird"}
    assert _extract_field_names(payload) == {"only_key"}


# --- compare_window --------------------------------------------------------


def _audit_row(
    *,
    entity: str,
    entity_id: int | None,
    action: str,
    created_at: datetime,
    changes: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=created_at.timestamp(),  # stable enough for sort
        entity=entity,
        entity_id=entity_id,
        action=SimpleNamespace(value=action),
        created_at=created_at,
        changes=changes or {},
    )


def _mock_db_with_rows(rows: list) -> AsyncMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_empty_window_returns_zero_changes() -> None:
    db = _mock_db_with_rows([])
    out = await compare_window(
        db,
        from_ts=datetime(2026, 5, 1, tzinfo=UTC),
        to_ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert out["summary"]["total_audit_rows"] == 0
    assert out["changes"] == []


@pytest.mark.asyncio
async def test_buckets_per_entity_id_and_derives_status() -> None:
    t1 = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 10, 10, 0, tzinfo=UTC)
    t3 = datetime(2026, 5, 11, 9, 0, tzinfo=UTC)
    rows = [
        # subnet 1: create + update → "created"
        _audit_row(
            entity="subnet",
            entity_id=1,
            action="create",
            created_at=t1,
            changes={"after": {"cidr": "10.0.0.0/24", "site_id": 1}},
        ),
        _audit_row(
            entity="subnet",
            entity_id=1,
            action="update",
            created_at=t2,
            changes={"before": {"description": None}, "after": {"description": "X"}},
        ),
        # port 99: update only → "updated"
        _audit_row(
            entity="port",
            entity_id=99,
            action="update",
            created_at=t3,
            changes={"before": {"label": "a"}, "after": {"label": "b"}},
        ),
    ]
    db = _mock_db_with_rows(rows)

    out = await compare_window(
        db,
        from_ts=datetime(2026, 5, 1, tzinfo=UTC),
        to_ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    by = {(c["entity"], c["entity_id"]): c for c in out["changes"]}
    assert by[("subnet", 1)]["status"] == "created"
    assert by[("subnet", 1)]["actions_count"] == 2
    assert set(by[("subnet", 1)]["fields_changed"]) >= {
        "cidr",
        "site_id",
        "description",
    }
    assert by[("port", 99)]["status"] == "updated"
    assert by[("port", 99)]["fields_changed"] == ["label"]

    # Summary mirrors the bucket counts.
    summary = out["summary"]
    assert summary["total_audit_rows"] == 3
    assert summary["by_entity"]["subnet"]["created"] == 1
    assert summary["by_entity"]["port"]["updated"] == 1


@pytest.mark.asyncio
async def test_transient_is_counted_separately() -> None:
    t0 = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    t1 = datetime(2026, 5, 10, 9, 5, tzinfo=UTC)
    rows = [
        _audit_row(entity="vlan", entity_id=7, action="create", created_at=t0),
        _audit_row(entity="vlan", entity_id=7, action="delete", created_at=t1),
    ]
    db = _mock_db_with_rows(rows)
    out = await compare_window(
        db,
        from_ts=datetime(2026, 5, 1, tzinfo=UTC),
        to_ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert out["changes"][0]["status"] == "transient"
    assert out["summary"]["by_entity"]["vlan"]["transient"] == 1


@pytest.mark.asyncio
async def test_orphan_rows_are_counted_but_excluded_from_buckets() -> None:
    """Audit rows without an entity_id (rare bulk ops) can't be aggregated
    — we still count them in the summary so the operator notices."""
    t0 = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    rows = [
        _audit_row(entity="port", entity_id=None, action="update", created_at=t0),
    ]
    db = _mock_db_with_rows(rows)
    out = await compare_window(
        db,
        from_ts=datetime(2026, 5, 1, tzinfo=UTC),
        to_ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert out["changes"] == []
    assert out["summary"]["orphan_rows"] == 1
    assert out["summary"]["total_audit_rows"] == 1


@pytest.mark.asyncio
async def test_changes_are_sorted_by_last_action_desc() -> None:
    """Most recent activity bubbles up — operators scan top-down."""
    t1 = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 11, 9, 0, tzinfo=UTC)
    rows = [
        _audit_row(entity="port", entity_id=1, action="update", created_at=t1),
        _audit_row(entity="port", entity_id=2, action="update", created_at=t2),
    ]
    db = _mock_db_with_rows(rows)
    out = await compare_window(
        db,
        from_ts=datetime(2026, 5, 1, tzinfo=UTC),
        to_ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert [c["entity_id"] for c in out["changes"]] == [2, 1]
