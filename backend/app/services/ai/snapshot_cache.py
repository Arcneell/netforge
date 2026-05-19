"""In-memory cache for the topology snapshot fed to every AI feature.

Why a cache:
- All three AI features (`suggest_links`, `advisor`, `nl_query`) call
  `build_topology_context` on every request — the same full read of sites /
  rooms / switches / ports / links / vlans / subnets / devices.
- On a busy stack (one operator clicking around in Insights, refreshing,
  then asking Ask AI) the same JSON gets rebuilt N times in 30 seconds for
  no benefit.

Strategy:
- Cheap *fingerprint* query (counts + max(updated_at) per table) → if it
  matches the cached one, hand back the cached context dict without
  re-running the full fetch.
- TTL safety-net of 5 minutes regardless — defends against the unlikely
  case of a write that doesn't change row count and lands on a table
  without `updated_at`.

The cache is process-local. In a multi-replica deployment that's fine: the
worst case is each replica re-warms its own copy on first request.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from threading import Lock
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.link import Link
from app.models.port import Port
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan

# Tables we fingerprint. The first element of each pair is the model; the
# second is the optional `updated_at` column — None only for `Link` because
# it's append-only (link rows are insert / delete, never UPDATE in the
# canonical CRUD). Everything else carries a server-managed `updated_at`
# via the TimestampMixin (Site / Switch / Subnet / Ip from day 1, Room /
# Port / Vlan / Device since the `0007_add_timestamps` migration).
#
# Including `max(updated_at)` makes a pure UPDATE on those tables — e.g.
# `update_port` flipping admin_status or rewriting notes — change the
# fingerprint, so the AI features never serve a stale snapshot.
_TRACKED: list[tuple[Any, Any]] = [
    (Site, Site.updated_at),
    (Switch, Switch.updated_at),
    (Subnet, Subnet.updated_at),
    (Ip, Ip.updated_at),
    (Room, Room.updated_at),
    (Port, Port.updated_at),
    (Vlan, Vlan.updated_at),
    (Device, Device.updated_at),
    (Link, None),  # append-only, count alone is enough
]

_TTL_SECONDS = 300


class _SnapshotCache:
    """One-slot cache. We don't need LRU — there's only ever one "current"
    snapshot the AI features want, parameterised by the entire DB state."""

    __slots__ = ("_computed_at", "_context", "_fingerprint", "_lock")

    def __init__(self) -> None:
        self._fingerprint: str | None = None
        self._context: dict[str, Any] | None = None
        self._computed_at: float = 0.0
        self._lock = Lock()

    def get(self, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            if self._context is None or self._fingerprint != fingerprint:
                return None
            if time.monotonic() - self._computed_at > _TTL_SECONDS:
                # Expired — drop it so a future hit pays the rebuild cost
                # cleanly instead of returning stale data on the next call.
                self._fingerprint = None
                self._context = None
                return None
            return self._context

    def set(self, fingerprint: str, context: dict[str, Any]) -> None:
        with self._lock:
            self._fingerprint = fingerprint
            self._context = context
            self._computed_at = time.monotonic()

    def clear(self) -> None:
        with self._lock:
            self._fingerprint = None
            self._context = None


_CACHE = _SnapshotCache()


def reset_snapshot_cache() -> None:
    """Drop the cached snapshot. Used by tests; admins don't need this."""
    _CACHE.clear()


async def _compute_fingerprint(db: AsyncSession) -> str:
    """Cheap query: per-table `(count, max(updated_at))` → SHA-1 hex.

    Conceptually a single bulk select would be marginally faster, but a loop
    is much easier to evolve when a new table joins `_TRACKED` and the
    perf hit (~20-50 ms total) is dwarfed by the seconds-long LLM call we
    are about to make."""
    parts: list[str] = []
    for model, ts_col in _TRACKED:
        # `count(*)` is always available — covers rows-added scenarios.
        count_row = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        if ts_col is not None:
            ts_row = (await db.execute(select(func.max(ts_col)))).scalar_one()
            parts.append(f"{model.__tablename__}:{count_row}:{ts_row.isoformat() if ts_row else 'nil'}")
        else:
            parts.append(f"{model.__tablename__}:{count_row}")
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()


async def get_or_build_context(
    db: AsyncSession,
    *,
    builder: Callable[[AsyncSession], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], bool]:
    """Return `(context, was_cached)`. `builder` is the original
    `build_topology_context` — injected so this module stays import-cycle
    free."""
    fingerprint = await _compute_fingerprint(db)
    cached = _CACHE.get(fingerprint)
    if cached is not None:
        return cached, True
    context = await builder(db)
    _CACHE.set(fingerprint, context)
    return context, False
