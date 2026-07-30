"""Shared plumbing for the `/api/ai` router package.

Everything every AI surface needs and nothing route-specific:

- the feature-flag guards (`_require_ai_enabled`, `_require_drafts_enabled`),
- the per-user rate-limit gate (`enforce_rate_limit`),
- the generic 502 detail string,
- the `netforge.ai` logger.

Keeping them in one module means a change to the "is AI on?" policy or to
the 429 wire format lands on every endpoint at once instead of drifting
between submodules.
"""

from __future__ import annotations

import logging
from typing import NoReturn

from fastapi import HTTPException, status

from app.config import get_settings
from app.services.ai.rate_limit import AIRateLimitExceeded, consume_ai_quota
from app.services.ai.types import (
    AIProviderError,
    AIProviderRateLimitError,
    AIUnsupportedFeatureError,
)
from app.services.errors import http_error

logger = logging.getLogger("netforge.ai")

# Client-facing detail for unexpected 502s. The real exception (type,
# message, traceback) is always logged server-side via logger.exception —
# echoing `f"{type(exc).__name__}: {exc}"` to the client leaked internals
# (connection strings, file paths, provider error payloads).
_GENERIC_502_DETAIL = (
    "AI request failed unexpectedly — details are in the server logs."
)

# Client-facing detail for a 429 caused by the *provider* rate-limiting us
# (as opposed to our own per-user quota — see `enforce_rate_limit`, which
# has its own message carrying `retry_after_seconds`).
_RATE_LIMITED_DETAIL = (
    "The AI provider is rate limiting requests right now — try again in a moment."
)


def _require_ai_enabled() -> None:
    settings = get_settings()
    if not settings.ai_enabled:
        # 404 (not 503) so an unauthenticated probe can't fingerprint the
        # feature — matches how we hide /api/auth/dev when AUTH_PROVIDER!=dev.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="AI not enabled")


def _require_drafts_enabled() -> None:
    """NL-to-action is the riskiest AI surface (apply mutates inventory).
    Returns 404 — same fingerprint-safe pattern as the master switch."""
    settings = get_settings()
    if not settings.ai_enabled or not settings.ai_drafts_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="AI drafts not enabled")


async def enforce_rate_limit(user_id: int, *, retry_after_header: bool = True) -> None:
    """Consume one slot of the caller's AI budget, or raise 429.

    `retry_after_header=False` is only used by `POST /ai/test`, which has
    always answered without a `Retry-After` header. The flag keeps that
    historical wire shape intact rather than silently widening the
    response of an endpoint the Settings UI polls.
    """
    try:
        await consume_ai_quota(user_id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
            headers=(
                {"Retry-After": str(exc.retry_after_seconds)}
                if retry_after_header
                else None
            ),
        ) from exc


def raise_ai_error(exc: Exception, *, context: str) -> NoReturn:
    """Translate a caught AI-layer exception into the canonical
    `{"error": {"code", "message"}}` shape every other router already uses
    (see `app/services/errors.py`), and never echo raw provider text to the
    client — SDK error bodies can carry internals (endpoints, request ids,
    occasionally more). The exception detail always goes to the server log;
    `context` is a short label for that log line (e.g. "nl-query").

    Call this from a single `except Exception as exc:` at the bottom of a
    route's try block — it discriminates the AI exception hierarchy itself:
    - `AIUnsupportedFeatureError` -> 501 (message is a static "not
      implemented" string, safe to show as-is).
    - `AIProviderRateLimitError` -> 429, so the client can back off and
      retry, distinct from the generic 502 below.
    - `AIProviderError` (anything else from a provider) -> 502, generic
      message.
    - Anything else -> 502, generic message, full traceback logged.
    """
    if isinstance(exc, AIUnsupportedFeatureError):
        http_error(status.HTTP_501_NOT_IMPLEMENTED, "AI_UNSUPPORTED_FEATURE", str(exc))
    if isinstance(exc, AIProviderRateLimitError):
        logger.warning("%s: rate limited by provider: %s", context, exc)
        http_error(status.HTTP_429_TOO_MANY_REQUESTS, "AI_RATE_LIMITED", _RATE_LIMITED_DETAIL)
    if isinstance(exc, AIProviderError):
        logger.warning("%s: provider error: %s", context, exc)
        http_error(status.HTTP_502_BAD_GATEWAY, "AI_PROVIDER_ERROR", _GENERIC_502_DETAIL)
    logger.exception("%s crashed", context)
    http_error(status.HTTP_502_BAD_GATEWAY, "AI_PROVIDER_ERROR", _GENERIC_502_DETAIL)
