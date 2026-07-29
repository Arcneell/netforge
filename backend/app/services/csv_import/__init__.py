"""CSV import — parsing, validation, per-entity upsert.

Conventions (see docs/08-import-csv.md):
  - Delimiter `;`, encoding `utf-8-sig` (Excel FR-compatible).
  - First line = headers (case-sensitive).
  - Reference columns (`site_code`, `vlan_id`, ...) are resolved against the
    current DB content; a missing reference produces a row-level error.
  - Upsert by the natural key called out in each `_Row` model docstring.
  - The whole import runs in a single transaction. On any error the
    transaction rolls back and the report lists everything we know.
  - `dry_run=True` always rolls back even on success.

Package layout — the module was split along its own seams, nothing moved
between responsibilities:

  `rows`     Pydantic row models, one per entity, plus the cell coercions.
  `parsing`  Bytes → rows: decoding, header rewriting, ZIP explosion, caps.
  `errors`   `_RefError` and the error → `ImportErrorRow` mapping.
  `refs`     Reference resolution + the per-import cache and subnet index.
  `persist`  One upsert function per entity, plus the `SPECS` registry.
  `detect`   Header-based entity auto-detection.
  `driver`   Transaction boundary: `run_import` / `run_bulk_import`.

This `__init__` is a pure facade: every name the old single-file module
exposed is re-exported here, so `from app.services.csv_import import X` and
`csv_import.X` keep working unchanged for every caller.
"""

from __future__ import annotations

from app.services.csv_import.detect import (
    ALL_HEADERS,
    REQUIRED_HEADERS,
    _all_headers,
    _DetectMatch,
    _required_headers,
    _score_entity,
    detect_entity,
)
from app.services.csv_import.driver import (
    _import_one,
    _SingleResult,
    _sort_bulk_reports,
    run_bulk_import,
    run_import,
)
from app.services.csv_import.errors import (
    _format_validation_errors,
    _friendly_integrity,
    _RefError,
)
from app.services.csv_import.parsing import (
    BULK_MAX_FILES,
    BULK_MAX_TOTAL_BYTES,
    ZIP_MAX_UNCOMPRESSED,
    _parse_csv,
    _raise_zip_too_large,
    _read_headers,
    apply_column_mapping,
    extract_zip,
)
from app.services.csv_import.persist import (
    IMPORT_ORDER,
    SPECS,
    _ImportSpec,
    _persist_device,
    _persist_ip,
    _persist_link,
    _persist_port,
    _persist_room,
    _persist_site,
    _persist_subnet,
    _persist_switch,
    _persist_vlan,
)
from app.services.csv_import.refs import (
    _device_by_name,
    _find_subnet_for,
    _port_on_switch,
    _ref_cache_scope,
    _RefCache,
    _refs,
    _room_by_codes,
    _site_by_code,
    _SubnetIndex,
    _switch_by_name,
    _vlan_by_id,
)
from app.services.csv_import.rows import (
    _MAC_PATTERNS,
    _coerce_bool,
    _DeviceRow,
    _empty_to_none,
    _IpRow,
    _LinkRow,
    _normalize_mac,
    _parse_csv_list,
    _PortRow,
    _RoomRow,
    _SiteRow,
    _SubnetRow,
    _SwitchRow,
    _VlanRow,
)

# The public surface is the four callables below; everything else is exported
# for the callers and tests that reached into the old flat module. Keeping the
# private names listed here is deliberate — it makes the compatibility
# contract explicit instead of accidental.
__all__ = [
    "ALL_HEADERS",
    "BULK_MAX_FILES",
    "BULK_MAX_TOTAL_BYTES",
    "IMPORT_ORDER",
    "REQUIRED_HEADERS",
    "SPECS",
    "ZIP_MAX_UNCOMPRESSED",
    "_MAC_PATTERNS",
    "_DetectMatch",
    "_DeviceRow",
    "_ImportSpec",
    "_IpRow",
    "_LinkRow",
    "_PortRow",
    "_RefCache",
    "_RefError",
    "_RoomRow",
    "_SingleResult",
    "_SiteRow",
    "_SubnetIndex",
    "_SubnetRow",
    "_SwitchRow",
    "_VlanRow",
    "_all_headers",
    "_coerce_bool",
    "_device_by_name",
    "_empty_to_none",
    "_find_subnet_for",
    "_format_validation_errors",
    "_friendly_integrity",
    "_import_one",
    "_normalize_mac",
    "_parse_csv",
    "_parse_csv_list",
    "_persist_device",
    "_persist_ip",
    "_persist_link",
    "_persist_port",
    "_persist_room",
    "_persist_site",
    "_persist_subnet",
    "_persist_switch",
    "_persist_vlan",
    "_port_on_switch",
    "_raise_zip_too_large",
    "_read_headers",
    "_ref_cache_scope",
    "_refs",
    "_required_headers",
    "_room_by_codes",
    "_score_entity",
    "_site_by_code",
    "_sort_bulk_reports",
    "_switch_by_name",
    "_vlan_by_id",
    "apply_column_mapping",
    "detect_entity",
    "extract_zip",
    "run_bulk_import",
    "run_import",
]
