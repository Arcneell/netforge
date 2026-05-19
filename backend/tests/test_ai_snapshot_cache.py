"""Tests for the topology-snapshot cache wrapper.

We don't exercise the SQL fingerprint here — that's an integration concern
that needs a real DB. Instead we patch `_compute_fingerprint` to control
the cache key directly and verify the cache contract (hit / miss / TTL
expiry / fingerprint change).
"""

from __future__ import annotations

import pytest

from app.services.ai import snapshot_cache as sc


@pytest.fixture(autouse=True)
def _clean_cache():
    sc.reset_snapshot_cache()
    yield
    sc.reset_snapshot_cache()


@pytest.mark.asyncio
async def test_first_call_builds_then_second_call_hits_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sc, "_compute_fingerprint", _fixed_fingerprint("abc"))

    builds = 0

    async def fake_builder(db):
        nonlocal builds
        builds += 1
        return {"sites": [{"id": 1}]}

    ctx1, cached1 = await sc.get_or_build_context(_db_stub(), builder=fake_builder)
    ctx2, cached2 = await sc.get_or_build_context(_db_stub(), builder=fake_builder)
    assert builds == 1, "second call must hit the cache"
    assert cached1 is False
    assert cached2 is True
    assert ctx1 is ctx2  # same dict reference handed back


@pytest.mark.asyncio
async def test_fingerprint_change_invalidates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = iter(["abc", "abc", "xyz"])
    monkeypatch.setattr(sc, "_compute_fingerprint", _consumer(fingerprints))

    builds = 0

    async def fake_builder(db):
        nonlocal builds
        builds += 1
        return {"sites": [{"id": builds}]}

    await sc.get_or_build_context(_db_stub(), builder=fake_builder)
    _, cached_second = await sc.get_or_build_context(_db_stub(), builder=fake_builder)
    _, cached_third = await sc.get_or_build_context(_db_stub(), builder=fake_builder)
    assert cached_second is True
    assert cached_third is False
    assert builds == 2  # initial + fingerprint flip


@pytest.mark.asyncio
async def test_ttl_expiry_forces_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached entry older than the TTL must be dropped on lookup so the
    next call cleanly rebuilds without leaking the stale dict."""
    monkeypatch.setattr(sc, "_compute_fingerprint", _fixed_fingerprint("abc"))
    monkeypatch.setattr(sc, "_TTL_SECONDS", 1)
    # Patch the monotonic source so we can fast-forward without sleeping.
    clock = {"now": 100.0}
    monkeypatch.setattr(sc.time, "monotonic", lambda: clock["now"])

    builds = 0

    async def fake_builder(db):
        nonlocal builds
        builds += 1
        return {"builds": builds}

    await sc.get_or_build_context(_db_stub(), builder=fake_builder)
    clock["now"] = 200.0  # 100 s later, well past TTL
    _, cached = await sc.get_or_build_context(_db_stub(), builder=fake_builder)
    assert cached is False
    assert builds == 2


# --- helpers ----------------------------------------------------------------


class _DbStub:
    """`get_or_build_context` only forwards the db handle to the fake builder;
    nothing else is called on it."""


def _db_stub() -> _DbStub:
    return _DbStub()


def _fixed_fingerprint(value: str):
    async def _coro(_db) -> str:
        return value

    return _coro


def _consumer(values):
    async def _coro(_db) -> str:
        return next(values)

    return _coro
