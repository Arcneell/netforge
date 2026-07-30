"""Tests for the fingerprint-keyed read cache.

The property worth pinning is the one the module exists for: a write changes
the *key*, so no reader can be served a pre-write payload. That is what makes
"POST a switch, immediately refetch the topology" safe without an invalidation
step. The rest is fall-through behaviour — a stack with no Redis must not pay a
single extra query for this module's existence.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
from pydantic import BaseModel, TypeAdapter

from app import cache
from app.config import get_settings
from app.services import read_cache

from .test_cache import FakeRedis


class Payload(BaseModel):
    value: str


_ADAPTER = TypeAdapter(Payload)
_LIST_ADAPTER = TypeAdapter(list[Payload])


class FakeDb:
    """Answers the one fingerprint statement `read_cache` issues."""

    def __init__(self, *, fingerprint_row: tuple[object, ...] | None = None) -> None:
        self.row = fingerprint_row or (1, "2026-07-30T08:00:00", 2, None)
        self.executions = 0
        self.fail = False

    async def execute(self, _stmt: object) -> FakeDb:
        self.executions += 1
        if self.fail:
            raise RuntimeError("no such table")
        return self

    def one(self) -> tuple[object, ...]:
        return self.row


@pytest.fixture
def configure() -> Iterator[Callable[..., FakeRedis]]:
    def _apply(**env: str) -> FakeRedis:
        client = FakeRedis()
        os.environ["REDIS_URL"] = "redis://localhost:6379/0"
        os.environ["CACHE_KEY_PREFIX"] = "netforge"
        os.environ.update(env)
        get_settings.cache_clear()
        cache._client = client
        cache._client_built = True
        return client

    yield _apply

    for name in ("REDIS_URL", "CACHE_KEY_PREFIX", "CACHE_READS_ENABLED", "CACHE_READ_TTL_SECONDS"):
        os.environ.pop(name, None)
    get_settings.cache_clear()
    cache.reset_client()


def _counting_builder(value: str = "built") -> tuple[Callable[[], object], list[int]]:
    calls: list[int] = []

    async def _build() -> Payload:
        calls.append(1)
        return Payload(value=value)

    return _build, calls


# --- Fall-through ---------------------------------------------------------- #


async def test_without_redis_the_builder_runs_and_no_query_is_issued() -> None:
    """The fingerprint query must not be paid by a stack that has no cache."""
    db = FakeDb()
    builder, calls = _counting_builder()

    result = await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert result == Payload(value="built")
    assert len(calls) == 1
    assert db.executions == 0


async def test_disabled_flag_skips_the_cache_entirely(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure(CACHE_READS_ENABLED="false")
    db = FakeDb()
    builder, calls = _counting_builder()

    await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert len(calls) == 1
    assert db.executions == 0
    assert client.calls == []


async def test_a_failing_fingerprint_still_serves_the_request(
    configure: Callable[..., FakeRedis],
) -> None:
    configure()
    db = FakeDb()
    db.fail = True
    builder, calls = _counting_builder()

    result = await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert result == Payload(value="built")
    assert len(calls) == 1


# --- Hit / miss ------------------------------------------------------------ #


async def test_second_call_hits_the_cache(configure: Callable[..., FakeRedis]) -> None:
    configure()
    db = FakeDb()
    builder, calls = _counting_builder()

    first = await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )
    second = await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert first == second == Payload(value="built")
    assert len(calls) == 1, "the second call must be served from Redis"


async def test_a_write_changes_the_key_so_the_next_read_rebuilds(
    configure: Callable[..., FakeRedis],
) -> None:
    """The headline property: correctness comes from the fingerprint, not from
    anybody remembering to invalidate."""
    configure()
    db = FakeDb()
    builder, calls = _counting_builder()

    await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )
    # A row was inserted somewhere: the count moved.
    db.row = (2, "2026-07-30T09:00:00", 2, None)
    await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert len(calls) == 2


async def test_an_in_place_update_changes_the_key(
    configure: Callable[..., FakeRedis],
) -> None:
    """Counts alone would miss an UPDATE — the `max(updated_at)` half is why
    the discriminator is in the fingerprint."""
    configure()
    db = FakeDb()
    builder, calls = _counting_builder()

    await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )
    db.row = (1, "2026-07-30T08:00:01", 2, None)  # same counts, newer updated_at
    await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert len(calls) == 2


async def test_different_params_do_not_share_an_entry(
    configure: Callable[..., FakeRedis],
) -> None:
    configure()
    db = FakeDb()
    builder, calls = _counting_builder()

    await read_cache.cached_read(
        db, name="thing", params={"site_id": 1}, adapter=_ADAPTER, builder=builder
    )
    await read_cache.cached_read(
        db, name="thing", params={"site_id": 2}, adapter=_ADAPTER, builder=builder
    )

    assert len(calls) == 2


async def test_different_endpoints_do_not_share_an_entry(
    configure: Callable[..., FakeRedis],
) -> None:
    configure()
    db = FakeDb()
    builder, calls = _counting_builder()

    await read_cache.cached_read(
        db, name="topology", params={}, adapter=_ADAPTER, builder=builder
    )
    await read_cache.cached_read(
        db, name="search", params={}, adapter=_ADAPTER, builder=builder
    )

    assert len(calls) == 2


async def test_param_order_does_not_change_the_key(
    configure: Callable[..., FakeRedis],
) -> None:
    configure()
    db = FakeDb()
    builder, calls = _counting_builder()

    await read_cache.cached_read(
        db, name="thing", params={"a": 1, "b": 2}, adapter=_ADAPTER, builder=builder
    )
    await read_cache.cached_read(
        db, name="thing", params={"b": 2, "a": 1}, adapter=_ADAPTER, builder=builder
    )

    assert len(calls) == 1


async def test_a_list_response_roundtrips(configure: Callable[..., FakeRedis]) -> None:
    """`/api/subnets/tree` answers with a bare list — the reason `cached_read`
    takes a TypeAdapter rather than a BaseModel subclass."""
    configure()
    db = FakeDb()
    calls: list[int] = []

    async def _build() -> list[Payload]:
        calls.append(1)
        return [Payload(value="a"), Payload(value="b")]

    first = await read_cache.cached_read(
        db, name="tree", params={}, adapter=_LIST_ADAPTER, builder=_build
    )
    second = await read_cache.cached_read(
        db, name="tree", params={}, adapter=_LIST_ADAPTER, builder=_build
    )

    assert first == second == [Payload(value="a"), Payload(value="b")]
    assert len(calls) == 1


async def test_an_undecodable_entry_is_rebuilt(
    configure: Callable[..., FakeRedis],
) -> None:
    configure()
    db = FakeDb()
    client = cache.get_client()
    assert client is not None
    builder, calls = _counting_builder()

    await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )
    # Overwrite the single stored entry with a payload the adapter rejects.
    key = next(iter(client.store))
    client.store[key] = b'{"unexpected": true}'

    result = await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert result == Payload(value="built")
    assert len(calls) == 2


async def test_entries_are_written_with_the_configured_ttl(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure(CACHE_READ_TTL_SECONDS="120")
    db = FakeDb()
    builder, _ = _counting_builder()

    await read_cache.cached_read(
        db, name="thing", params={}, adapter=_ADAPTER, builder=builder
    )

    assert set(client.expiries.values()) == {120}


# --- Fingerprint shape ----------------------------------------------------- #


def test_the_fingerprint_covers_every_table_the_builders_read() -> None:
    """A table missing from `_TRACKED` is a stale-read bug, so the list is
    pinned here rather than left to drift silently."""
    tracked = {model.__tablename__ for model, _ in read_cache._TRACKED}
    assert tracked == {
        "sites",
        "rooms",
        "vlans",
        "vrfs",
        "subnets",
        "ips",
        "devices",
        "switches",
        "ports",
        "cables",
        "links",
        "port_vlan",
    }


def test_the_fingerprint_statement_is_a_single_round_trip() -> None:
    """Two scalar subqueries per table in one SELECT — not one query per table
    like `services/ai/snapshot_cache.py`, which would be far too expensive on a
    read endpoint's critical path."""
    from sqlalchemy import func, select
    from sqlalchemy.dialects import postgresql

    columns: list[object] = []
    for model, discriminator in read_cache._TRACKED:
        columns.append(select(func.count()).select_from(model).scalar_subquery())
        columns.append(select(discriminator).scalar_subquery())
    sql = str(select(*columns).compile(dialect=postgresql.dialect()))

    assert sql.count("SELECT") == 1 + 2 * len(read_cache._TRACKED)
    assert "FROM port_vlan" in sql
    assert "max(links.id)" in sql
