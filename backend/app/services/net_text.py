"""Shared INET/CIDR text-canonicalisation helper.

Used by `services/subnets.py` and `services/ips.py` — both need to turn
whatever asyncpg hands back for an INET column into a bare dotted-quad
before comparing it against strings built from `ipaddress.IPv4Address`.
Was duplicated verbatim in both modules (Codex P1 on #80); this is the
single copy both import.
"""

from __future__ import annotations

from ipaddress import IPv4Address


def ip_text(value: object) -> str:
    """Canonicalise whatever asyncpg returns for an INET column to a bare
    dotted-quad.

    asyncpg decodes `inet` to `ipaddress.IPv4Interface` by default, and
    `str(IPv4Interface('10.0.0.1/32'))` returns `'10.0.0.1/32'` — the
    trailing `/32` breaks any comparison against a plain
    `str(IPv4Address(...))`. Strip the mask and re-parse with
    `IPv4Address` so we always end up with the bare dotted-quad used
    everywhere else (next_free_ip, list_subnet_ips, bulk_ip_range, ...).
    """
    text = str(value)
    if "/" in text:
        text = text.split("/", 1)[0]
    return str(IPv4Address(text))
