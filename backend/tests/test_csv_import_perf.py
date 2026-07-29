"""Query-count regression tests for the CSV importer.

These pin the O(rows × subnets) fix in `services.csv_import.refs`. They count
*statements*, never wall-clock time: a timing assertion would be flaky on CI
and would not actually describe the bug that was fixed.

The harness below is a hand-rolled fake session rather than `AsyncMock`
because we need two things a mock cannot give us: a stable statement log, and
enough of a store that the importer's own writes are visible to its later
reads (which is exactly what the reference cache has to stay honest about).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from app.models.core import Room, Site
from app.models.ip import Ip
from app.models.subnet import Subnet
from app.services import csv_import as service
from app.services.csv_import.refs import _SubnetIndex

# --------------------------------------------------------------------------- #
# Fake session
# --------------------------------------------------------------------------- #


def _eq_pairs(clause: Any) -> list[tuple[str, Any]]:
    """Flatten a `WHERE a = :x AND b = :y` clause into `[(column, value), ...]`.

    The importer only ever filters on equality against a natural key, so this
    covers every statement it emits.
    """
    if clause is None:
        return []
    if isinstance(clause, BooleanClauseList):
        out: list[tuple[str, Any]] = []
        for sub in clause.clauses:
            out.extend(_eq_pairs(sub))
        return out
    if isinstance(clause, BinaryExpression):
        return [(clause.left.key, clause.right.value)]
    return []


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


@dataclass
class _FakeSession:
    """In-memory stand-in for `AsyncSession` that logs every statement.

    `queries` holds one `(table, where_pairs)` entry per `execute()`; an empty
    `where_pairs` means a full-table scan, which is what the subnet
    containment lookup used to do once per row.
    """

    rows: dict[type, list[Any]] = field(default_factory=dict)
    queries: list[tuple[str, tuple[tuple[str, Any], ...]]] = field(default_factory=list)
    committed: bool = False
    rolled_back: bool = False
    _pending: list[Any] = field(default_factory=list)
    _next_id: int = 1000

    def seed(self, *objs: Any) -> None:
        for obj in objs:
            self.rows.setdefault(type(obj), []).append(obj)

    async def execute(self, stmt: Any, *_a: Any, **_kw: Any) -> _Result:
        model = stmt.column_descriptions[0]["entity"]
        pairs = _eq_pairs(stmt.whereclause)
        self.queries.append((model.__tablename__, tuple(pairs)))
        candidates = self.rows.get(model, [])
        matched = [
            r for r in candidates if all(getattr(r, k, None) == v for k, v in pairs)
        ]
        return _Result(matched)

    def add(self, obj: Any) -> None:
        self.rows.setdefault(type(obj), []).append(obj)
        self._pending.append(obj)

    async def delete(self, obj: Any) -> None:
        bucket = self.rows.get(type(obj), [])
        if obj in bucket:
            bucket.remove(obj)

    async def flush(self) -> None:
        for obj in self._pending:
            if getattr(obj, "id", None) is None:
                self._next_id += 1
                obj.id = self._next_id
        self._pending.clear()

    async def commit(self) -> None:
        await self.flush()
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    # -- assertions helpers ------------------------------------------------

    def scans(self, table: str) -> int:
        """Full-table reads (no WHERE) — the pathological shape."""
        return sum(1 for t, pairs in self.queries if t == table and not pairs)

    def hits(self, table: str) -> int:
        return sum(1 for t, _ in self.queries if t == table)

    def shapes(self) -> list[tuple[str, tuple[str, ...]]]:
        """The statement log with the bound values dropped."""
        return [(t, tuple(k for k, _ in pairs)) for t, pairs in self.queries]


def _csv(*lines: str) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


# --------------------------------------------------------------------------- #
# The fix: subnet containment is resolved from one snapshot, not one per row
# --------------------------------------------------------------------------- #


def _nth_subnet_prefix(i: int) -> str:
    """`10.a.b` for the i-th distinct /24 — two octets so M can exceed 256."""
    return f"10.{i // 256}.{i % 256}"


async def _import_ips(n_rows: int, n_subnets: int) -> _FakeSession:
    db = _FakeSession()
    db.seed(
        *[
            Subnet(id=i + 1, cidr=f"{_nth_subnet_prefix(i)}.0/24", site_id=1)
            for i in range(n_subnets)
        ]
    )
    lines = ["address;status"]
    for i in range(n_rows):
        prefix = _nth_subnet_prefix(i % n_subnets)
        lines.append(f"{prefix}.{(i % 200) + 10};assigned")
    report = await service.run_import(db, "ips", _csv(*lines), dry_run=True)
    assert report.ok_rows == n_rows, report.error_rows
    assert report.error_rows == []
    return db


@pytest.mark.asyncio
async def test_ip_import_reads_the_subnets_table_once_per_import() -> None:
    """`_find_subnet_for` used to run `SELECT * FROM subnets` for every single
    IP row — O(rows × subnets) rows dragged over the wire. It is now one read
    per import, whatever the row count.
    """
    for n_rows in (1, 10, 100):
        db = await _import_ips(n_rows=n_rows, n_subnets=50)
        assert db.scans("subnets") == 1
        # One statement for the snapshot + the per-row upsert probe on `ips`.
        # Before the fix this was `2 * n_rows`.
        assert len(db.queries) == 1 + n_rows


@pytest.mark.asyncio
async def test_ip_import_query_count_does_not_grow_with_subnet_count() -> None:
    """The whole point of the index: the cost of resolving an address stops
    depending on how many subnets the inventory holds."""
    small = await _import_ips(n_rows=25, n_subnets=4)
    large = await _import_ips(n_rows=25, n_subnets=400)

    # Same statements in the same order — only the bound addresses differ.
    assert small.shapes() == large.shapes()
    assert small.scans("subnets") == 1
    assert large.scans("subnets") == 1


@pytest.mark.asyncio
async def test_reference_lookups_are_memoised_per_distinct_key() -> None:
    """`site_code` / `room_code` repeated on every row cost one statement for
    the whole file, not one per row."""
    db = _FakeSession()
    db.seed(Site(id=1, code="HQ", name="HQ"), Room(id=7, site_id=1, code="SRV-1"))

    lines = ["name;type;site_code;room_code"]
    for i in range(40):
        lines.append(f"srv-{i:03d};server;HQ;SRV-1")

    report = await service.run_import(db, "devices", _csv(*lines), dry_run=True)
    assert report.ok_rows == 40, report.error_rows

    assert db.hits("sites") == 1
    assert db.hits("rooms") == 1
    # Only the per-row upsert probe on `devices` scales with the file.
    assert db.hits("devices") == 40


# --------------------------------------------------------------------------- #
# The cache must not go stale behind the import's own writes
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cache_sees_entities_created_earlier_in_the_same_import() -> None:
    """A bulk upload that creates a site and then a room pointing at it must
    still resolve — the negative entry cached on the first miss is replaced by
    the freshly created object, not left to rot."""
    db = _FakeSession()
    report = await service.run_bulk_import(
        db,
        [
            ("sites.csv", _csv("code;name", "HQ;Headquarters")),
            ("rooms.csv", _csv("site_code;code;description", "HQ;SRV-1;Server room")),
        ],
        dry_run=False,
    )
    assert report.applied is True
    assert report.total_ok_rows == 2, report.files

    created_site = db.rows[Site][0]
    created_room = db.rows[Room][0]
    assert created_room.site_id == created_site.id
    # `rooms.csv` resolved `HQ` from the cache: the only `sites` statement is
    # the upsert probe issued while importing `sites.csv` itself.
    assert db.hits("sites") == 1


@pytest.mark.asyncio
async def test_subnet_index_is_rebuilt_after_the_import_creates_a_subnet() -> None:
    """`subnets.csv` followed by `ips.csv` in one transaction: the containment
    index snapshotted before the insert would miss the new CIDR, so any subnet
    upsert invalidates it."""
    db = _FakeSession()
    db.seed(Site(id=1, code="HQ", name="HQ"))
    report = await service.run_bulk_import(
        db,
        [
            ("subnets.csv", _csv("cidr;site_code", "192.168.7.0/24;HQ")),
            ("ips.csv", _csv("address;status", "192.168.7.42;assigned")),
        ],
        dry_run=False,
    )
    assert report.applied is True
    assert report.total_ok_rows == 2, report.files

    created_ip = db.rows[Ip][0]
    created_subnet = db.rows[Subnet][0]
    assert created_ip.subnet_id == created_subnet.id
    # The index is rebuilt lazily: invalidating it while importing
    # `subnets.csv` costs nothing until `ips.csv` actually needs a lookup.
    assert db.scans("subnets") == 1


# --------------------------------------------------------------------------- #
# `_SubnetIndex` reproduces the old linear scan exactly
# --------------------------------------------------------------------------- #


def test_subnet_index_returns_first_containing_row_not_the_most_specific() -> None:
    """The pre-refactor loop returned the first containing row in DB order,
    so a supernet listed before its child won. Nested-subnet resolution must
    keep behaving that way — switching to longest-prefix-match here would
    silently re-home existing IPs."""
    supernet = Subnet(id=1, cidr="10.0.0.0/16", site_id=1)
    child = Subnet(id=2, cidr="10.0.30.0/24", site_id=1)

    from ipaddress import IPv4Address

    assert _SubnetIndex([supernet, child]).find(IPv4Address("10.0.30.5")) is supernet
    assert _SubnetIndex([child, supernet]).find(IPv4Address("10.0.30.5")) is child


def test_subnet_index_keeps_the_first_row_when_a_cidr_repeats_across_vrfs() -> None:
    """Two VRFs may hold the same CIDR (the GiST exclusion is partitioned by
    `vrf_id`). The old scan took whichever row came back first and did no VRF
    filtering at all; so does the index."""
    from ipaddress import IPv4Address

    global_vrf = Subnet(id=1, cidr="172.16.0.0/24", site_id=1, vrf_id=None)
    tenant_vrf = Subnet(id=2, cidr="172.16.0.0/24", site_id=1, vrf_id=9)

    index = _SubnetIndex([global_vrf, tenant_vrf])
    assert index.find(IPv4Address("172.16.0.9")) is global_vrf


def test_subnet_index_returns_none_when_nothing_contains_the_address() -> None:
    from ipaddress import IPv4Address

    index = _SubnetIndex([Subnet(id=1, cidr="10.0.0.0/24", site_id=1)])
    assert index.find(IPv4Address("192.0.2.1")) is None
    assert _SubnetIndex([]).find(IPv4Address("10.0.0.1")) is None


def test_subnet_index_handles_the_default_route_and_host_prefixes() -> None:
    """Prefix lengths 0 and 32 exercise the mask arithmetic at both ends."""
    from ipaddress import IPv4Address

    default = Subnet(id=1, cidr="0.0.0.0/0", site_id=1)
    host = Subnet(id=2, cidr="10.0.0.7/32", site_id=1)

    assert _SubnetIndex([host, default]).find(IPv4Address("10.0.0.7")) is host
    assert _SubnetIndex([host, default]).find(IPv4Address("10.0.0.8")) is default


def test_subnet_index_matches_non_canonical_stored_cidrs() -> None:
    """Rows are parsed with `strict=False`, same as the old scan, so a CIDR
    stored with host bits set still resolves."""
    from ipaddress import IPv4Address

    sloppy = Subnet(id=1, cidr="10.0.5.42/24", site_id=1)
    assert _SubnetIndex([sloppy]).find(IPv4Address("10.0.5.1")) is sloppy
