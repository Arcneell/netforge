"""Infra advisor — asks the LLM for actionable recommendations.

The advisor is run on-demand (button in the UI). Each run:
1. Builds a fuller snapshot than suggest_links (adds subnets + their usage,
   so capacity-style insights have the numbers they need).
2. Asks the model for up to ~20 insights via a strict JSON-Schema tool.
3. Persists the results into `infra_insights` keyed by the new
   `ai_run_logs.id` — the "latest" report is the rows sharing the most
   recent run id.

The previous run's rows are kept on purpose: an admin who wants to compare
last week's report can still query by `run_id`. The UI normally only shows
the latest set.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai import (
    AIRunKind,
    AIRunLog,
    InfraInsight,
    InsightCategory,
    InsightSeverity,
)
from app.services.ai.context import build_topology_context_cached
from app.services.ai.providers import get_provider
from app.services.ai.retry import call_with_retry
from app.services.ai.types import AIProviderError, ToolDef

SYSTEM_PROMPT = """You are a senior network architect reviewing a NetForge inventory
to flag risks and improvement opportunities. The operator pays for every token,
so be focused: surface real, actionable issues — not generic "consider using
a firewall" boilerplate.

Categories you can use (`category` field):
- spof: a single point of failure (one core switch, one uplink, one DHCP server).
- capacity: a subnet or switch close to exhaustion.
- security: management IPs on a user VLAN, default-route gaps, exposed services.
- segmentation: VLAN sprawl, missing isolation between trusted/untrusted zones.
- naming: inconsistencies in switch / room / VLAN naming that will hurt operations.
- redundancy: missing redundant paths, no second core, no STP, etc.
- other: anything that genuinely doesn't fit but is still worth flagging.

Severity guidance (`severity` field):
- critical: incident-likely if untouched (data loss, hard outage path, exposed mgmt).
- warning: real risk, but not imminent — capacity > 80 %, single uplink to core, etc.
- info: opportunity / cleanup — naming, documentation, low-stakes consolidation.

Hard rules:
- Each insight must reference at least one concrete entity from the snapshot.
- Up to 20 insights per run; quality > quantity. Drop everything you'd hesitate to put in a real ops report.
- Never invent entities — only use IDs and names present in the snapshot.
- Be specific: "switch SW-CORE-01 is the only path to room R-102" beats "consider redundancy".

