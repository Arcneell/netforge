"""Request-shape helpers shared by middleware.

Centralises the "what is the real client IP?" logic so the rate limiter and
the audit-log middleware can't drift apart on the security-sensitive bits.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from fastapi import Request

from app.config import get_settings


def client_ip(request: Request) -> str | None:
    """Return the trusted client IP for the request, or None when unknown.

    Trust order:
      1. ``X-Real-IP`` — ONLY when the immediate TCP peer is inside
         ``TRUSTED_PROXIES`` (CIDR list, defaults to loopback + the
         standard docker bridge). The bundled nginx unconditionally
         overwrites this header with ``$remote_addr`` so it is safe to
         trust on that hop, but for deployments that put the backend
         behind a different reverse proxy (or none at all), we must
         refuse to honour the header from arbitrary clients — otherwise
         anyone can spoof X-Real-IP to bypass the per-IP rate limit
         and to poison ``audit_log.ip_address`` / ``sessions.ip_address``.
      2. ``request.client.host`` — the immediate TCP peer as seen by
         uvicorn. In dev (no nginx) this is the actual client; in prod
         behind a trusted nginx, X-Real-IP already won at step 1.

    ``X-Forwarded-For`` is intentionally NOT trusted. Our nginx config
    uses ``$proxy_add_x_forwarded_for`` which APPENDS, leaving the
    first entry fully attacker-controlled — keying on it would let a
    hot-looped script rotate the value per request and bypass any
    per-IP rate limit.

    For multi-proxy deployments (LB → nginx → backend), add the LB
    subnet to ``TRUSTED_PROXIES`` and configure nginx with
    ``real_ip_header X-Real-IP;`` plus a matching ``set_real_ip_from``.
    """
    peer = request.client.host if request.client else None
    real_ip = request.headers.get("x-real-ip")
    if real_ip and peer and _is_trusted_proxy(peer):
        return real_ip.strip()
    return peer


@lru_cache(maxsize=1)
def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse `settings.trusted_proxies` once. Defaults to loopback +
    the standard docker bridge so the bundled nginx → backend hop
    works out-of-the-box; any deployment that adds an external proxy
    must extend the setting.
    """
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    raw = (get_settings().trusted_proxies or "").strip()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            nets.append(ipaddress.ip_network(piece, strict=False))
        except ValueError:
            # Operator typo'd a CIDR — skip silently and log via the
            # config validator path (the rate-limiter shouldn't crash
            # on a config error).
            continue
    return tuple(nets)


def _is_trusted_proxy(peer: str) -> bool:
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(ip in net for net in _trusted_proxy_networks())
