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


# --- Deterministic data-quality checks --------------------------------------


def test_local_dq_flags_empty_required_cells() -> None:
    issues = cm.run_local_data_quality(
        entity="sites",
        csv_columns=["Code", "Name"],
        sample_rows=[
            ["HQ", "Headquarters"],
            ["", "Branch"],
            ["", ""],
        ],
        column_mapping={"Code": "code", "Name": "name"},
    )
    # Both `code` and `name` are required for sites.
    cols = {(i.column, i.issue) for i in issues}
    assert ("Code", "empty required value") in cols
    assert ("Name", "empty required value") in cols
    # Counts only sample rows.
    code_issue = next(i for i in issues if i.column == "Code")
    assert code_issue.affected_row_count == 2
    assert code_issue.source == "local"
    assert code_issue.severity == "critical"


def test_local_dq_flags_invalid_cidr() -> None:
    issues = cm.run_local_data_quality(
        entity="subnets",
        csv_columns=["Subnet"],
        sample_rows=[["10.0.0.0/24"], ["not-a-network"], ["10.0.0.1"]],
        column_mapping={"Subnet": "cidr"},
    )
    # 10.0.0.0/24 → valid; not-a-network + 10.0.0.1 (missing /prefix) → flagged.
    cidr_issue = next(
        (i for i in issues if i.column == "Subnet" and "cidr" in i.issue),
        None,
    )
    assert cidr_issue is not None
    assert cidr_issue.affected_row_count == 2
    assert "not-a-network" in cidr_issue.sample_values


def test_local_dq_flags_invalid_mac() -> None:
    issues = cm.run_local_data_quality(
        entity="ips",
        csv_columns=["IP", "MAC"],
        sample_rows=[
            ["10.0.0.1", "aa:bb:cc:dd:ee:ff"],
            ["10.0.0.2", "not-a-mac"],
        ],
        column_mapping={"IP": "address", "MAC": "mac"},
    )
    mac_issue = next(i for i in issues if i.column == "MAC")
    assert "not-a-mac" in mac_issue.sample_values


def test_local_dq_accepts_cisco_dotted_mac_format() -> None:
    """Codex P2 on PR #63: the importer's `_MAC_PATTERNS` accepts
    `aabb.ccdd.eeff` so the local validator must too — otherwise we'd
    flag valid Cisco/HP MACs as data-quality issues."""
    issues = cm.run_local_data_quality(
        entity="ips",
        csv_columns=["MAC"],
        sample_rows=[["aabb.ccdd.eeff"], ["AABB.CCDD.EEFF"]],
        column_mapping={"MAC": "mac"},
    )
    assert not any(i.column == "MAC" for i in issues)


def test_local_dq_subnets_treats_site_code_as_required() -> None:
    """Codex P2 on PR #63: `site_code` is required by `_SubnetRow` in the
    importer but was missing from the mapper's required-field map. A blank
    cell in a mapped `site_code` column now produces a critical issue."""
    issues = cm.run_local_data_quality(
        entity="subnets",
        csv_columns=["Subnet", "Site"],
        sample_rows=[["10.0.0.0/24", ""], ["10.0.1.0/24", "PAR"]],
        column_mapping={"Subnet": "cidr", "Site": "site_code"},
    )
    site_issue = next(
        (i for i in issues if i.column == "Site" and "empty" in i.issue),
        None,
    )
    assert site_issue is not None
    assert site_issue.severity == "critical"
    assert site_issue.affected_row_count == 1


def test_local_dq_flags_invalid_vlan_id() -> None:
    issues = cm.run_local_data_quality(
        entity="vlans",
        csv_columns=["ID", "Name"],
        sample_rows=[["10", "user"], ["99999", "broken"], ["abc", "alpha"]],
        column_mapping={"ID": "vlan_id", "Name": "name"},
    )
    vlan_issue = next(i for i in issues if i.column == "ID")
    assert vlan_issue.affected_row_count == 2
    assert vlan_issue.severity == "warning"


def test_local_dq_flags_duplicates_in_unique_columns() -> None:
    issues = cm.run_local_data_quality(
        entity="subnets",
        csv_columns=["CIDR"],
        sample_rows=[["10.0.0.0/24"], ["10.0.0.0/24"], ["10.0.1.0/24"]],
        column_mapping={"CIDR": "cidr"},
    )
    dup_issue = next(i for i in issues if "duplicate" in i.issue)
    assert dup_issue.severity == "warning"
    assert "10.0.0.0/24" in dup_issue.sample_values


def test_local_dq_skips_unmapped_columns() -> None:
    """Columns the operator hasn't mapped to a canonical field should be
    invisible to the local checks — we can't validate something whose
    expected shape we don't know."""
    issues = cm.run_local_data_quality(
        entity="subnets",
        csv_columns=["Mystery"],
        sample_rows=[["nonsense"], [""]],
        column_mapping={"Mystery": None},
    )
    assert issues == []


@pytest.mark.asyncio
async def test_run_mapping_includes_local_data_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: the local check should pad the LLM's data_quality list."""
    fake_provider = SimpleNamespace(name="anthropic", model="claude-sonnet-4-6")

    async def fake_call(**kwargs):
        return AICompletion(
            text=None,
            tool_call=ToolCall(
                name="submit_mapping",
                input={
                    "columns": [
                        {"csv_column": "CIDR", "suggested_field": "cidr", "confidence": 0.95},
                    ],
                    "missing_required_fields": [],
                    "data_quality": [
                        {
                            "severity": "info",
                            "column": "CIDR",
                            "issue": "mixed casing in headers",
                            "details": "Some CIDR values use uppercase.",
                            "affected_row_count": 1,
                        },
                    ],
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
        csv_columns=["CIDR"],
        sample_rows=[["not-a-cidr"]],  # local check should fire on this
    )
    sources = {i.source for i in result.data_quality}
    assert sources == {"local", "llm"}
    # Local check produced exactly one entry — invalid CIDR.
    local_issues = [i for i in result.data_quality if i.source == "local"]
    assert len(local_issues) == 1
    assert "not-a-cidr" in local_issues[0].sample_values
