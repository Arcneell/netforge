"""`net_text.ip_text` — shared INET canonicalisation helper (Fix #11).

Previously duplicated verbatim as `_ip_text` in both `services/subnets.py`
and `services/ips.py`; both now import the single copy here (re-exported
under the same private name so existing call sites don't change).
"""

from __future__ import annotations

from ipaddress import IPv4Interface

from app.services.ips import _ip_text as ips_ip_text
from app.services.net_text import ip_text
from app.services.subnets import _ip_text as subnets_ip_text


def test_ip_text_strips_the_mask_asyncpg_adds() -> None:
    assert ip_text(IPv4Interface("10.0.0.5/32")) == "10.0.0.5"


def test_ip_text_passes_through_a_bare_string() -> None:
    assert ip_text("10.0.0.5") == "10.0.0.5"


def test_subnets_and_ips_both_reexport_the_same_shared_helper() -> None:
    assert subnets_ip_text is ip_text
    assert ips_ip_text is ip_text
