"""Tests for the suggest-links persistence layer (`_persist_suggestions`).

We mock the AsyncSession so the validation rules can be exercised without a
real Postgres. The rules pinned here are the same the docstring of
`_persist_suggestions` lists — they are what stands between a hallucinated
LLM answer and a corrupt `link_suggestions` table.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.suggest_links import _persist_suggestions


def _port(id_: int, switch_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=id_, switch_id=switch_id)


def _scalars(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _mock_db(
    *,
    ports: list,
    links: list,
    pending: list,
) -> AsyncMock:
    db = AsyncMock()
    # `_persist_suggestions` issues three queries in this order:
    #   1) Port.id.in_(referenced_ids)
    #   2) select(Link)
    #   3) select(LinkSuggestion).where(status == pending)
    db.execute = AsyncMock(
        side_effect=[_scalars(ports), _scalars(links), _scalars(pending)]
    )
    db.add_all = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_filters_out_below_threshold() -> None:
    db = _mock_db(ports=[_port(1, 10), _port(2, 11)], links=[], pending=[])
    raw = [{"port_a_id": 1, "port_b_id": 2, "confidence": 0.4, "reasoning": "weak"}]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 0
    db.add_all.assert_not_called()


@pytest.mark.asyncio
async def test_drops_same_switch_pair() -> None:
    db = _mock_db(ports=[_port(1, 10), _port(2, 10)], links=[], pending=[])
    raw = [{"port_a_id": 1, "port_b_id": 2, "confidence": 0.9, "reasoning": "same sw"}]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 0


@pytest.mark.asyncio
async def test_drops_self_pair_and_missing_port() -> None:
    db = _mock_db(ports=[_port(1, 10)], links=[], pending=[])
    raw = [
        {"port_a_id": 1, "port_b_id": 1, "confidence": 0.9, "reasoning": "self"},
        {"port_a_id": 1, "port_b_id": 99, "confidence": 0.9, "reasoning": "ghost"},
    ]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 0


@pytest.mark.asyncio
async def test_canonical_order_and_dedup_within_batch() -> None:
    """The DB constraint requires port_a_id < port_b_id. We must reorder *and*
    dedup when the LLM repeats the same pair in two orientations."""
    db = _mock_db(ports=[_port(1, 10), _port(2, 11)], links=[], pending=[])
    raw = [
        {"port_a_id": 2, "port_b_id": 1, "confidence": 0.9, "reasoning": "a"},
        {"port_a_id": 1, "port_b_id": 2, "confidence": 0.8, "reasoning": "duplicate"},
    ]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 1
    # The single row that landed must be in canonical order.
    db.add_all.assert_called_once()
    rows = db.add_all.call_args.args[0]
    assert len(rows) == 1
    assert (rows[0].port_a_id, rows[0].port_b_id) == (1, 2)


@pytest.mark.asyncio
async def test_skips_pair_already_in_links_table() -> None:
    existing_link = SimpleNamespace(port_a_id=1, port_b_id=2)
    db = _mock_db(
        ports=[_port(1, 10), _port(2, 11)],
        links=[existing_link],
        pending=[],
    )
    raw = [{"port_a_id": 1, "port_b_id": 2, "confidence": 0.95, "reasoning": "ok"}]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 0


@pytest.mark.asyncio
async def test_skips_pair_already_pending() -> None:
    existing_pending = SimpleNamespace(port_a_id=1, port_b_id=2)
    db = _mock_db(
        ports=[_port(1, 10), _port(2, 11)],
        links=[],
        pending=[existing_pending],
    )
    raw = [{"port_a_id": 1, "port_b_id": 2, "confidence": 0.95, "reasoning": "ok"}]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 0


@pytest.mark.asyncio
async def test_link_type_falls_back_to_copper_when_unknown() -> None:
    db = _mock_db(ports=[_port(1, 10), _port(2, 11)], links=[], pending=[])
    raw = [
        {
            "port_a_id": 1,
            "port_b_id": 2,
            "confidence": 0.9,
            "reasoning": "ok",
            "link_type": "telegram",  # invalid
        }
    ]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 1
    rows = db.add_all.call_args.args[0]
    assert rows[0].link_type == "copper"


@pytest.mark.asyncio
async def test_confidence_is_clamped_to_unit_interval() -> None:
    db = _mock_db(ports=[_port(1, 10), _port(2, 11)], links=[], pending=[])
    raw = [{"port_a_id": 1, "port_b_id": 2, "confidence": 1.7, "reasoning": "ok"}]
    count = await _persist_suggestions(db, run_id=1, raw_items=raw, threshold=0.5)
    assert count == 1
    rows = db.add_all.call_args.args[0]
    assert rows[0].confidence == 1.0


@pytest.mark.asyncio
async def test_empty_input_short_circuits() -> None:
    db = AsyncMock()
    count = await _persist_suggestions(db, run_id=1, raw_items=[], threshold=0.5)
    assert count == 0
    db.execute.assert_not_called()
