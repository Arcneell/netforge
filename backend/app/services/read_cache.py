"""Redis cache for the expensive assembled read endpoints.

Which endpoints, and why those
------------------------------
Only reads whose cost is *assembly*, not row fetching:

  - `GET /api/topology` — 5 queries plus the grouping/parenting pass and a
    payload that can reach 500 nodes / 2000 edges. The SPA refetches it on
    every filter change (site, room, VLAN, devices on/off), so the same graph
    is rebuilt repeatedly while nothing has been written.
  - `GET /api/search` — one bounded query per entity type (seven of them) for
    a single term, refired as the operator types.
  - `GET /api/subnets/tree` — fetches every subnet in scope and assembles the
    hierarchy plus the auto-grouping supernets in Python.
  - `GET /api/subnets/capacity` — same full-scope fetch, aggregated.

Deliberately NOT cached: paginated list endpoints and single-row GETs. Their
cost is already one or two indexed queries, the parameter space (page, filters,
free text) makes the hit rate poor, and the fingerprint query below would be a
net loss on the cheapest of them. `compute_utilization` is two SELECTs and is
left alone for the same reason.

Correctness does not depend on invalidation
-------------------------------------------
The cache key embeds a *fingerprint* of the inventory tables, so a write
changes the key rather than requiring anyone to remember to evict. There is no
"bump a generation counter after the write commits" step, and therefore no
window in which the classic SPA flow — POST a switch, immediately refetch the
topology — can be served the pre-write graph. That race is the reason this
module fingerprints instead of invalidating: getting it wrong shows up as the
UI apparently losing a write, which is far worse than a lower hit rate.

The trade is one extra query per cached request. It is a single statement of
scalar subqueries over small tables (see `_fingerprint`), and it replaces
between five and seven queries plus the assembly pass on a hit.

`CACHE_READ_TTL_SECONDS` is therefore a memory bound, not a staleness bound:
entries for superseded fingerprints are unreachable the moment a write lands,
and the TTL is what stops them accumulating in Redis.

What the fingerprint covers
---------------------------
`_TRACKED` lists every table these endpoints read. Each contributes
`count(*)` plus a discriminator that changes when a row is modified in place:

  - `max(updated_at)` for the tables carrying `TimestampMixin`. Postgres
    manages the column, so any UPDATE moves it.
  - `max(id)` for `links`, which has no timestamps. `count(*)` alone would
    miss a delete-plus-insert inside one transaction; `max(id)` does not.
  - A weighted checksum for `port_vlan`, which has neither timestamps nor a
    surrogate id (composite PK). `count(*)` alone would miss swapping one
    tagged VLAN for another, which is exactly what the topology VLAN filter
    reads. The checksum is a collision-resistance-by-arithmetic trick, not a
    cryptographic hash — it catches every single-row edit, which is the shape
    every mutation in `services/ports.py` actually takes.

Adding a table to any of the cached builders means adding it here. A missing
entry is a stale-read bug, so keep the list a superset rather than trimming it
per endpoint: one global fingerprint means any write invalidates every cached
read, which costs hit rate and buys correctness that cannot be got wrong.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import get_settings
from app.models.cable import Cable
from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.link import Link
from app.models.port import Port, PortVlan
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan
from app.models.vrf import Vrf

logger = logging.getLogger("netforge.cache")

# Bumped when the key layout or the fingerprint composition changes, so a
# rolling deploy cannot read entries written under the old scheme. The app
# version is in the key too, which covers response-schema changes.
_SCHEMA_VERSION = 1

# Odd multiplier for the `port_vlan` checksum. Any value coprime with the
# vlan-id range works; a large prime keeps `port_id * K + vlan_id` from
# colliding across plausible (port, vlan) pairs.
_PORT_VLAN_WEIGHT = 1_000_003

# (model, discriminator) — see the module docstring for why each table gets
# the discriminator it does.
_TRACKED: list[tuple[Any, Any]] = [
    (Site, func.max(Site.updated_at)),
    (Room, func.max(Room.updated_at)),
    (Vlan, func.max(Vlan.updated_at)),
    (Vrf, func.max(Vrf.updated_at)),
    (Subnet, func.max(Subnet.updated_at)),
    (Ip, func.max(Ip.updated_at)),
    (Device, func.max(Device.updated_at)),
    (Switch, func.max(Switch.updated_at)),
    (Port, func.max(Port.updated_at)),
    (Cable, func.max(Cable.updated_at)),
    (Link, func.max(Link.id)),
    (PortVlan, func.sum(PortVlan.port_id * _PORT_VLAN_WEIGHT + PortVlan.vlan_id)),
]


async def _fingerprint(db: AsyncSession) -> str:
    """One statement, one round trip: `count(*)` + a discriminator per table.

    Rendered as `SELECT (SELECT count(*) FROM sites), (SELECT max(updated_at)
    FROM sites), ...` — a flat list of scalar subqueries with no FROM of its
    own. Deliberately not the per-table loop `services/ai/snapshot_cache.py`
    uses: that one runs ~17 round trips, which is fine ahead of a seconds-long
    LLM call and far too expensive on a read endpoint's critical path.
    """
    columns: list[Any] = []
    for model, discriminator in _TRACKED:
        columns.append(select(func.count()).select_from(model).scalar_subquery())
        columns.append(select(discriminator).scalar_subquery())
    row = (await db.execute(select(*columns))).one()
    raw = "|".join("nil" if value is None else str(value) for value in row)
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]


def _params_digest(params: Mapping[str, Any]) -> str:
    """Stable short digest of an endpoint's query parameters.

    `sort_keys` so `{a, b}` and `{b, a}` share an entry, `default=str` so an
    enum or date parameter cannot make the key unserialisable.
    """
    raw = json.dumps(dict(params), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _key(name: str, fingerprint: str, params: Mapping[str, Any]) -> str:
    return f"read:v{_SCHEMA_VERSION}:{__version__}:{name}:{fingerprint}:{_params_digest(params)}"


async def cached_read[T](
    db: AsyncSession,
    *,
    name: str,
    params: Mapping[str, Any],
    adapter: TypeAdapter[T],
    builder: Callable[[], Awaitable[T]],
) -> T:
    """Return `builder()`'s result, from Redis when an entry matches.

    `name` namespaces the endpoint and `params` covers everything that changes
    its output. `adapter` serialises and revalidates the payload, so a hit is
    indistinguishable from a miss both to the caller and to FastAPI's
    `response_model`. A `TypeAdapter` rather than a `BaseModel` subclass
    because `/api/subnets/tree` responds with a bare `list[SubnetTreeNode]`;
    callers keep theirs at module level since building one is not free.

    Falls straight through to `builder()` — without paying the fingerprint
    query — whenever reads are not cached: `CACHE_READS_ENABLED=false`, no
    `REDIS_URL`, or the cache breaker currently open. That ordering matters:
    a stack without Redis must not pay a single extra statement for the
    existence of this module.
    """
    from app import cache

    settings = get_settings()
    if not settings.cache_reads_enabled or not cache.cache_available():
        return await builder()

    try:
        fingerprint = await _fingerprint(db)
    except Exception:
        # The fingerprint is an optimisation; a failure here (an unexpected
        # dialect, a table missing mid-migration) must not fail the request
        # the builder can still serve.
        logger.warning("cache.read.fingerprint_failed name=%s", name, exc_info=True)
        return await builder()

    key = _key(name, fingerprint, params)
    payload = await cache.get_json(key)
    if payload is not None:
        try:
            return adapter.validate_python(payload)
        except Exception:
            # Written by a shape we no longer accept. Fall through and let the
            # fresh value overwrite it.
            logger.warning("cache.read.validate_failed name=%s", name)

    result = await builder()
    await cache.set_json(
        key,
        adapter.dump_python(result, mode="json"),
        ttl_seconds=settings.cache_read_ttl_seconds,
    )
    return result


__all__ = ["cached_read"]
