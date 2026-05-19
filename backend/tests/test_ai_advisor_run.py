"""Tests for the advisor run plumbing — schema enforcement + persistence.

We exercise `_persist_insights` and the new `list_latest_insights` /
`latest_run` helpers. The LLM call itself is out of scope here; it's covered
by the provider tests + the manual integration smoke test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.advisor import (
    _persist_insights,
    latest_run,
    list_latest_insights,
)


@pytest.mark.asyncio
async def test_persist_drops_rows_with_missing_required_fields() -> None:
    db = AsyncMock()
    db.add_all = MagicMock()
    db.flush = AsyncMock()
    raw = [
        # missing title
        {"severity": "critical", "category": "spof", "description": "x"},
        # missing description
        {"severity": "info", "category": "naming", "title": "Naming"},
        # unknown severity
        {"severity": "screaming", "category": "spof", "title": "T", "description": "D"},
    ]
    count = await _persist_insights(db, run_id=1, raw_items=raw)
    assert count == 0
    db.add_all.assert_not_called()


@pytest.mark.asyncio
async def test_persist_clamps_fields_and_writes_valid_rows() -> None:
    db = AsyncMock()
    db.add_all = MagicMock()
    db.flush = AsyncMock()
    long_title = "T" * 500
    raw = [
        {
            "severity": "warning",
            "category": "capacity",
            "title": long_title,
            "description": "Subnet 10.0.0.0/24 is 92% full",
            "recommendation": "Plan migration to /23",
            "affected_entities": [{"type": "subnet", "id": 12, "name": "10.0.0.0/24"}],
        }
    ]
    count = await _persist_insights(db, run_id=42, raw_items=raw)
    assert count == 1
    db.add_all.assert_called_once()
    row = db.add_all.call_args.args[0][0]
    assert len(row.title) == 200  # capped per docstring
    assert row.run_id == 42
    assert row.affected_entities == [{"type": "subnet", "id": 12, "name": "10.0.0.0/24"}]


@pytest.mark.asyncio
async def test_persist_accepts_unknown_category_as_other() -> None:
    """`InsightCategory` is an Enum — an unknown value triggers ValueError in
    the constructor and the row should be dropped, not coerced into 'other'."""
    db = AsyncMock()
    db.add_all = MagicMock()
    db.flush = AsyncMock()
    raw = [
        {
            "severity": "warning",
            "category": "made-up-bucket",
            "title": "T",
            "description": "D",
        }
    ]
    count = await _persist_insights(db, run_id=1, raw_items=raw)
    assert count == 0


@pytest.mark.asyncio
async def test_persist_ignores_non_list_affected_entities() -> None:
    """The LLM has been observed to return `affected_entities` as a string —
    we must not crash, just blank the field."""
    db = AsyncMock()
    db.add_all = MagicMock()
    db.flush = AsyncMock()
    raw = [
        {
            "severity": "info",
            "category": "naming",
            "title": "T",
            "description": "D",
            "affected_entities": "not a list",
        }
    ]
    count = await _persist_insights(db, run_id=1, raw_items=raw)
    assert count == 1
    row = db.add_all.call_args.args[0][0]
    assert row.affected_entities == []


@pytest.mark.asyncio
async def test_latest_run_returns_none_when_empty() -> None:
    db = AsyncMock()
    first_result = MagicMock()
    first_result.first = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=first_result)
    assert await latest_run(db) is None


@pytest.mark.asyncio
async def test_latest_run_returns_id_and_timestamp() -> None:
    now = datetime(2026, 5, 19, tzinfo=UTC)
    db = AsyncMock()
    first_result = MagicMock()
    first_result.first = MagicMock(return_value=(42, now))
    db.execute = AsyncMock(return_value=first_result)
    assert await latest_run(db) == (42, now)


@pytest.mark.asyncio
async def test_list_latest_insights_handles_empty_state() -> None:
    db = AsyncMock()
    first_result = MagicMock()
    first_result.first = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=first_result)
    run_id, run_created_at, items = await list_latest_insights(db)
    assert (run_id, run_created_at, items) == (None, None, [])


@pytest.mark.asyncio
async def test_list_latest_insights_returns_triple_with_timestamp() -> None:
    now = datetime(2026, 5, 19, tzinfo=UTC)
    fake_insights = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    first_result = MagicMock()
    first_result.first = MagicMock(return_value=(7, now))
    second_result = MagicMock()
    second_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=fake_insights))
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[first_result, second_result])
    run_id, run_created_at, items = await list_latest_insights(db)
    assert run_id == 7
    assert run_created_at == now
    assert items == fake_insights
