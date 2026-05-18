"""Suggest topological links between switch ports using AI.

Workflow:
1. Build a structured snapshot of the network (sites/rooms/switches/ports/links/vlans).
2. Hand it to the configured provider with a strict JSON-Schema tool —
   the model is forced to call the tool, so we never have to parse prose.
3. Validate every candidate suggestion (ports exist, distinct, canonical
   order, no existing link, no existing pending suggestion for the pair).
4. Persist the survivors as `link_suggestions(status='pending')`.

The route layer handles auth + rate limiting; this module focuses on the
LLM round-trip + persistence.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai import AIRunKind, AIRunLog, LinkSuggestion, LinkSuggestionStatus
from app.models.link import Link
from app.models.port import Port
from app.services.ai.context import build_topology_context
from app.services.ai.providers import get_provider
from app.services.ai.types import AIProviderError, ToolDef

SYSTEM_PROMPT = """You are a senior network engineer helping operators find missing
physical links in a network topology stored in NetForge.

Your job: read the supplied JSON snapshot (sites, rooms, switches, ports,
existing links, vlans) and identify probable PORT-TO-PORT links between
switches that ARE NOT YET in the `existing_links` array.

Strong signals (any of these = high confidence ≥ 0.7):
- A port's `label` or `notes` mentions another switch by name and a port number
  ("to-SW-CORE-01:gi1/0/24" / "uplink to HQ-CORE-02 port 12").
- Two trunk ports on different switches share the same VLAN profile and
  are in adjacent rooms / the same site.
- Switch naming convention pairs (SW-EDGE-01 → SW-CORE-01) with matching
  port labels.

Weak signals (use confidence 0.3–0.6):
- Hostname / description hints without a clear port number.
- Pure VLAN-overlap without textual cues.

Hard rules:
- NEVER suggest a link if the same (port_a_id, port_b_id) pair already
  appears in `existing_links` — those are already recorded.
- NEVER suggest two ports on the SAME switch.
- NEVER suggest a port that is `disabled` (mode == "disabled") OR `down`
  (admin_status == "down").
- Each port can appear in AT MOST ONE suggestion — a port has one cable.
- Be conservative: an empty list is fine, hallucinated links are not.

