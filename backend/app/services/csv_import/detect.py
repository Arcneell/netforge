"""Auto-detection — match CSV headers against each entity's required columns
to pick the right importer without forcing the user to choose.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.schemas.imports import DetectReport
from app.services.csv_import.parsing import _read_headers
from app.services.csv_import.persist import SPECS


def _required_headers(model: type[BaseModel]) -> set[str]:
    """Columns that MUST appear in the CSV for this entity.

    Pydantic fields without a default value are required at validation time —
    they're the strongest signal that a CSV belongs to that entity. Optional
    columns (with defaults like `None`) don't have to be present even if the
    importer would accept them, and using them in the match would muddy the
    score.
    """
    out: set[str] = set()
    for name, field in model.model_fields.items():
        if field.is_required():
            out.add(name)
    return out


def _all_headers(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields.keys())


REQUIRED_HEADERS: dict[str, set[str]] = {
    e: _required_headers(spec.row_model) for e, spec in SPECS.items()
}
ALL_HEADERS: dict[str, set[str]] = {
    e: _all_headers(spec.row_model) for e, spec in SPECS.items()
}


@dataclass(frozen=True)
class _DetectMatch:
    entity: str
    score: float
    missing_required: list[str]
    unknown: list[str]


def _score_entity(headers: set[str], entity: str) -> _DetectMatch:
    """Score how well `headers` matches the row model of `entity`.

    A perfect match (score == 1.0) means every required header is present and
    no unknown header appears. Any missing required column kills the match
    (score < 1.0); unknown headers cost a little — enough to disambiguate
    between entities that share a required column subset but differ in their
    optional columns.
    """
    required = REQUIRED_HEADERS[entity]
    known = ALL_HEADERS[entity]
    missing = sorted(required - headers)
    unknown = sorted(headers - known)
    if missing:
        # If any required column is missing the file simply isn't this entity.
        return _DetectMatch(entity, 0.0, missing, unknown)
    # All required columns present. Penalize unknown headers but only mildly,
    # since CSVs from older exports might carry extra columns we now ignore.
    penalty = 0.1 * len(unknown) / max(len(known), 1)
    return _DetectMatch(entity, max(0.0, 1.0 - penalty), [], unknown)


def detect_entity(content: bytes) -> DetectReport:
    """Pick the most likely entity for a CSV by looking at its header row.

    Returns the best match plus diagnostics so the UI can explain *why* a
    file was assigned (or rejected). When several entities tie on required
    columns, the one with the smallest set of unknown headers wins.
    """
    header_list = _read_headers(content)
    headers = set(header_list)

    if not headers:
        return DetectReport(
            entity=None,
            confidence=0.0,
            headers=[],
            matched_required=[],
            missing_required=[],
            unknown_headers=[],
            candidates={},
        )

    scores = {e: _score_entity(headers, e) for e in SPECS}
    # Strict matches first: required columns satisfied. Tie-break by fewest
    # unknown columns, then by entity name for determinism.
    strict = [m for m in scores.values() if not m.missing_required]
    if strict:
        strict.sort(key=lambda m: (len(m.unknown), m.entity))
        best = strict[0]
        return DetectReport(
            entity=best.entity,
            confidence=best.score,
            headers=header_list,
            matched_required=sorted(REQUIRED_HEADERS[best.entity]),
            missing_required=[],
            unknown_headers=best.unknown,
            candidates={e: scores[e].score for e in SPECS},
        )

    # No entity has all its required columns — pick the closest as the most
    # likely intent so the UI can show "did you mean …?" with the missing
    # columns spelled out.
    nearest = min(scores.values(), key=lambda m: (len(m.missing_required), m.entity))
    return DetectReport(
        entity=None,
        confidence=0.0,
        headers=header_list,
        matched_required=sorted(REQUIRED_HEADERS[nearest.entity] & headers),
        missing_required=nearest.missing_required,
        unknown_headers=nearest.unknown,
        candidates={e: scores[e].score for e in SPECS},
    )
