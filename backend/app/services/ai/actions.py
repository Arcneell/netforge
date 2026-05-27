"""Natural-language → CRUD draft pipeline.

Workflow:
1. Operator types "create a VLAN 50 named IoT on site Paris" in free text.
2. The LLM is forced (`tool_choice`) to pick ONE intent from a closed enum
   and return a strict, validated payload.
3. The result is persisted as a row in `ai_action_drafts` with status =
   pending. **Nothing is created in the actual inventory tables yet.**
4. An admin reviews the draft (the UI shows intent + payload + the raw NL
   prompt) and explicitly clicks "Apply". The apply endpoint dispatches
   to the matching service module and updates the draft row.

Why drafts, not direct execution: the LLM is occasionally wrong about
which entity the operator meant — a "create" on the wrong site is hard to
roll back. Drafts give the operator a 1-second sanity check that is the
audit trail too.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai import (
    AIActionDraft,
    AIActionDraftStatus,
    AIRunKind,
    AIRunLog,
)
from app.models.core import Room, Site
from app.models.subnet import Subnet
from app.models.vlan import Vlan
from app.services.ai.context import build_topology_context_cached
from app.services.ai.providers import get_provider
from app.services.ai.types import AIProviderError, ToolDef

# Intent enum mirrored on the tool schema — the model can pick exactly one.
SUPPORTED_INTENTS = ["create_site", "create_room", "create_vlan", "create_subnet"]

SYSTEM_PROMPT = """You are NetForge's NL-to-action drafter.

