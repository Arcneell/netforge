"""CSV mapping assistant — `POST /ai/csv/suggest-mapping`.

Guesses which NetForge field each column of an uploaded CSV corresponds
to. Advisory only: the operator still renames their headers and runs the
canonical import pipeline afterwards.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.routers.ai.common import (
    _GENERIC_502_DETAIL,
    _require_ai_enabled,
    enforce_rate_limit,
    logger,
)
from app.schemas.ai import (
    CsvColumnMapping,
    CsvDataQualityIssue,
    CsvMappingRequest,
    CsvMappingResponse,
)
from app.services.ai import AIProviderError, AIUnsupportedFeatureError
from app.services.ai.csv_mapping import list_canonical_fields, run_mapping_suggestion
from app.services.ai.locale import language_instruction as _lang_for

router = APIRouter()


@router.post(
    "/csv/suggest-mapping",
    response_model=CsvMappingResponse,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def suggest_csv_mapping(
    payload: CsvMappingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> CsvMappingResponse:
    """Ask the model to guess which NetForge field each CSV column maps to.

    Pure suggestion — the operator still renames their headers and runs the
    canonical import pipeline. Counts against the AI rate limit because it
    burns a full LLM call.
    """
    _require_ai_enabled()
    await enforce_rate_limit(user.id)

    if not list_canonical_fields(payload.entity):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"unknown entity for mapping: {payload.entity!r}",
        )

    try:
        result = await run_mapping_suggestion(
            db,
            user_id=user.id,
            entity=payload.entity,
            csv_columns=payload.csv_columns,
            sample_rows=payload.sample_rows,
            language_instruction=_lang_for(accept_language),
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("csv-mapping crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=_GENERIC_502_DETAIL,
        ) from exc

    return CsvMappingResponse(
        entity=result.entity,
        columns=[CsvColumnMapping(**c.__dict__) for c in result.columns],
        missing_required_fields=result.missing_required_fields,
        data_quality=[CsvDataQualityIssue(**i.__dict__) for i in result.data_quality],
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