Return suggestions via the `submit_link_suggestions` tool. Do not write
explanatory prose — the tool call IS the answer.
"""

SUGGEST_TOOL = ToolDef(
    name="submit_link_suggestions",
    description=(
        "Submit the final list of suggested topology links. Each item must "
        "reference real port ids from the snapshot."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "suggestions": {
                "type": "array",
                "maxItems": 100,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["port_a_id", "port_b_id", "confidence", "reasoning"],
                    "properties": {
                        "port_a_id": {"type": "integer", "minimum": 1},
                        "port_b_id": {"type": "integer", "minimum": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reasoning": {"type": "string", "maxLength": 500},
                        "link_type": {
                            "type": "string",
                            "enum": ["copper", "fiber", "dac", "virtual"],
                        },
                    },
                },
            },
        },
        "required": ["suggestions"],
    },
)


@dataclass
class ScanReport:
    """What the route hands back to the UI after a scan."""

    run_id: int
    provider: str
    model: str
    raw_count: int  # total returned by the model
    persisted_count: int  # how many survived validation + dedup
    skipped_count: int  # raw_count - persisted_count
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


async def run_suggest_links(
    db: AsyncSession,
    *,
    user_id: int | None,
    confidence_threshold: float = 0.5,
) -> ScanReport:
    """Drive one suggest-links scan end-to-end."""
    settings = get_settings()
    provider = get_provider()

    context = await build_topology_context(db)
    payload = json.dumps(context, separators=(",", ":"), default=str)

    t0 = time.monotonic()
    error: str | None = None
    try:
        completion = await provider.call(
            system=SYSTEM_PROMPT,
            prompt=f"Network snapshot:\n```json\n{payload}\n```",
            tools=[SUGGEST_TOOL],
            max_tokens=settings.ai_max_output_tokens,
            temperature=0.2,
        )
    except AIProviderError as exc:
        error = str(exc)
        completion = None

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    run = AIRunLog(
        user_id=user_id,
        kind=AIRunKind.suggest_links,
        provider=provider.name,
        model=provider.model,
        prompt_tokens=completion.usage.prompt_tokens if completion else 0,
        completion_tokens=completion.usage.completion_tokens if completion else 0,
        latency_ms=elapsed_ms,
        success=error is None,
        error=error,
    )
    db.add(run)
    await db.flush()  # need run.id for the suggestions FK

    if not completion or not completion.tool_call:
        await db.commit()
        if error:
            raise AIProviderError(error)
        raise AIProviderError("provider returned no tool call")

    raw_items = completion.tool_call.input.get("suggestions", []) or []
    persisted = await _persist_suggestions(
        db,
        run_id=run.id,
        raw_items=raw_items,
        threshold=confidence_threshold,
    )
    await db.commit()

    return ScanReport(
        run_id=run.id,
        provider=provider.name,
        model=provider.model,
        raw_count=len(raw_items),
        persisted_count=persisted,
        skipped_count=len(raw_items) - persisted,
        latency_ms=elapsed_ms,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
    )


async def _persist_suggestions(
    db: AsyncSession,
    *,
    run_id: int,
    raw_items: list[dict],
    threshold: float,
) -> int:
    """Validate + insert pending suggestions, return how many landed.

    Filters applied (in order):
    - Confidence below threshold.
    - port_a_id == port_b_id, or either port absent from the DB, or both
      ports on the same switch.
    - The (canonical) pair already exists in `links`.
    - The (canonical) pair already has a pending suggestion (idempotent
      re-runs don't multiply rows).
    """
    if not raw_items:
        return 0

    # Pre-fetch the universe of ports referenced in the raw items so we can
    # validate without N round-trips.
    referenced_ids: set[int] = set()
    for item in raw_items:
        for key in ("port_a_id", "port_b_id"):
            pid = item.get(key)
            if isinstance(pid, int):
                referenced_ids.add(pid)
    if not referenced_ids:
        return 0
    ports = (
        await db.execute(select(Port).where(Port.id.in_(referenced_ids)))
    ).scalars().all()
    port_by_id = {p.id: p for p in ports}

    # Existing real links and pending suggestions, keyed by canonical pair.
    canonical_pairs_in_links = {
        (link.port_a_id, link.port_b_id)
        for link in (await db.execute(select(Link))).scalars().all()
    }
    pending_pairs = {
        (s.port_a_id, s.port_b_id)
        for s in (
            await db.execute(
                select(LinkSuggestion).where(
                    LinkSuggestion.status == LinkSuggestionStatus.pending
                )
            )
        )
        .scalars()
        .all()
    }

    new_rows: list[LinkSuggestion] = []
    seen_in_batch: set[tuple[int, int]] = set()
    for item in raw_items:
        a = item.get("port_a_id")
        b = item.get("port_b_id")
        if not isinstance(a, int) or not isinstance(b, int) or a == b:
            continue
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if confidence < threshold:
            continue
        port_a = port_by_id.get(a)
        port_b = port_by_id.get(b)
        if not port_a or not port_b:
            continue
        if port_a.switch_id == port_b.switch_id:
            continue
        # Canonical order — same invariant as the `links` table.
        if a > b:
            a, b = b, a
            port_a, port_b = port_b, port_a
        pair = (a, b)
        if pair in canonical_pairs_in_links or pair in pending_pairs or pair in seen_in_batch:
            continue
        seen_in_batch.add(pair)

        reasoning = str(item.get("reasoning", "")).strip()[:500]
        link_type = str(item.get("link_type", "copper") or "copper").lower()
        if link_type not in {"copper", "fiber", "dac", "virtual"}:
            link_type = "copper"
        new_rows.append(
            LinkSuggestion(
                run_id=run_id,
                port_a_id=a,
                port_b_id=b,
                link_type=link_type,
                confidence=max(0.0, min(1.0, confidence)),
                reasoning=reasoning,
                status=LinkSuggestionStatus.pending,
            )
        )

    if not new_rows:
        return 0
    db.add_all(new_rows)
    await db.flush()
    return len(new_rows)


async def list_pending(db: AsyncSession) -> list[LinkSuggestion]:
    return (
        (
            await db.execute(
                select(LinkSuggestion)
                .where(LinkSuggestion.status == LinkSuggestionStatus.pending)
                .order_by(LinkSuggestion.confidence.desc(), LinkSuggestion.id.asc())
            )
        )
        .scalars()
        .all()
    )


async def annotate_for_read(
    db: AsyncSession, suggestions: list[LinkSuggestion]
) -> list[dict]:
    """Denormalize port + switch labels onto each suggestion.

    The route layer uses this output to feed `LinkSuggestionRead` directly —
    keeps the modal independent of any global ports list endpoint (which
    doesn't exist; ports are nested under switches).
    """
    if not suggestions:
        return []
    port_ids: set[int] = set()
    for s in suggestions:
        port_ids.update((s.port_a_id, s.port_b_id))
    ports = (
        (await db.execute(select(Port).where(Port.id.in_(port_ids)))).scalars().all()
    )
    port_by_id = {p.id: p for p in ports}
    switch_ids = {p.switch_id for p in ports}
    from app.models.switch import Switch

    switches = (
        (await db.execute(select(Switch).where(Switch.id.in_(switch_ids))))
        .scalars()
        .all()
    )
    sw_by_id = {s.id: s for s in switches}

    def _resolve(pid: int) -> tuple[str | None, str | None]:
        port = port_by_id.get(pid)
        if not port:
            return None, None
        sw = sw_by_id.get(port.switch_id)
        return (
            port.label or f"port {port.number}",
            sw.name if sw else None,
        )

    out: list[dict] = []
    for s in suggestions:
        a_lbl, a_sw = _resolve(s.port_a_id)
        b_lbl, b_sw = _resolve(s.port_b_id)
        out.append(
            {
                "id": s.id,
                "port_a_id": s.port_a_id,
                "port_b_id": s.port_b_id,
                "port_a_label": a_lbl,
                "port_b_label": b_lbl,
                "switch_a_name": a_sw,
                "switch_b_name": b_sw,
                "link_type": s.link_type,
                "confidence": s.confidence,
                "reasoning": s.reasoning,
                "status": s.status.value,
                "accepted_link_id": s.accepted_link_id,
                "resolved_by_user_id": s.resolved_by_user_id,
                "resolved_at": s.resolved_at,
                "created_at": s.created_at,
            }
        )
    return out


async def accept_suggestion(
    db: AsyncSession,
    *,
    suggestion_id: int,
    user_id: int,
) -> tuple[LinkSuggestion, Link]:
    """Promote a pending suggestion into a real Link, mark it accepted."""
    suggestion = await db.get(LinkSuggestion, suggestion_id)
    if not suggestion:
        raise LookupError("suggestion not found")
    if suggestion.status != LinkSuggestionStatus.pending:
        raise ValueError(f"suggestion already {suggestion.status.value}")

    # Re-check the pair is still link-able (ports may have been deleted, a
    # real link may have been created in between).
    exists = (
        await db.execute(
            select(Link).where(
                tuple_(Link.port_a_id, Link.port_b_id) == (suggestion.port_a_id, suggestion.port_b_id)
            )
        )
    ).scalar_one_or_none()
    if exists:
        suggestion.status = LinkSuggestionStatus.superseded
        suggestion.resolved_at = _now()
        suggestion.resolved_by_user_id = user_id
        await db.commit()
        raise ValueError("a link already exists between these ports")

    from app.models.link import LinkType  # local import to avoid cycle at import time

    try:
        link_type_enum = LinkType(suggestion.link_type)
    except ValueError:
        link_type_enum = LinkType.copper
    link = Link(
        port_a_id=suggestion.port_a_id,
        port_b_id=suggestion.port_b_id,
        link_type=link_type_enum,
        description=f"AI-suggested ({suggestion.confidence:.0%})",
    )
    db.add(link)
    await db.flush()
    suggestion.status = LinkSuggestionStatus.accepted
    suggestion.accepted_link_id = link.id
    suggestion.resolved_at = _now()
    suggestion.resolved_by_user_id = user_id
    await db.commit()
    return suggestion, link


async def reject_suggestion(
    db: AsyncSession,
    *,
    suggestion_id: int,
    user_id: int,
) -> LinkSuggestion:
    suggestion = await db.get(LinkSuggestion, suggestion_id)
    if not suggestion:
        raise LookupError("suggestion not found")
    if suggestion.status != LinkSuggestionStatus.pending:
        raise ValueError(f"suggestion already {suggestion.status.value}")
    suggestion.status = LinkSuggestionStatus.rejected
    suggestion.resolved_at = _now()
    suggestion.resolved_by_user_id = user_id
    await db.commit()
    return suggestion


def _now():
    """Lazy import + UTC now — matches the rest of the codebase."""
    from datetime import datetime

    return datetime.now(UTC)