The operator types a CRUD-style request in free text ("create a VLAN 50
named IoT at site PAR"). Your job: pick ONE supported intent and produce a
strict payload that the operator can review and apply.

Rules:
- The intent MUST be one of: create_site, create_room, create_vlan,
  create_subnet. If the request doesn't match any of these, set
  `intent` = null and use `reasoning` to explain why.
- Resolve references against the supplied snapshot — never invent a
  `site_code` or a `vlan_id` the snapshot doesn't show.
- Be conservative: missing fields default to null/empty, never guessed.

Return your output via the `submit_draft` tool. Do not write prose around it.
"""

DRAFT_TOOL = ToolDef(
    name="submit_draft",
    description=(
        "Submit a single drafted CRUD action. The operator will review it "
        "before anything is created in the inventory."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "payload", "reasoning"],
        "properties": {
            "intent": {
                "type": ["string", "null"],
                "enum": [*SUPPORTED_INTENTS, None],
            },
            "payload": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "code": {"type": "string", "maxLength": 50},
                    "name": {"type": "string", "maxLength": 200},
                    "address": {"type": "string", "maxLength": 500},
                    "description": {"type": "string", "maxLength": 500},
                    "site_code": {"type": "string", "maxLength": 50},
                    "vlan_id": {"type": "integer", "minimum": 1, "maximum": 4094},
                    "cidr": {"type": "string", "maxLength": 40},
                    "gateway": {"type": "string", "maxLength": 40},
                    "color": {"type": "string", "maxLength": 7},
                    # Optional scope. The applier validates against the
                    # snapshot — invalid ids fail at apply time, not draft.
                    "vrf_id": {"type": "integer", "minimum": 1},
                    "parent_subnet_id": {"type": "integer", "minimum": 1},
                },
            },
            "reasoning": {"type": "string", "maxLength": 500},
        },
    },
)


# --- Pure payload validators (no DB) ---------------------------------------


def _validate_payload(intent: str, payload: dict[str, Any]) -> dict[str, Any] | str:
    """Return either a cleaned payload dict or an error string.

    These are *shape* checks — DB-side references (does `site_code` PAR
    exist?) are resolved later by the applier so a stale snapshot doesn't
    block an otherwise valid draft."""
    if intent == "create_site":
        code = (payload.get("code") or "").strip().upper()
        name = (payload.get("name") or "").strip()
        if not code or not name:
            return "create_site requires `code` and `name`"
        return {
            "code": code,
            "name": name,
            "address": (payload.get("address") or "").strip() or None,
        }
    if intent == "create_room":
        site_code = (payload.get("site_code") or "").strip().upper()
        code = (payload.get("code") or "").strip()
        if not site_code or not code:
            return "create_room requires `site_code` and `code`"
        return {
            "site_code": site_code,
            "code": code,
            "description": (payload.get("description") or "").strip() or None,
        }
    if intent == "create_vlan":
        try:
            vlan_id = int(payload.get("vlan_id"))
        except (TypeError, ValueError):
            return "create_vlan requires a numeric `vlan_id`"
        if not (1 <= vlan_id <= 4094):
            return "vlan_id must be in 1–4094"
        name = (payload.get("name") or "").strip()
        if not name:
            return "create_vlan requires `name`"
        return {
            "vlan_id": vlan_id,
            "name": name,
            "description": (payload.get("description") or "").strip() or None,
            "color": (payload.get("color") or "").strip() or None,
        }
    if intent == "create_subnet":
        cidr = (payload.get("cidr") or "").strip()
        site_code = (payload.get("site_code") or "").strip().upper()
        if not cidr or not site_code:
            return "create_subnet requires `cidr` and `site_code`"
        # Defer the CIDR-parsing rigor to the applier — the create endpoint
        # validates with pydantic anyway.
        payload_out: dict[str, Any] = {"cidr": cidr, "site_code": site_code}
        if payload.get("gateway"):
            payload_out["gateway"] = str(payload["gateway"]).strip()
        if payload.get("vlan_id") is not None:
            try:
                payload_out["vlan_id"] = int(payload["vlan_id"])
            except (TypeError, ValueError):
                return "vlan_id must be an integer"
        # Forward vrf_id / parent_subnet_id when the LLM emitted them.
        # PR #96 added applier-side handling but the validator dropped
        # both fields here, so AI-applied subnets still landed in the
        # global VRF as roots regardless of the prompt (Codex P2 on
        # #96). Coerce to ints — anything else fails the applier's own
        # check chain.
        for key in ("vrf_id", "parent_subnet_id"):
            if payload.get(key) is not None:
                try:
                    payload_out[key] = int(payload[key])
                except (TypeError, ValueError):
                    return f"{key} must be an integer"
        if payload.get("description"):
            payload_out["description"] = str(payload["description"]).strip()
        return payload_out
    return f"unknown intent: {intent}"


# --- LLM-driven drafting ---------------------------------------------------


async def draft_action(
    db: AsyncSession,
    *,
    user_id: int,
    prompt: str,
    language_instruction: str | None = None,
) -> AIActionDraft:
    """Ask the model to draft one action, persist it as pending."""
    settings = get_settings()
    provider = get_provider()
    context, _was_cached = await build_topology_context_cached(db)
    payload_json = json.dumps(context, separators=(",", ":"), default=str)

    system = SYSTEM_PROMPT + (
        f"\n\n{language_instruction}" if language_instruction else ""
    )

    t0 = time.monotonic()
    error: str | None = None
    try:
        completion = await provider.call(
            system=system,
            prompt=f"Operator request: {prompt}",
            cache_prefix=f"Network snapshot:\n```json\n{payload_json}\n```",
            tools=[DRAFT_TOOL],
            max_tokens=settings.ai_max_output_tokens,
            temperature=0.1,
        )
    except AIProviderError as exc:
        error = str(exc)
        completion = None
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    run = AIRunLog(
        user_id=user_id,
        kind=AIRunKind.nl_query,  # piggy-backed: same "one-shot tool call" shape.
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
        if error:
            raise AIProviderError(error)
        raise AIProviderError("provider returned no tool call")

    intent = completion.tool_call.input.get("intent")
    raw_payload = completion.tool_call.input.get("payload") or {}
    if intent not in SUPPORTED_INTENTS:
        raise AIProviderError(
            f"model could not match a supported intent (got {intent!r})"
        )
    cleaned = _validate_payload(intent, raw_payload)
    if isinstance(cleaned, str):
        raise AIProviderError(f"draft payload invalid: {cleaned}")

    draft = AIActionDraft(
        user_id=user_id,
        prompt=prompt.strip()[:2000],
        intent=intent,
        payload=cleaned,
        status=AIActionDraftStatus.pending,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


# --- Applier ---------------------------------------------------------------


async def apply_draft(
    db: AsyncSession, *, draft_id: int, user_id: int
) -> AIActionDraft:
    """Execute the pending draft. Returns the updated row.

    The applier does *not* re-query the LLM — it runs the cleaned payload
    that was already validated at draft time. References (site_code,
    vlan_id) are resolved here against the live DB.
    """
    draft = await db.get(AIActionDraft, draft_id)
    if not draft:
        raise LookupError("draft not found")
    if draft.status != AIActionDraftStatus.pending:
        raise ValueError(f"draft already {draft.status.value}")

    try:
        if draft.intent == "create_site":
            result_pointer = await _apply_create_site(db, draft.payload)
        elif draft.intent == "create_room":
            result_pointer = await _apply_create_room(db, draft.payload)
        elif draft.intent == "create_vlan":
            result_pointer = await _apply_create_vlan(db, draft.payload)
        elif draft.intent == "create_subnet":
            result_pointer = await _apply_create_subnet(db, draft.payload)
        else:
            raise ValueError(f"unsupported intent: {draft.intent}")
    except Exception as exc:
        # Roll back the failed transaction before touching the draft row,
        # otherwise `commit()` raises `PendingRollbackError` (e.g. when the
        # inner applier tripped a constraint like `subnets_no_overlap` —
        # the session is in failed state until we explicitly roll it back).
        await db.rollback()
        # Re-fetch the draft because rollback evicts it from the session.
        draft = await db.get(AIActionDraft, draft_id)
        if not draft:
            raise
        draft.status = AIActionDraftStatus.failed
        draft.error_message = str(exc)[:1000]
        draft.applied_at = datetime.now(UTC)
        draft.applied_by_user_id = user_id
        await db.commit()
        raise

    draft.status = AIActionDraftStatus.applied
    draft.applied_resource = result_pointer
    draft.applied_at = datetime.now(UTC)
    draft.applied_by_user_id = user_id
    await db.commit()
    await db.refresh(draft)
    return draft


async def reject_draft(
    db: AsyncSession, *, draft_id: int, user_id: int
) -> AIActionDraft:
    """Mark a draft as rejected — operator declined to apply it."""
    draft = await db.get(AIActionDraft, draft_id)
    if not draft:
        raise LookupError("draft not found")
    if draft.status != AIActionDraftStatus.pending:
        raise ValueError(f"draft already {draft.status.value}")
    draft.status = AIActionDraftStatus.rejected
    draft.applied_at = datetime.now(UTC)
    draft.applied_by_user_id = user_id
    await db.commit()
    await db.refresh(draft)
    return draft


# --- Per-intent appliers — each returns an `kind:id` pointer ---------------


async def _apply_create_site(db: AsyncSession, payload: dict[str, Any]) -> str:
    existing = (
        await db.execute(select(Site).where(Site.code == payload["code"]))
    ).scalar_one_or_none()
    if existing:
        raise ValueError(f"site with code {payload['code']} already exists")
    site = Site(
        code=payload["code"],
        name=payload["name"],
        address=payload.get("address"),
    )
    db.add(site)
    await db.flush()
    return f"site:{site.id}"


async def _apply_create_room(db: AsyncSession, payload: dict[str, Any]) -> str:
    site = (
        await db.execute(select(Site).where(Site.code == payload["site_code"]))
    ).scalar_one_or_none()
    if not site:
        raise ValueError(f"site with code {payload['site_code']} not found")
    existing = (
        await db.execute(
            select(Room).where(
                Room.site_id == site.id, Room.code == payload["code"]
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError(
            f"room {payload['code']} already exists in site {payload['site_code']}"
        )
    room = Room(
        site_id=site.id,
        code=payload["code"],
        description=payload.get("description"),
    )
    db.add(room)
    await db.flush()
    return f"room:{room.id}"


async def _apply_create_vlan(db: AsyncSession, payload: dict[str, Any]) -> str:
    existing = (
        await db.execute(select(Vlan).where(Vlan.vlan_id == payload["vlan_id"]))
    ).scalar_one_or_none()
    if existing:
        raise ValueError(f"VLAN id {payload['vlan_id']} already exists")
    vlan = Vlan(
        vlan_id=payload["vlan_id"],
        name=payload["name"],
        description=payload.get("description"),
        color=payload.get("color"),
    )
    db.add(vlan)
    await db.flush()
    return f"vlan:{vlan.id}"


async def _apply_create_subnet(db: AsyncSession, payload: dict[str, Any]) -> str:
    """Mirrors the `/api/subnets` create path's semantic checks so a draft
    can never produce inventory state that the canonical endpoint would
    have rejected.

    Forwards vrf_id and parent_subnet_id from the draft payload — the
    previous applier silently dropped both, so AI-applied subnets always
    landed in the global VRF as roots, bypassing the per-VRF GiST
    exclusion + the parent-containment guard. Combined with subsequent
    edits, that left the hierarchy in a half-broken state.
    """
    from ipaddress import IPv4Address, IPv4Network

    try:
        network = IPv4Network(payload["cidr"], strict=False)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"invalid CIDR: {exc}") from exc

    gateway = payload.get("gateway")
    if gateway:
        try:
            gw = IPv4Address(gateway)
        except ValueError as exc:
            raise ValueError(f"invalid gateway: {exc}") from exc
        if gw not in network:
            raise ValueError(
                f"gateway {gw} is outside the subnet {network}"
            )

    site = (
        await db.execute(select(Site).where(Site.code == payload["site_code"]))
    ).scalar_one_or_none()
    if not site:
        raise ValueError(f"site with code {payload['site_code']} not found")
    vlan_pk: int | None = None
    if payload.get("vlan_id") is not None:
        vlan_row = (
            await db.execute(
                select(Vlan).where(Vlan.vlan_id == payload["vlan_id"])
            )
        ).scalar_one_or_none()
        if not vlan_row:
            raise ValueError(f"VLAN id {payload['vlan_id']} not found")
        vlan_pk = vlan_row.id

    vrf_id = payload.get("vrf_id")
    parent_subnet_id = payload.get("parent_subnet_id")

    # If the payload specifies a parent, mirror /api/subnets' containment
    # check: the parent must exist, live in the same VRF, and strictly
    # contain the child. Without this an AI-applied subnet can violate
    # the hierarchy invariant; subsequent edits then 400 with confusing
    # INVALID_PARENT errors.
    if parent_subnet_id is not None:
        parent = await db.get(Subnet, parent_subnet_id)
        if parent is None:
            raise ValueError(f"parent subnet {parent_subnet_id} not found")
        if parent.vrf_id != vrf_id:
            raise ValueError(
                "parent subnet must live in the same VRF as the child"
            )
        parent_net = IPv4Network(str(parent.cidr), strict=False)
        if not (network.subnet_of(parent_net) and network != parent_net):
            raise ValueError(
                f"{network} is not strictly contained in parent {parent_net}"
            )

    subnet = Subnet(
        cidr=str(network),
        gateway=str(gw) if gateway else None,
        vlan_id=vlan_pk,
        site_id=site.id,
        vrf_id=vrf_id,
        parent_subnet_id=parent_subnet_id,
        description=payload.get("description"),
    )
    db.add(subnet)
    await db.flush()
    return f"subnet:{subnet.id}"
