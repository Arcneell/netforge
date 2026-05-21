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

import ipaddress
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field

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
        "management_ip": "Management IP address.",
        "description": "Optional free-text description.",
    },
    "ports": {
        "switch_name": "Name of the parent switch.",
        "number": "Port number on the switch.",
        "label": "Optional label.",
        "mode": "access | trunk | hybrid | disabled.",
        "native_vlan": "Native VLAN id.",
        "trunk_vlans": "Comma-separated list of tagged / trunk VLAN ids.",
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

The operator's CSV uses arbitrary column names. Your job, in one tool call:
  1. For each CSV column, guess which NetForge canonical field it maps to
     (or mark it as unmapped).
  2. Flag data-quality issues you spot in the sample rows that would break
     the import or mislead the operator.

You receive:
- The target entity (e.g. "subnets", "switches").
- The list of canonical NetForge field names for that entity (the only
  values you may use for `suggested_field`).
- The CSV column names AS THEY APPEAR in the file.
- A few sample rows so you can disambiguate from the data (e.g. column
  "IP" with values like "10.0.0.1" is an `address`; "10.0.0.0/24" is a `cidr`).

Mapping rules:
- Each `suggested_field` value MUST be either one of the canonical fields
  listed in the user prompt or null.
- A canonical field may be referenced by at most ONE CSV column. If two
  columns both look like the same field, pick the more obvious one and
  leave the other unmapped.
- Confidence is 0.0–1.0. Exact name matches → ≥ 0.9. Reasonable guesses
  from data shape → 0.6–0.8. Weak guesses → 0.3–0.5.
- Use the sample values to settle disambiguations — never invent a value.
- `notes` is one short sentence (≤ 120 chars) explaining the call.

Data-quality rules:
- Focus on issues the sample obviously reveals: mixed unit conventions
  (Mbps vs Gbps), inconsistent casing of identifiers, ambiguous boolean
  encodings (1/0 vs yes/no vs Y/N), suspicious outliers, values that don't
  match the column's apparent type, mixed delimiters, hidden whitespace, …
- DO NOT flag missing-required-field errors here — that's reserved for
  `missing_required_fields`.
- Severity: "critical" if the import would crash; "warning" if it would
  succeed but produce wrong data; "info" for style hints.
- `affected_row_count` counts ONLY the rows shown in the sample.

Return your output via the `submit_mapping` tool.
"""


def _build_tool(allowed_fields: list[str]) -> ToolDef:
    return ToolDef(
        name="submit_mapping",
        description=(
            "Submit the per-column mapping decisions and any data-quality "
            "observations. Use null for `suggested_field` to leave a CSV "
            "column unmapped."
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
                # Free-form data-quality observations the model can spot
                # from the sample — mixed units, inconsistent casing, etc.
                # The deterministic checks in `run_local_data_quality` catch
                # the obvious ones (malformed CIDR, empty required cells).
                "data_quality": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["severity", "issue", "details"],
                        "properties": {
                            "severity": {
                                "type": "string",
                                "enum": ["info", "warning", "critical"],
                            },
                            "column": {"type": ["string", "null"], "maxLength": 200},
                            "issue": {"type": "string", "maxLength": 80},
                            "details": {"type": "string", "maxLength": 400},
                            "sample_values": {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 80},
                                "maxItems": 5,
                            },
                            "affected_row_count": {"type": "integer", "minimum": 0},
                        },
                    },
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
class DataQualityIssue:
    severity: str  # "info" | "warning" | "critical"
    column: str | None
    issue: str
    details: str
    sample_values: list[str] = field(default_factory=list)
    affected_row_count: int = 0
    source: str = "llm"  # "local" for deterministic checks


@dataclass
class MappingResult:
    entity: str
    columns: list[MappingSuggestion]
    missing_required_fields: list[str]
    data_quality: list[DataQualityIssue]
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


# --- Deterministic data-quality checks -------------------------------------

# Per-entity hint of which canonical fields are required to import a row.
# Used to flag empty cells in mapped columns. Mirrors the `_*Row` Pydantic
# models in services.csv_import — we duplicate here deliberately because
# importing them would create a circular dep, and the catalog is short.
_REQUIRED_FIELDS: dict[str, set[str]] = {
    "sites": {"code", "name"},
    "rooms": {"site_code", "code"},
    "vlans": {"vlan_id", "name"},
    # `site_code` is required by `_SubnetRow` in services.csv_import — Codex
    # flagged the omission on PR #63, otherwise a CSV with blank site_code
    # passed the mapper's data-quality check and crashed at import.
    "subnets": {"cidr", "site_code"},
    "ips": {"address"},
    "devices": {"name"},
    "switches": {"name"},
    "ports": {"switch_name", "number"},
    "links": {"switch_a", "port_a", "switch_b", "port_b"},
}

# Field → checker name. The checker validates one cell and returns True
# when the value looks valid for that target. Only fields with a reasonable
# regex/parsing check appear here — free-text fields (description, notes)
# are intentionally skipped.
_FIELD_VALIDATORS: dict[str, str] = {
    "cidr": "cidr",
    "gateway": "ipv4",
    "address": "ipv4",
    "management_ip": "ipv4",
    "dhcp_range_start": "ipv4",
    "dhcp_range_end": "ipv4",
    "mac": "mac",
    "vlan_id": "vlan_id",
    "native_vlan": "vlan_id",
}

# Canonical fields that should be unique within a CSV — duplicates are
# nearly always operator error and the import would either fail or pick
# one arbitrarily. Keep this conservative; "name" is duplicated all the
# time across entities (two devices may share a name across sites) so it
# is NOT in this list — only fields with a hard uniqueness invariant.
_UNIQUE_FIELDS: dict[str, set[str]] = {
    "sites": {"code"},
    "vlans": {"vlan_id"},
    "subnets": {"cidr"},
    "ips": {"address"},
}

# Mirror the importer's `_MAC_PATTERNS` — colon/hyphen-separated, no
# separator, AND Cisco-style dotted (`aabb.ccdd.eeff`). Codex flagged the
# omission on PR #63 because the validator was rejecting MACs the importer
# happily accepts.
_MAC_PATTERNS = (
    re.compile(r"^[0-9a-f]{2}([:-]?[0-9a-f]{2}){5}$", re.IGNORECASE),
    re.compile(r"^[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}$", re.IGNORECASE),
)


def _looks_like_cidr(value: str) -> bool:
    try:
        ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return False
    return "/" in value


def _looks_like_ipv4(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return isinstance(addr, ipaddress.IPv4Address)


def _looks_like_mac(value: str) -> bool:
    s = value.strip()
    return any(pat.match(s) for pat in _MAC_PATTERNS)


def _looks_like_vlan_id(value: str) -> bool:
    try:
        v = int(value.strip())
    except (ValueError, TypeError):
        return False
    return 1 <= v <= 4094


_VALIDATORS = {
    "cidr": _looks_like_cidr,
    "ipv4": _looks_like_ipv4,
    "mac": _looks_like_mac,
    "vlan_id": _looks_like_vlan_id,
}


def run_local_data_quality(
    *,
    entity: str,
    csv_columns: list[str],
    sample_rows: list[list[str]],
    column_mapping: dict[str, str | None],
) -> list[DataQualityIssue]:
    """Deterministic checks that don't need the LLM.

    Three categories, ordered by how much they matter:
      1. Empty required cells — would crash the import outright.
      2. Type mismatches in mapped columns — would import wrong data.
      3. Duplicate values in unique columns — sample-only, just a heuristic.

    We deliberately keep this short. The LLM picks up the long tail
    (mixed units, casing conventions) — it's a complement, not a backstop.
    """
    issues: list[DataQualityIssue] = []
    if not sample_rows:
        return issues

    required = _REQUIRED_FIELDS.get(entity, set())
    unique = _UNIQUE_FIELDS.get(entity, set())

    # Map column index → target field, for the columns the operator actually
    # mapped. Unmapped columns are skipped by all three checks below.
    col_index_to_field: dict[int, str] = {}
    for idx, col in enumerate(csv_columns):
        target = column_mapping.get(col)
        if target:
            col_index_to_field[idx] = target

    # 1. Empty cells in columns mapped to a required field.
    for idx, field_name in col_index_to_field.items():
        if field_name not in required:
            continue
        empty_count = 0
        for row in sample_rows:
            cell = (row[idx] if idx < len(row) else "").strip()
            if not cell:
                empty_count += 1
        if empty_count:
            issues.append(
                DataQualityIssue(
                    severity="critical",
                    column=csv_columns[idx],
                    issue="empty required value",
                    details=(
                        f"{empty_count}/{len(sample_rows)} sample rows have an empty "
                        f"`{csv_columns[idx]}` cell — `{field_name}` is required."
                    ),
                    sample_values=[],
                    affected_row_count=empty_count,
                    source="local",
                )
            )

    # 2. Type mismatches in mapped columns whose target has a validator.
    for idx, field_name in col_index_to_field.items():
        validator_key = _FIELD_VALIDATORS.get(field_name)
        if not validator_key:
            continue
        check = _VALIDATORS[validator_key]
        bad: list[str] = []
        for row in sample_rows:
            cell = (row[idx] if idx < len(row) else "").strip()
            if not cell:
                continue  # empty handled by check #1; not a type issue
            if not check(cell):
                bad.append(cell)
        if bad:
            issues.append(
                DataQualityIssue(
                    severity="warning",
                    column=csv_columns[idx],
                    issue=f"value doesn't look like {validator_key}",
                    details=(
                        f"{len(bad)}/{len(sample_rows)} sample rows in "
                        f"`{csv_columns[idx]}` don't match the expected "
                        f"{validator_key} format."
                    ),
                    sample_values=bad[:5],
                    affected_row_count=len(bad),
                    source="local",
                )
            )

    # 3. Duplicates in columns mapped to a unique field.
    for idx, field_name in col_index_to_field.items():
        if field_name not in unique:
            continue
        values = [
            (row[idx] if idx < len(row) else "").strip().lower()
            for row in sample_rows
        ]
        values = [v for v in values if v]
        counts = Counter(values)
        dups = [v for v, n in counts.items() if n > 1]
        if dups:
            issues.append(
                DataQualityIssue(
                    severity="warning",
                    column=csv_columns[idx],
                    issue="duplicate values in unique column",
                    details=(
                        f"`{csv_columns[idx]}` maps to `{field_name}` which is "
                        f"unique across the dataset, but the sample shows duplicates."
                    ),
                    sample_values=dups[:5],
                    affected_row_count=sum(counts[v] for v in dups),
                    source="local",
                )
            )

    return issues


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

    # Parse the LLM's data-quality observations (optional in the schema —
    # older provider responses may omit the key entirely).
    raw_dq = completion.tool_call.input.get("data_quality", []) or []
    llm_dq: list[DataQualityIssue] = []
    for item in raw_dq:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "warning")).lower()
        if severity not in {"info", "warning", "critical"}:
            severity = "warning"
        col = item.get("column")
        col_str = str(col).strip()[:200] if isinstance(col, str) else None
        issue_text = str(item.get("issue", "")).strip()[:80]
        if not issue_text:
            continue
        details_text = str(item.get("details", "")).strip()[:400]
        sample_values = [
            str(v).strip()[:80]
            for v in (item.get("sample_values") or [])
            if isinstance(v, (str, int, float))
        ][:5]
        try:
            row_count = int(item.get("affected_row_count", 0) or 0)
        except (TypeError, ValueError):
            row_count = 0
        llm_dq.append(
            DataQualityIssue(
                severity=severity,
                column=col_str,
                issue=issue_text,
                details=details_text,
                sample_values=sample_values,
                affected_row_count=max(0, row_count),
                source="llm",
            )
        )

    # Run the deterministic checks against the LLM's own mapping. This is
    # what makes the assistant catch "you forgot to fill `code` on row 2"
    # reliably — the LLM is bad at counting blanks but great at spotting
    # inconsistent conventions.
    column_mapping = {c.csv_column: c.suggested_field for c in columns_out}
    local_dq = run_local_data_quality(
        entity=entity,
        csv_columns=csv_columns,
        sample_rows=sample,
        column_mapping=column_mapping,
    )

    return MappingResult(
        entity=entity,
        columns=columns_out,
        missing_required_fields=missing_out,
        data_quality=local_dq + llm_dq,
        provider=provider.name,
        model=provider.model,
        latency_ms=elapsed_ms,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
    )
