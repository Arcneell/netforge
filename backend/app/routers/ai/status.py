"""AI status + connectivity probe.

Two endpoints the Settings UI leans on before showing anything else:
`GET /ai/status` (is the feature on, and with which provider/model?) and
`POST /ai/test` (does the configured API key actually work?).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_role
from app.config import get_settings
from app.models.user import User, UserRole
from app.routers.ai.common import _require_ai_enabled, enforce_rate_limit
from app.schemas.ai import AIStatusRead, AITestResult
from app.services.ai import AIProviderError, get_provider

router = APIRouter()


@router.get("/status", response_model=AIStatusRead, dependencies=[Depends(get_current_user)])
async def get_status() -> AIStatusRead:
    """Reports current AI configuration. Never raises — even when disabled
    we return a 200 with `enabled=false` so the UI can branch cleanly."""
    settings = get_settings()
    return AIStatusRead(
        enabled=settings.ai_enabled,
        provider=settings.ai_provider,
        model=settings.ai_model or "(default for provider)",
        drafts_enabled=settings.ai_enabled and settings.ai_drafts_enabled,
        scheduler_enabled=settings.ai_enabled and settings.ai_scheduler_enabled,
    )


@router.post(
    "/test",
    response_model=AITestResult,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def test_connection(user: User = Depends(get_current_user)) -> AITestResult:
    """Tiny ping call to the configured provider. Used by the Settings UI
    to verify "is my API key valid?" without burning tokens on a full scan."""
    _require_ai_enabled()
    await enforce_rate_limit(user.id, retry_after_header=False)

    provider = get_provider()
    t0 = time.monotonic()
    try:
        completion = await provider.call(
            system="You are a connection-test assistant. Reply with the single word 'pong'.",
            prompt="ping",
            max_tokens=16,
            temperature=0.0,
        )
    except AIProviderError as exc:
        return AITestResult(
            ok=False,
            provider=provider.name,
            model=provider.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
    return AITestResult(
        ok=bool(completion.text or completion.tool_call),
        provider=provider.name,
        model=provider.model,
        latency_ms=int((time.monotonic() - t0) * 1000),
        error=None,
    )
