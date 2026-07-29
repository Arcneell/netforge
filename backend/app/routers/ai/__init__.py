"""AI integration router — /api/ai.

This package is the split-up form of the former single `routers/ai.py`.
One submodule per surface; `router` below is the exact same object the
rest of the app used to import, mounted unchanged in `app.main`.

Surfaces:
- `common`        — feature-flag guards, rate-limit gate, shared 502 detail.
- `status`        — `GET /status`, `POST /test` (provider connectivity ping).
- `suggestions`   — link-suggestion scan / list / accept / reject.
- `insights`      — infrastructure advisor: cached report + refresh.
- `query`         — one-shot natural-language question (`POST /query`).
- `integrity`     — deterministic integrity checks (no LLM).
- `usage`         — AI usage dashboard aggregates.
- `csv_mapping`   — CSV column → NetForge field mapping assistant.
- `schedules`     — scheduled advisor / suggest-links runs.
- `drafts`        — NL-to-action drafts: draft / list / apply / reject.
- `pdf_export`    — advisor report rendered as PDF.
- `streaming`     — SSE variant of the NL query (`POST /query/stream`).
- `conversations` — persistent Ask-AI threads.

All write paths are admin-only and rate-limited.

NOTE — the `include_router` order below reproduces the route registration
order of the original module verbatim. Every path here is a literal (no
prefix shadowing), so ordering does not affect matching, but it *does*
drive the key order of the generated OpenAPI document, which the frontend
`schema.d.ts` is generated from. Keep new surfaces appended at the end
unless you deliberately want the schema to shuffle.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.ai import (
    conversations,
    csv_mapping,
    drafts,
    insights,
    integrity,
    pdf_export,
    query,
    schedules,
    status,
    streaming,
    suggestions,
    usage,
)

# Re-exported for callers (and tests) that reached into the old flat module
# for the feature-flag guards.
from app.routers.ai.common import (
    _GENERIC_502_DETAIL,
    _require_ai_enabled,
    _require_drafts_enabled,
    enforce_rate_limit,
    logger,
)

router = APIRouter(prefix="/ai", tags=["ai"])

router.include_router(status.router)
router.include_router(suggestions.router)
router.include_router(insights.router)
router.include_router(query.router)
router.include_router(integrity.router)
router.include_router(usage.router)
router.include_router(csv_mapping.router)
router.include_router(schedules.router)
router.include_router(drafts.router)
router.include_router(pdf_export.router)
router.include_router(streaming.router)
router.include_router(conversations.router)

__all__ = [
    "_GENERIC_502_DETAIL",
    "_require_ai_enabled",
    "_require_drafts_enabled",
    "conversations",
    "csv_mapping",
    "drafts",
    "enforce_rate_limit",
    "insights",
    "integrity",
    "logger",
    "pdf_export",
    "query",
    "router",
    "schedules",
    "status",
    "streaming",
    "suggestions",
    "usage",
]
