"""Tests for the canonical AI error format + provider-error-to-HTTP mapping
(HIGH audit fix): a provider rate-limit must surface as a 429, everything
else the router doesn't explicitly recognise must surface as a generic 502
that never echoes raw provider/SDK text, and every response must use the
`{"error": {"code", "message"}}` shape the rest of the app already uses.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers.ai.common import (
    _GENERIC_502_DETAIL,
    _RATE_LIMITED_DETAIL,
    raise_ai_error,
)
from app.services.ai.types import (
    AIProviderError,
    AIProviderRateLimitError,
    AIUnsupportedFeatureError,
)


def _detail_of(exc: HTTPException) -> dict:
    assert isinstance(exc.detail, dict)
    return exc.detail["error"]


def test_unsupported_feature_maps_to_501() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_ai_error(AIUnsupportedFeatureError("gemini tools not supported"), context="x")
    assert exc.value.status_code == 501
    err = _detail_of(exc.value)
    assert err["code"] == "AI_UNSUPPORTED_FEATURE"
    assert "gemini tools not supported" in err["message"]


def test_rate_limit_error_maps_to_429_with_generic_message() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_ai_error(
            AIProviderRateLimitError("anthropic API call failed (rate limited): 429 too many requests"),
            context="nl-query",
        )
    assert exc.value.status_code == 429
    err = _detail_of(exc.value)
    assert err["code"] == "AI_RATE_LIMITED"
    assert err["message"] == _RATE_LIMITED_DETAIL
    # The raw provider text must not leak into the client-facing message.
    assert "429 too many requests" not in err["message"]


def test_generic_provider_error_maps_to_502_without_leaking_detail() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_ai_error(
            AIProviderError("anthropic API call failed: connection reset by peer"),
            context="advisor run",
        )
    assert exc.value.status_code == 502
    err = _detail_of(exc.value)
    assert err["code"] == "AI_PROVIDER_ERROR"
    assert err["message"] == _GENERIC_502_DETAIL
    assert "connection reset" not in err["message"]


def test_unexpected_exception_maps_to_502_without_leaking_detail() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_ai_error(RuntimeError("DSN=postgresql://user:pw@host/db"), context="csv-mapping")
    assert exc.value.status_code == 502
    err = _detail_of(exc.value)
    assert err["code"] == "AI_PROVIDER_ERROR"
    assert "DSN" not in err["message"]
    assert "user:pw" not in err["message"]


# --- Type preservation through the service layer's re-raise ----------------
#
# advisor.py / suggest_links.py / csv_mapping.py / nl_query.py / actions.py
# all catch the provider exception around the LLM call, then (on "no tool
# call" / empty completion) used to re-wrap it as a brand-new
# `AIProviderError(str(original))` — which silently downgraded a rate-limit
# failure to a generic error by the time the router saw it. They must now
# re-raise the ORIGINAL exception object so its concrete type survives.


@pytest.mark.asyncio
async def test_advisor_preserves_rate_limit_error_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.ai import advisor

    async def fake_call(**_kwargs):
        raise AIProviderRateLimitError("slow down")

    fake_provider = SimpleNamespace(name="anthropic", model="m", call=fake_call)
    monkeypatch.setattr(advisor, "get_provider", lambda: fake_provider)
    monkeypatch.setattr(
        advisor,
        "build_topology_context_cached",
        AsyncMock(return_value=({"sites": []}, False)),
    )
    # `call_with_retry` retries once on rate limit — patch the sleep away
    # and let the second attempt raise the same typed error again so we
    # don't need a real timer in the test.
    import asyncio

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    with pytest.raises(AIProviderRateLimitError):
        await advisor.run_advisor(db, user_id=1)
