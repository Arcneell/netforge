"""LLM-assisted CSV → NetForge column mapping.

Operators routinely arrive with Excel exports from their previous IPAM, a
vendor's "config dump" CSV, or hand-curated spreadsheets — each with column
headers that don't match NetForge's canonical names. This service hands the
LLM the foreign headers + a sample of rows and asks it to propose a best
guess of which NetForge field each one maps to.

Scope: **suggestion only**. The actual import pipeline still requires
canonical column names (see `services.csv_import`). The operator uses the
suggestion to rename their headers before uploading. A future PR can teach
the import to accept an explicit mapping; the schema returned here is
already structured to be reusable for that.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai import AIRunKind, AIRunLog
from app.services.ai.providers import get_provider
from app.services.ai.types import AIProviderError, ToolDef

# Canonical NetForge fields per import entity — keep this in sync with the
# `_*Row` models in `services.csv_import`. The descriptions are concise so the
# LLM has enough hint to disambiguate ("name" vs "hostname" vs "label" etc.).
_FIELD_CATALOG: dict[str, dict[str, str]] = {
    "sites": {
        "code": "Short site identifier (uppercase, e.g. PAR, HQ).",
        "name": "Human-readable site name.",
        "address": "Optional postal address.",
    },
    "rooms": {
        "site_code": "Code of the parent site.",
        "code": "Room identifier within the site (e.g. R-101).",
        "description": "Optional free-text description.",
    },
    "vlans": {
        "vlan_id": "Numeric VLAN id 1–4094.",
        "name": "Human-readable VLAN name.",
        "description": "Optional free-text description.",
        "color": "Optional hex colour like #1E90FF.",
    },
    "subnets": {
        "cidr": "IPv4 network in CIDR notation (e.g. 10.0.0.0/24).",
        "gateway": "Default gateway IPv4 address.",
        "vlan_id": "VLAN id this subnet belongs to.",
        "site_code": "Parent site code.",
        "description": "Optional free-text description.",
        "dhcp_enabled": "Boolean — is DHCP enabled on this subnet?",
        "dhcp_range_start": "First IP of the DHCP range.",
        "dhcp_range_end": "Last IP of the DHCP range.",
    },
    "ips": {
        "address": "IPv4 address.",
        "status": "reserved | assigned | dhcp.",
        "hostname": "Owning hostname / DNS name.",
        "mac": "MAC address (any common format).",
        "device_name": "Name of the device owning this IP.",
        "description": "Optional free-text description.",
    },
    "devices": {
        "name": "Device identifier / hostname.",
        "type": "server | desktop | laptop | printer | phone | ap | camera | ups | other.",
        "vendor": "Vendor name (Cisco, HP, …).",
        "model": "Model name.",
        "serial": "Serial number.",
        "site_code": "Parent site code.",
        "room_code": "Parent room code.",
        "description": "Optional free-text description.",
    },
    "switches": {
        "name": "Switch hostname.",
        "vendor": "Vendor name.",
        "model": "Model name.",
        "port_count": "Number of ports.",
        "site_code": "Parent site code.",
        "room_code": "Parent room code.",
        "mgmt_ip": "Management IP address.",
        "description": "Optional free-text description.",
    },
    "ports": {
        "switch_name": "Name of the parent switch.",
        "number": "Port number on the switch.",
        "label": "Optional label.",
        "mode": "access | trunk | hybrid | disabled.",
        "native_vlan": "Native VLAN id.",
        "tagged_vlans": "Comma-separated list of tagged VLAN ids.",
        "admin_status": "up | down.",
        "notes": "Free-text notes.",
    },
    "links": {
        "switch_a": "Endpoint A: switch name.",
        "port_a": "Endpoint A: port number or label.",
        "switch_b": "Endpoint B: switch name.",
        "port_b": "Endpoint B: port number or label.",
        "link_type": "copper | fiber | dac | virtual.",
        "description": "Optional free-text description.",
    },
}

# Maximum sample rows we forward to the LLM. Three is enough for it to spot
# format conventions (CIDR vs IP, MAC notation, boolean encoding) without
# blowing up tokens.
_MAX_SAMPLE_ROWS = 3
_MAX_CELL_LEN = 80


SYSTEM_PROMPT = """You are a CSV-import mapping assistant for NetForge.

The operator's CSV uses arbitrary column names. Your job: for each CSV column,
guess which NetForge canonical field it maps to — or mark it as unmapped
when nothing matches.

You receive:
- The target entity (e.g. "subnets", "switches").
- The list of canonical NetForge field names for that entity (the only
  values you may use for `suggested_field`).
- The CSV column names AS THEY APPEAR in the file.
- A few sample rows so you can disambiguate from the data (e.g. column
  "IP" with values like "10.0.0.1" is an `address`; "10.0.0.0/24" is a `cidr`).

Rules:
- Each `suggested_field` value MUST be either one of the canonical fields
  listed in the user prompt or null.
- A canonical field may be referenced by at most ONE CSV column. If two
  columns both look like the same field, pick the more obvious one and
  leave the other unmapped.
- Confidence is 0.0–1.0. Exact name matches → ≥ 0.9. Reasonable guesses
  from data shape → 0.6–0.8. Weak guesses → 0.3–0.5.
- Use the sample values to settle disambiguations — never invent a value.
- `notes` is one short sentence (≤ 120 chars) explaining the call.

