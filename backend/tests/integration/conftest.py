"""Fixtures for the Postgres integration suite.

These tests exercise the DB-side invariants (GiST exclusions, the
`subnets_validate_parent()` trigger) that SQLite / mocks cannot cover.
They only run when `NETFORGE_INTEGRATION_DB_URL` points at a disposable
PostgreSQL database (SQLAlchemy asyncpg URL, e.g.
`postgresql+asyncpg://netforge:dev@localhost:5433/netforge_it`):

    docker run --rm -d -p 5433:5432 -e POSTGRES_USER=netforge \
        -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=netforge_it postgres:16-alpine
    NETFORGE_INTEGRATION_DB_URL=postgresql+asyncpg://netforge:dev@localhost:5433/netforge_it \
        python -m pytest tests/integration

Without the variable every module in this package skips at collection
(`pytest.skip(allow_module_level=True)` in each test module) so the normal
unit suite stays green with zero external dependencies.

The `migrated_database` fixture applies `alembic upgrade head`
programmatically. `alembic/env.py` ignores the ini URL and reads
`app.config.get_settings().database_url`, so the override goes through the
`DATABASE_URL` env var + an lru_cache clear, and is restored afterwards.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

INTEGRATION_DB_URL_VAR = "NETFORGE_INTEGRATION_DB_URL"
INTEGRATION_REDIS_URL_VAR = "NETFORGE_INTEGRATION_REDIS_URL"

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def integration_db_url() -> str | None:
    """URL of the disposable Postgres, or None when the suite must skip."""
    return os.environ.get(INTEGRATION_DB_URL_VAR) or None


def integration_redis_url() -> str | None:
    """URL of the disposable Redis, or None when those modules must skip.

    Independent of the Postgres variable: the Redis modules test the counter
    script and the cache helpers, neither of which touches the database.

        docker run --rm -d -p 6380:6379 redis:7-alpine
        NETFORGE_INTEGRATION_REDIS_URL=redis://localhost:6380/0 \
            python -m pytest tests/integration
    """
    return os.environ.get(INTEGRATION_REDIS_URL_VAR) or None


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Apply `alembic upgrade head` on the integration database once.

    Yields the database URL. Session-scoped: migrations are idempotent to
    re-run but there is no point paying for them per test.
    """
    url = integration_db_url()
    if not url:  # Belt and braces — test modules already skip at collection.
        pytest.skip(f"{INTEGRATION_DB_URL_VAR} is not set")

    from alembic.config import Config

    from alembic import command
    from app.config import get_settings

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    # Resolve the script dir absolutely — the ini value is relative to the
    # process cwd, which is not necessarily backend/ under pytest.
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()

    yield url


@pytest.fixture
async def db(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """Fresh AsyncSession on a wiped inventory.

    Engine is created (and disposed) per test because asyncpg connections
    are bound to the event loop, and pytest-asyncio gives each test its own
    loop by default. NullPool keeps no cross-loop connections around.

    Only the tables this suite touches are wiped, children-first so the
    RESTRICT FKs (sites, vrfs) don't complain.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            for table in ("ips", "subnets", "vrfs", "sites"):
                await conn.execute(text(f"DELETE FROM {table}"))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
async def redis_client() -> AsyncIterator[object]:
    """A real async Redis client on a flushed database.

    Created per test because redis-py connections, like asyncpg's, are bound to
    the event loop and pytest-asyncio gives each test its own. `flushdb` rather
    than deleting known keys: this is a disposable instance, and a leftover
    counter from a previous test would silently change the budget under the
    next one.
    """
    url = integration_redis_url()
    if not url:  # Belt and braces — test modules already skip at collection.
        pytest.skip(f"{INTEGRATION_REDIS_URL_VAR} is not set")

    from redis.asyncio import Redis

    client = Redis.from_url(url, decode_responses=False)
    try:
        await client.flushdb()
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def site_id(db: AsyncSession) -> int:
    """One Site row — subnets.site_id is NOT NULL."""
    from app.models.core import Site

    site = Site(code="IT", name="Integration test site")
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site.id
