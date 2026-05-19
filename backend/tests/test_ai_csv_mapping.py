"""Tests for the CSV mapping assistant.

We exercise the pure-Python helpers (`list_canonical_fields`,
`_truncate_sample`, `_build_tool`) and the post-call sanitization that runs
after the LLM returns a tool call. The provider round-trip is mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai import csv_mapping as cm
from app.services.ai.types import AICompletion, AIProviderError, TokenUsage, ToolCall


def test_list_canonical_fields_returns_sorted_set() -> None:
    fields = cm.list_canonical_fields("subnets")
    assert "cidr" in fields and "gateway" in fields
    assert fields == sorted(fields)  # stable order for the UI


def test_list_canonical_fields_unknown_entity_returns_empty() -> None:
    assert cm.list_canonical_fields("unicorns") == []


def test_truncate_sample_caps_rows_and_cells() -> None:
    rows = [
        ["A" * 200, "short"],
        ["B" * 50, "x"],
        ["C", "y"],
        ["dropped", "dropped"],
        ["dropped", "dropped"],
    ]
    out = cm._truncate_sample(rows)
    assert len(out) == cm._MAX_SAMPLE_ROWS
    assert all(len(cell) <= cm._MAX_CELL_LEN for row in out for cell in row)


def test_build_tool_restricts_suggested_field_to_known_fields() -> None:
    tool = cm._build_tool(["cidr", "gateway"])
    enum = tool.input_schema["properties"]["columns"]["items"]["properties"][
        "suggested_field"
    ]["enum"]
    # The enum is the canonical set + None (to allow "unmapped").
    assert set(enum) == {"cidr", "gateway", None}


@pytest.mark.asyncio
async def test_run_mapping_rejects_unknown_entity() -> None:
    db = AsyncMock()
    with pytest.raises(AIProviderError):
        await cm.run_mapping_suggestion(
            db,
            user_id=1,
            entity="unicorns",
            csv_columns=["a"],
            sample_rows=[],
        )


@pytest.mark.asyncio
async def test_run_mapping_filters_hallucinated_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model may invent a field that's not in the catalog — strip it."""
    fake_provider = SimpleNamespace(
        name="anthropic",
        model="claude-sonnet-4-6",
    )

    async def fake_call(**kwargs):
        return AICompletion(
            text=None,
            tool_call=ToolCall(
                name="submit_mapping",
                input={
                    "columns": [
                        {"csv_column": "Subnet", "suggested_field": "cidr", "confidence": 0.95, "notes": "exact"},
                        {"csv_column": "GW", "suggested_field": "gateway", "confidence": 0.9, "notes": ""},
                        {"csv_column": "Site", "suggested_field": "site_code", "confidence": 0.85, "notes": ""},
                        {"csv_column": "Foobar", "suggested_field": "hallucinated_field", "confidence": 0.5},
                    ],
                    "missing_required_fields": ["description"],
                },
            ),
            usage=TokenUsage(prompt_tokens=100, completion_tokens=20),
        )

    fake_provider.call = fake_call  # type: ignore[attr-defined]
    monkeypatch.setattr(cm, "get_provider", lambda: fake_provider)

    # Mock the AIRunLog persistence.
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    result = await cm.run_mapping_suggestion(
        db,
        user_id=1,
        entity="subnets",
        csv_columns=["Subnet", "GW", "Site", "Foobar"],
        sample_rows=[["10.0.0.0/24", "10.0.0.1", "PAR", "?"]],
    )

    # Hallucinated field is replaced by None; the rest passes through.
    by_col = {c.csv_column: c for c in result.columns}
    assert by_col["Foobar"].suggested_field is None
    assert by_col["Subnet"].suggested_field == "cidr"
    assert by_col["GW"].suggested_field == "gateway"
    assert by_col["Site"].suggested_field == "site_code"
    # description is in the catalog and not used by any column → reported.
    assert "description" in result.missing_required_fields


@pytest.mark.asyncio
async def test_run_mapping_dedup_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the model assigns the same target to two columns, only the FIRST
    keeps it — the duplicate is forced to None."""
    fake_provider = SimpleNamespace(name="anthropic", model="claude-sonnet-4-6")

    async def fake_call(**kwargs):
        return AICompletion(
            text=None,
            tool_call=ToolCall(
                name="submit_mapping",
                input={
                    "columns": [
                        {"csv_column": "A", "suggested_field": "cidr", "confidence": 0.9},
                        {"csv_column": "B", "suggested_field": "cidr", "confidence": 0.5},
                    ],
                    "missing_required_fields": [],
                },
            ),
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        )

    fake_provider.call = fake_call  # type: ignore[attr-defined]
    monkeypatch.setattr(cm, "get_provider", lambda: fake_provider)
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    result = await cm.run_mapping_suggestion(
        db,
        user_id=1,
        entity="subnets",
        csv_columns=["A", "B"],
        sample_rows=[],
    )
    assert result.columns[0].suggested_field == "cidr"
    assert result.columns[1].suggested_field is None