Return your output via the `submit_mapping` tool.
"""


def _build_tool(allowed_fields: list[str]) -> ToolDef:
    return ToolDef(
        name="submit_mapping",
        description=(
            "Submit the per-column mapping decisions. Use null for "
            "`suggested_field` to leave a CSV column unmapped."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["columns", "missing_required_fields"],
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["csv_column", "suggested_field", "confidence"],
                        "properties": {
                            "csv_column": {"type": "string", "maxLength": 200},
                            "suggested_field": {
                                "type": ["string", "null"],
                                "enum": [*allowed_fields, None],
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "notes": {"type": "string", "maxLength": 200},
                        },
                    },
                },
                # The model's *own* list of canonical fields it couldn't map
                # from any CSV column — useful to surface "your CSV is
                # missing a `gateway` column" in the UI.
                "missing_required_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 30,
                },
            },
        },
    )


@dataclass
class MappingSuggestion:
    csv_column: str
    suggested_field: str | None
    confidence: float
    notes: str


@dataclass
class MappingResult:
    entity: str
    columns: list[MappingSuggestion]
    missing_required_fields: list[str]
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


def _truncate_sample(rows: list[list[str]]) -> list[list[str]]:
    """Cap rows count + individual cell length so a `cat /etc/passwd` row
    doesn't blow up the prompt or smuggle weird payloads through."""
    capped: list[list[str]] = []
    for row in rows[:_MAX_SAMPLE_ROWS]:
        capped.append(
            [(cell or "")[: _MAX_CELL_LEN] for cell in row]
        )
    return capped


def list_canonical_fields(entity: str) -> list[str]:
    """Public accessor for the catalog — used by tests and the route layer
    to validate the requested entity before talking to the LLM."""
    fields = _FIELD_CATALOG.get(entity)
    if fields is None:
        return []
    return sorted(fields.keys())


async def run_mapping_suggestion(
    db: AsyncSession,
    *,
    user_id: int | None,
    entity: str,
    csv_columns: list[str],
    sample_rows: list[list[str]],
    language_instruction: str | None = None,
) -> MappingResult:
    """Drive one mapping-suggestion call end-to-end.

    Raises `AIProviderError` if the provider call fails or the model returns
    no tool call. The route layer maps that to a 502.
    """
    fields = _FIELD_CATALOG.get(entity)
    if not fields:
        raise AIProviderError(f"unknown entity for mapping: {entity!r}")
    allowed = list(fields.keys())

    settings = get_settings()
    provider = get_provider()
    tool = _build_tool(allowed)

    sample = _truncate_sample(sample_rows)
    user_prompt_parts = [
        f"Entity: {entity}",
        "",
        "Canonical NetForge fields:",
    ]
    for name, desc in fields.items():
        user_prompt_parts.append(f"- {name}: {desc}")
    user_prompt_parts.extend(
        [
            "",
            f"CSV columns (in order): {json.dumps(csv_columns)}",
            "",
            f"Sample rows (each is an array aligned with the columns above): {json.dumps(sample)}",
        ]
    )
    user_prompt = "\n".join(user_prompt_parts)

    system = SYSTEM_PROMPT + (f"\n\n{language_instruction}" if language_instruction else "")

    t0 = time.monotonic()
    error: str | None = None
    try:
        completion = await provider.call(
            system=system,
            prompt=user_prompt,
            tools=[tool],
            max_tokens=settings.ai_max_output_tokens,
            temperature=0.1,
        )
    except AIProviderError as exc:
        error = str(exc)
        completion = None
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Log it the same way every other AI feature does — this keeps the
    # Usage dashboard accurate.
    run = AIRunLog(
        user_id=user_id,
        # Re-use `nl_query` kind: it's the closest "one-shot question →
        # structured answer" pattern and avoids a migration to add a new
        # enum value purely for cost-tracking.
        kind=AIRunKind.nl_query,
        provider=provider.name,
        model=provider.model,
        prompt_tokens=completion.usage.prompt_tokens if completion else 0,
        completion_tokens=completion.usage.completion_tokens if completion else 0,
        latency_ms=elapsed_ms,
        success=error is None,
        error=error,
    )
    db.add(run)
    await db.commit()

    if not completion or not completion.tool_call:
        if error:
            raise AIProviderError(error)
        raise AIProviderError("provider returned no tool call")

    raw_columns = completion.tool_call.input.get("columns", []) or []
    missing_raw = completion.tool_call.input.get("missing_required_fields", []) or []

    columns_out: list[MappingSuggestion] = []
    used_targets: set[str] = set()
    for item in raw_columns:
        csv_col = str(item.get("csv_column", "")).strip()
        if not csv_col:
            continue
        suggested = item.get("suggested_field")
        # Drop hallucinated targets that aren't part of the allowed set.
        if suggested is not None:
            suggested = str(suggested)
            if suggested not in allowed or suggested in used_targets:
                suggested = None
            else:
                used_targets.add(suggested)
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        notes = str(item.get("notes", "")).strip()[:200]
        columns_out.append(
            MappingSuggestion(
                csv_column=csv_col,
                suggested_field=suggested,
                confidence=max(0.0, min(1.0, confidence)),
                notes=notes,
            )
        )

    missing_out = [
        str(f).strip()
        for f in missing_raw
        if isinstance(f, str) and str(f).strip() in allowed and str(f).strip() not in used_targets
    ]

    return MappingResult(
        entity=entity,
        columns=columns_out,
        missing_required_fields=missing_out,
        provider=provider.name,
        model=provider.model,
        latency_ms=elapsed_ms,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
    )
