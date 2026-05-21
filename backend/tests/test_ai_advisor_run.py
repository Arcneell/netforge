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
    compute_insight_streaks,
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


# --- compute_insight_streaks ------------------------------------------------


def _insight(id: int, category: str, title: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        category=SimpleNamespace(value=category),
        title=title,
    )


def _result_with(rows: list) -> MagicMock:
    r = MagicMock()
    r.all = MagicMock(return_value=rows)
    return r


@pytest.mark.asyncio
async def test_streaks_default_to_one_when_no_prior_runs() -> None:
    """First-ever advisor run: every finding is brand-new, so every streak
    is 1. Sanity check that the helper doesn't crash on the empty-prior-runs
    branch."""
    items = [_insight(1, "spof", "SPOF on SW-CORE-01"), _insight(2, "naming", "VLAN name typo")]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with([]))  # no prior runs
    streaks = await compute_insight_streaks(db, current_run_id=10, current_items=items)
    assert streaks == {1: 1, 2: 1}


@pytest.mark.asyncio
async def test_streaks_count_consecutive_matches() -> None:
    """A finding present in the current run AND the 3 most recent prior
    runs → streak 4. The match key is `(category, lowercased title)` —
    we lowercase both sides defensively so a casing tweak in a re-run
    doesn't reset the streak."""
    items = [
        _insight(100, "spof", "SPOF on SW-CORE-01"),
        _insight(101, "naming", "fresh finding"),
    ]
    # prior_run_rows: 3 prior runs, newest first
    prior_run_rows = _result_with([(9,), (8,), (7,)])
    # For the SPOF item: present in runs 9 + 8 + 7 (streak grows to 4).
    # For the "fresh finding": not in any prior run (streak stays 1).
    prior_keys_rows = _result_with(
        [
            (9, SimpleNamespace(value="spof"), "SPOF on SW-CORE-01"),
            (8, SimpleNamespace(value="spof"), "spof on sw-core-01"),  # casing-tolerant
            (7, SimpleNamespace(value="spof"), "SPOF on SW-CORE-01"),
        ]
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[prior_run_rows, prior_keys_rows])
    streaks = await compute_insight_streaks(db, current_run_id=10, current_items=items)
    assert streaks == {100: 4, 101: 1}


@pytest.mark.asyncio
async def test_streak_breaks_on_gap() -> None:
    """If a finding was present in run N and N-2 but NOT N-1, the streak
    must stop counting at the gap — the operator presumably fixed it
    between runs and the issue regressed. We report `2` (current + N
    only), not `3`, so the badge doesn't lie about persistence."""
    items = [_insight(1, "spof", "SPOF on X")]
    prior_run_rows = _result_with([(9,), (8,), (7,)])
    prior_keys_rows = _result_with(
        [
            # Present in 9 ...
            (9, SimpleNamespace(value="spof"), "SPOF on X"),
            # ... absent from 8 ...
            (8, SimpleNamespace(value="capacity"), "Unrelated"),
            # ... present again in 7 (but shouldn't extend the streak).
            (7, SimpleNamespace(value="spof"), "SPOF on X"),
        ]
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[prior_run_rows, prior_keys_rows])
    streaks = await compute_insight_streaks(db, current_run_id=10, current_items=items)
    assert streaks == {1: 2}  # current + run 9 only
