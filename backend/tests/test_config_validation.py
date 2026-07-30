"""Boot-time validation of `RATE_LIMIT_STORE`.

Same posture as the CORS wildcard guard in `main.create_app` and the
PUBLIC_URL guard in `auth/dev.py`: a misconfiguration that silently degrades a
fleet-wide counter to a per-process one looks fine on a single-worker dev box
and quietly multiplies the effective cap in production, so it is worth
refusing to start over.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import RATE_LIMIT_STORES, Settings


def _settings(**overrides: object) -> Settings:
    # `_env_file=None` so a developer's own .env cannot influence the result.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize("store", sorted(RATE_LIMIT_STORES - {"redis"}))
def test_accepted_stores_that_need_nothing_else(store: str) -> None:
    assert _settings(rate_limit_store=store).rate_limit_store == store


def test_redis_store_is_accepted_with_a_url() -> None:
    settings = _settings(
        rate_limit_store="redis", redis_url="redis://localhost:6379/0"
    )
    assert settings.rate_limit_store == "redis"


def test_redis_store_without_a_url_refuses_to_boot() -> None:
    with pytest.raises(ValidationError, match="requires REDIS_URL"):
        _settings(rate_limit_store="redis")


def test_redis_store_with_a_blank_url_refuses_to_boot() -> None:
    with pytest.raises(ValidationError, match="requires REDIS_URL"):
        _settings(rate_limit_store="redis", redis_url="   ")


def test_an_unknown_store_refuses_to_boot() -> None:
    """A typo must not fall through to the per-process window."""
    with pytest.raises(ValidationError, match="is not one of"):
        _settings(rate_limit_store="postgres")


def test_the_store_value_is_normalised() -> None:
    """The call sites compare against lowercase literals, so an operator who
    writes `Database` must not silently land on the memory path."""
    assert _settings(rate_limit_store="  DataBase ").rate_limit_store == "database"


def test_declared_defaults_keep_redis_off() -> None:
    """Redis must be opt-in: a stock install has no cache and counts in Postgres.

    Reads the field defaults rather than a constructed instance — `conftest.py`
    exports `RATE_LIMIT_STORE=memory` for the whole unit suite, so an instance
    here would report the suite's override, not the shipped default.
    """
    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    assert defaults["redis_url"] == ""
    assert defaults["rate_limit_store"] == "database"


def test_cache_feature_flags_default_on_but_are_gated_by_the_url() -> None:
    """Both flags default to true; with no REDIS_URL they are inert anyway, which
    is what keeps the stack working without a cache."""
    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    assert defaults["cache_sessions_enabled"] is True
    assert defaults["cache_reads_enabled"] is True
    assert defaults["cache_session_ttl_seconds"] == 30
    assert defaults["cache_read_ttl_seconds"] == 300
