"""Snapshot / diff comparison — derived from the audit log.

Takes two timestamps and answers "what changed between these moments?" by
aggregating the `audit_log` rows in the window into one row per affected
entity. The implementation is deliberately lightweight: we do NOT attempt
to reconstruct full entity state at each timestamp (which would require
replaying every audit event since day one, an expensive O(N) scan). The
audit log already records the before/after of each mutation, so the
aggregated view is enough for an operator to answer:

  - "What did we change since the merge freeze last month?"
  - "Show me everything that touched switch SW-CORE-01 last week."
  - "How many ports were created during the lab rebuild?"

For each (entity, entity_id) bucket we compute:

  - `status` from the sequence: create-only → "created"; delete present →
    "deleted" (or "transient" when also created in the same window);
    everything else → "updated".
  - `fields_changed`: union of every `after` key across the bucket's
    updates. Useful to grep "where did `dhcp_enabled` flip?".
  - `actions_count`: total audit rows in the bucket.

Caller is expected to bound the window (`from`/`to`) to keep the aggregation
fast — the router enforces a 90-day cap.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AuditLog


def _extract_field_names(changes: dict[str, Any] | None) -> set[str]:
    """Return the set of column names recorded in a single audit row."""
    if not isinstance(changes, dict):
        return set()
    out: set[str] = set()
    for bucket_key in ("before", "after"):
        bucket = changes.get(bucket_key)
        if isinstance(bucket, dict):
            out.update(bucket.keys())
    return out


def _derive_status(actions: list[str]) -> str:
    """First / last action determines the bucket's net effect.

    Status legend:
      - `created`   : created in the window, still present at `to`
      - `updated`   : existed before the window, mutated within it
      - `deleted`   : existed before the window, deleted within it
      - `transient` : created AND deleted in the window (no surviving row)
    """
    if not actions:
        return "updated"  # defensive — shouldn't happen
    first, last = actions[0], actions[-1]
    if first == "create" and last == "delete":
        return "transient"
    if first == "create":
        return "created"
    if last == "delete":
        return "deleted"
    return "updated"


async def compare_window(
    db: AsyncSession,
    *,
    from_ts: datetime,
    to_ts: datetime,
    entity: str | None = None,
) -> dict:
    """Aggregate every audit row in [from_ts, to_ts] into a per-entity diff."""
    base = (
        select(AuditLog)
        .where(AuditLog.created_at >= from_ts)
        .where(AuditLog.created_at <= to_ts)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    )
    if entity is not None:
        base = base.where(AuditLog.entity == entity)
    rows: list[AuditLog] = list((await db.execute(base)).scalars().all())

    # Bucket by (entity, entity_id). Skip rows with no entity_id (e.g.
    # bulk operations that didn't carry the PK) — they can't be aggregated
    # but are still counted in the total.
    buckets: dict[tuple[str, int], list[AuditLog]] = defaultdict(list)
    orphan_count = 0
    for row in rows:
        if row.entity_id is None:
            orphan_count += 1
            continue
        buckets[(row.entity, int(row.entity_id))].append(row)

    changes: list[dict] = []
    by_entity_counter: dict[str, Counter] = defaultdict(Counter)

    for (ent, ent_id), bucket in buckets.items():
        actions = [r.action.value if hasattr(r.action, "value") else str(r.action) for r in bucket]
        status = _derive_status(actions)
        fields: set[str] = set()
        for r in bucket:
            fields.update(_extract_field_names(r.changes))
        changes.append(
            {
                "entity": ent,
                "entity_id": ent_id,
                "status": status,
                "actions_count": len(bucket),
                "first_action_at": bucket[0].created_at,
                "last_action_at": bucket[-1].created_at,
                "fields_changed": sorted(fields),
            }
        )
        by_entity_counter[ent][status] += 1

    # Sort by last_action_at desc — most recent activity bubbles to the top.
    changes.sort(key=lambda c: c["last_action_at"], reverse=True)

    by_entity = {
        ent: {
            "created": int(counter.get("created", 0)),
            "updated": int(counter.get("updated", 0)),
            "deleted": int(counter.get("deleted", 0)),
            "transient": int(counter.get("transient", 0)),
        }
        for ent, counter in by_entity_counter.items()
    }

    return {
        "from_ts": from_ts,
        "to_ts": to_ts,
        "summary": {
            "total_audit_rows": len(rows),
            "orphan_rows": orphan_count,
            "by_entity": by_entity,
        },
        "changes": changes,
    }
