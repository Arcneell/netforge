"""Snapshot / diff response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SnapshotEntityBucket(BaseModel):
    """Per-entity counter inside a snapshot summary."""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    # Entity that was created AND deleted inside the window — kept separate
    # so an operator can spot "the migration script that wiped its own VRF".
    transient: int = 0


class SnapshotSummary(BaseModel):
    total_audit_rows: int
    # Audit rows we couldn't bucket because they had no entity_id (rare —
    # mostly legacy bulk ops). Counted but not detailed.
    orphan_rows: int
    by_entity: dict[str, SnapshotEntityBucket]


class SnapshotChange(BaseModel):
    """One affected entity inside the window."""

    entity: str
    entity_id: int
    status: str = Field(description="created | updated | deleted | transient")
    actions_count: int
    first_action_at: datetime
    last_action_at: datetime
    # Union of columns touched by every audit row in the bucket.
    fields_changed: list[str]


class SnapshotCompareResponse(BaseModel):
    from_ts: datetime
    to_ts: datetime
    summary: SnapshotSummary
    changes: list[SnapshotChange]
