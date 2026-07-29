"""Deterministic integrity checks — `GET /ai/integrity-checks`.

Lives under /ai because the UI groups it with the advisor, but it never
touches an LLM: the rules are hard-coded and the wording is translated
locally. That is why it stays up even when AI is disabled.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.ai import IntegrityIssueRead, IntegrityReportRead
from app.services.ai.integrity import run_all_checks

router = APIRouter()


@router.get(
    "/integrity-checks",
    response_model=IntegrityReportRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def get_integrity_checks(
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> IntegrityReportRead:
    """Run the deterministic integrity checks (no LLM round-trip).

    Always returns a 200 — even when AI is disabled this endpoint stays up
    because it does not call any external provider. `Accept-Language`
    drives the issue titles + descriptions (FR/EN baked in)."""
    issues = await run_all_checks(db, accept_language=accept_language)
    return IntegrityReportRead(
        issues=[
            IntegrityIssueRead(
                severity=i.severity,
                category=i.category,
                title=i.title,
                description=i.description,
                recommendation=i.recommendation,
                affected_entities=i.affected_entities,
            )
            for i in issues
        ]
    )