Return your output via the `submit_insights` tool. Do not write prose around it.
"""

ADVISOR_TOOL = ToolDef(
    name="submit_insights",
    description=(
        "Submit the final list of infrastructure insights. Each insight must "
        "reference at least one real entity from the snapshot."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "insights": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["severity", "category", "title", "description"],
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["info", "warning", "critical"],
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "spof",
                                "capacity",
                                "security",
                                "segmentation",
                                "naming",
                                "redundancy",
                                "other",
                            ],
                        },
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": "string", "maxLength": 1500},
                        "recommendation": {"type": "string", "maxLength": 1500},
                        "affected_entities": {
                            "type": "array",
                            "maxItems": 20,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["type", "id"],
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "site",
                                            "room",
                                            "switch",
                                            "port",
                                            "vlan",
                                            "subnet",
                                            "device",
                                        ],
                                    },
                                    "id": {"type": "integer", "minimum": 1},
                                    "name": {"type": "string", "maxLength": 200},
                                },
                            },
                        },
                    },
                },
            },
        },
        "required": ["insights"],
    },
)


@dataclass
class AdvisorReport:
    run_id: int
    provider: str
    model: str
    raw_count: int
    persisted_count: int
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


async def run_advisor(
    db: AsyncSession,
    *,
    user_id: int | None,
    language_instruction: str | None = None,
) -> AdvisorReport:
    """Drive one advisor run end-to-end and persist insights.

    `language_instruction`, when supplied by the route from the request's
    Accept-Language header, is appended to the system prompt so the model
    answers in the same language the user is reading the UI in.
    """
    settings = get_settings()
    provider = get_provider()
    context, _was_cached = await build_topology_context_cached(db)
    payload = json.dumps(context, separators=(",", ":"), default=str)
    system = SYSTEM_PROMPT + (f"\n\n{language_instruction}" if language_instruction else "")

    t0 = time.monotonic()
    error: str | None = None
    error_exc: AIProviderError | None = None
    try:
        completion = await call_with_retry(
            lambda: provider.call(
                system=system,
                # Snapshot is the only thing in the user message — passing it
                # as `cache_prefix` so re-runs against unchanged infra hit the
                # Anthropic prompt cache.
                prompt="",
                cache_prefix=f"Network snapshot:\n```json\n{payload}\n```",
                tools=[ADVISOR_TOOL],
                max_tokens=settings.ai_max_output_tokens,
                temperature=0.3,
            )
        )
    except AIProviderError as exc:
        error = str(exc)
        error_exc = exc
        completion = None
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    run = AIRunLog(
        user_id=user_id,
        kind=AIRunKind.advisor,
        provider=provider.name,
        model=provider.model,
        prompt_tokens=completion.usage.prompt_tokens if completion else 0,
        completion_tokens=completion.usage.completion_tokens if completion else 0,
        latency_ms=elapsed_ms,
        success=error is None,
        error=error,
    )
    db.add(run)
    await db.flush()

    if not completion or not completion.tool_call:
        await db.commit()
        if error_exc:
            # Re-raise the ORIGINAL exception (not a re-wrapped generic
            # AIProviderError) so its concrete type — e.g.
            # `AIProviderRateLimitError` — survives to the router, which
            # maps it to a 429 instead of a generic 502.
            raise error_exc
        raise AIProviderError("provider returned no tool call")

    raw_items = completion.tool_call.input.get("insights", []) or []
    persisted = await _persist_insights(db, run_id=run.id, raw_items=raw_items)
    await db.commit()

    return AdvisorReport(
        run_id=run.id,
        provider=provider.name,
        model=provider.model,
        raw_count=len(raw_items),
        persisted_count=persisted,
        latency_ms=elapsed_ms,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
    )


async def _persist_insights(
    db: AsyncSession, *, run_id: int, raw_items: list[dict]
) -> int:
    rows: list[InfraInsight] = []
    for item in raw_items:
        try:
            severity = InsightSeverity(item["severity"])
            category = InsightCategory(item.get("category", "other"))
        except (KeyError, ValueError):
            continue
        title = str(item.get("title", "")).strip()[:200]
        description = str(item.get("description", "")).strip()[:1500]
        if not title or not description:
            continue
        recommendation = str(item.get("recommendation", "")).strip()[:1500]
        # We don't validate entity ids against the DB — the AI might reference
        # a recently-deleted entity, but the UI handles "name only" cards
        # gracefully so a stale id is not a crash, just a non-clickable chip.
        entities = item.get("affected_entities") or []
        if not isinstance(entities, list):
            entities = []
        rows.append(
            InfraInsight(
                run_id=run_id,
                severity=severity,
                category=category,
                title=title,
                description=description,
                recommendation=recommendation,
                affected_entities=entities,
            )
        )
    if not rows:
        return 0
    db.add_all(rows)
    await db.flush()
    return len(rows)


async def latest_run(db: AsyncSession) -> tuple[int, datetime] | None:
    """Return the (id, created_at) of the most recent successful advisor run,
    or `None` if none has succeeded yet."""
    row = (
        await db.execute(
            select(AIRunLog.id, AIRunLog.created_at)
            .where(AIRunLog.kind == AIRunKind.advisor, AIRunLog.success.is_(True))
            .order_by(desc(AIRunLog.created_at))
            .limit(1)
        )
    ).first()
    if not row:
        return None
    return row[0], row[1]


async def latest_run_id(db: AsyncSession) -> int | None:
    """Back-compat shim used by callers that only need the id."""
    pair = await latest_run(db)
    return pair[0] if pair else None


async def list_latest_insights(
    db: AsyncSession,
) -> tuple[int | None, datetime | None, list[InfraInsight]]:
    """Return `(run_id, run_created_at, insights)` for the latest successful run."""
    pair = await latest_run(db)
    if pair is None:
        return None, None, []
    run_id, created_at = pair
    items = (
        (
            await db.execute(
                select(InfraInsight)
                .where(InfraInsight.run_id == run_id)
                # Order by severity criticality, then by id for stability.
                .order_by(
                    InfraInsight.severity.desc(),
                    InfraInsight.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return run_id, created_at, list(items)


# Number of previous successful advisor runs we look back through when
# computing how often a finding has recurred. 4 = roughly a week of daily
# runs, which is enough to spot "this SPOF has been ignored for a week"
# without dragging the SELECT into pagination territory on busy installs.
_STREAK_LOOKBACK = 4


def _streak_key(item: InfraInsight) -> tuple[str, str]:
    """The matching key used to decide that two insights from different runs
    refer to the same underlying finding.

    `(category, title)` is the stable signature — the advisor prompt is
    deterministic enough that a recurring problem (e.g. "SPOF: SW-CORE-01
    is the only path to room R-102") produces the same title across runs
    when the underlying topology hasn't changed. Affected-entity matching
    would be more precise but the LLM occasionally rewords the title or
    swaps the entity order, which we'd rather treat as the same finding.
    """
    return (item.category.value, item.title.strip().lower())


async def compute_insight_streaks(
    db: AsyncSession,
    *,
    current_run_id: int,
    current_items: list[InfraInsight],
) -> dict[int, int]:
    """For every insight in `current_items`, count how many consecutive
    previous advisor runs (back to a `_STREAK_LOOKBACK`-deep window) also
    produced a matching insight. Returns `{insight_id: streak_count}` —
    the count includes the current run, so a brand-new finding gets `1`
    and one that's been around for three runs gets `3`.

    The query: pull the IDs of the most recent successful advisor runs
    (excluding the current one) in one SELECT, then for each, fetch the
    `(category, title)` tuples and check intersection with the current
    run's tuples. Two SELECTs total, both cheap because they index on
    `run_id`.
    """
    if not current_items:
        return {}

    # Walk back through previous successful advisor runs, stopping the
    # first time a current-finding doesn't appear — that's where its
    # streak ends.
    prev_run_rows = (
        await db.execute(
            select(AIRunLog.id)
            .where(
                AIRunLog.kind == AIRunKind.advisor,
                AIRunLog.success.is_(True),
                AIRunLog.id != current_run_id,
            )
            .order_by(desc(AIRunLog.created_at))
            .limit(_STREAK_LOOKBACK)
        )
    ).all()
    prev_run_ids = [int(r[0]) for r in prev_run_rows]

    streaks: dict[int, int] = {item.id: 1 for item in current_items}
    if not prev_run_ids:
        return streaks

    # Fetch all prior keys in one shot (grouped client-side), so we don't
    # pay N SELECTs for N runs back. The total is bounded:
    # `_STREAK_LOOKBACK * (advisor max insights = 20)` rows.
    prior_rows = (
        await db.execute(
            select(InfraInsight.run_id, InfraInsight.category, InfraInsight.title)
            .where(InfraInsight.run_id.in_(prev_run_ids))
        )
    ).all()
    per_run_keys: dict[int, set[tuple[str, str]]] = {}
    for row_run_id, category, title in prior_rows:
        per_run_keys.setdefault(int(row_run_id), set()).add(
            (
                category.value if hasattr(category, "value") else str(category),
                str(title).strip().lower(),
            )
        )

    # `prev_run_ids` is already in newest-first order; iterate forward in
    # time. For each current finding, increment the streak only while the
    # finding keeps appearing in consecutive prior runs.
    for item in current_items:
        key = _streak_key(item)
        for prev_id in prev_run_ids:
            if key in per_run_keys.get(prev_id, set()):
                streaks[item.id] += 1
            else:
                break
    return streaks
