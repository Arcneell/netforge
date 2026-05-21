"""Snapshot diff router — /api/snapshots/compare (admin-only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.snapshot import SnapshotCompareResponse
from app.services.snapshots import compare_window

router = APIRouter(
    prefix="/snapshots",
    tags=["snapshots"],
    dependencies=[Depends(require_role(UserRole.admin))],
)

# Largest comparison window we accept. The endpoint aggregates audit rows
# in-memory; a 90-day cap keeps a single response well under 100k rows
# even in a busy install. Operators wanting longer-term reporting should
# script multiple calls or query the audit log directly.
_MAX_WINDOW = timedelta(days=90)


@router.get("/compare", response_model=SnapshotCompareResponse)
async def compare(
    from_: datetime = Query(..., alias="from", description="ISO-8601 lower bound (inclusive)."),
    to: datetime | None = Query(
        default=None,
        description="ISO-8601 upper bound (inclusive). Defaults to now() when omitted.",
    ),
    entity: str | None = Query(
        default=None,
        max_length=50,
        description="Restrict the diff to one entity type (site, room, vlan, subnet, port, ...).",
    ),
    db: AsyncSession = Depends(get_db),
) -> SnapshotCompareResponse:
    """Aggregate every audit row in [from, to] into a per-entity diff.

    The response is a flat list of `{entity, entity_id, status, fields_changed}`
    plus a per-entity summary. Status legend:
      - `created`   : entity exists at `to` but didn't exist at `from`
      - `updated`   : existed before, mutated during the window
      - `deleted`   : existed before, removed during the window
      - `transient` : created AND deleted in the window — useful for spotting
                      botched migrations

    We do NOT reconstruct full entity state at each timestamp — that would
    require replaying every audit event since day one. The audit log's
    `before`/`after` payloads are sufficient for the questions this view
    typically answers.
    """
    now = datetime.now(UTC)
    to_ts = to or now
    # Naive datetimes coming in via query string are treated as UTC so we
    # can compare them with timezone-aware DB columns without TypeErrors.
    if from_.tzinfo is None:
        from_ = from_.replace(tzinfo=UTC)
    if to_ts.tzinfo is None:
        to_ts = to_ts.replace(tzinfo=UTC)

    if from_ >= to_ts:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "INVALID_RANGE", "message": "`from` must be strictly before `to`."}},
        )
    if to_ts - from_ > _MAX_WINDOW:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "WINDOW_TOO_LARGE",
                    "message": f"Maximum window is {_MAX_WINDOW.days} days.",
                }
            },
        )

    result = await compare_window(db, from_ts=from_, to_ts=to_ts, entity=entity)
    return SnapshotCompareResponse(**result)
