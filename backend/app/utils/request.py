"""Request-shape helpers shared by middleware.

Centralises the "what is the real client IP?" logic so the rate limiter and
the audit-log middleware can't drift apart on the security-sensitive bits.
"""

from __future__ import annotations

from fastapi import Request


def client_ip(request: Request) -> str | None:
    """Return the trusted client IP for the request, or None when unknown.

    Trust order:
      1. ``X-Real-IP`` — nginx sets this to ``$remote_addr`` (the immediate
         TCP peer that connected to nginx). The backend cannot reach nginx's
         private socket directly, so a client cannot spoof this header: nginx
         unconditionally overwrites whatever the client sent.
      2. ``request.client.host`` — the immediate TCP peer as seen by uvicorn.
         In dev (no nginx) this is the actual client; in prod it's nginx, but
         X-Real-IP already won above.

    ``X-Forwarded-For`` is intentionally NOT trusted. Our nginx config uses
    ``$proxy_add_x_forwarded_for`` which APPENDS, leaving the first entry
    fully attacker-controlled — keying on it would let a hot-looped script
    rotate the value per request and bypass any per-IP rate limit.

    For multi-proxy deployments (LB → nginx → backend), set the LB to forward
    X-Real-IP and configure nginx with ``real_ip_header X-Real-IP;`` and a
    ``set_real_ip_from`` directive for the LB subnet.
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None
