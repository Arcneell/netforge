"""PDF export of the advisor report — `GET /ai/insights/export.pdf`.

Separate from `insights.py` because it is the only AI route that answers
with a binary body instead of a JSON model, and it pulls in the fpdf2
renderer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.routers.ai.common import _require_ai_enabled
from app.services.ai.advisor import list_latest_insights

# Re-use the parsing logic the locale shim already implements.
from app.services.ai.locale import _parse_primary_tag
from app.services.ai.pdf_export import build_filename as _pdf_filename
from app.services.ai.pdf_export import render_advisor_report
from app.services.errors import http_error

router = APIRouter()


@router.get(
    "/insights/export.pdf",
    response_class=Response,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def export_insights_pdf(
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> Response:
    """Render the latest advisor report as a PDF.

    Gated on `AI_ENABLED` — same pattern as the rest of the advisor surface.
    Returns 404 when AI is disabled or when no advisor run has ever
    succeeded (matches the empty state the UI already handles). The PDF is
    rendered in the operator's UI language — FR/EN, falls back to EN.
    """
    _require_ai_enabled()
    run_id, run_created_at, items = await list_latest_insights(db)
    if run_id is None:
        http_error(
            status.HTTP_404_NOT_FOUND,
            "NO_ADVISOR_RUN",
            "no advisor run has succeeded yet",
        )
    locale = _parse_primary_tag(accept_language)
    pdf_bytes = render_advisor_report(
        run_created_at=run_created_at,
        insights=items,
        locale=locale,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_pdf_filename(run_created_at)}"',
        },
    )
