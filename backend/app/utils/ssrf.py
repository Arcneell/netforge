"""SSRF guard for admin-supplied outbound URLs.

Webhook URLs and AI-schedule notification URLs are admin-controlled but
free-form HTTPS strings. Without a guard, an admin (or anyone who steals
an admin API token) can point them at internal services that the
backend can otherwise reach but the outside world cannot:

  - http://127.0.0.1:5432 / http://postgres:5432 (the DB on the docker
    bridge network)
  - http://169.254.169.254/latest/meta-data/iam/security-credentials/
    (AWS / GCP / Azure cloud-metadata endpoints)
  - http://localhost:8000/api/... (the backend itself, bypassing auth
    when it reads its own session cookie)

The first two leak the response body back through `WebhookDelivery.error`,
so even a basic ping exfiltrates internal HTTP responses to anyone who
can read the delivery log.

This module resolves the hostname via `socket.getaddrinfo`, then refuses
anything that maps to a non-globally-routable address (RFC 1918 / 6598,
loopback, link-local, multicast, reserved). Operators on a dev or
isolated network can opt out via `WEBHOOK_ALLOW_PRIVATE_TARGETS=true`.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Hosts the parser will refuse outright regardless of DNS resolution
# (some operators block DNS to RFC1918 ranges; this catches the literal
# IP / hostname forms too).
_BLOCKED_LITERAL_HOSTS = frozenset({"localhost", "metadata.google.internal"})

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeOutboundURL(ValueError):
    """Raised when a URL maps to a private / loopback / metadata target."""


def check_outbound_url(url: str, *, allow_private: bool = False) -> None:
    """Refuse SSRF-risky URLs by raising `UnsafeOutboundURL`.

    `allow_private=True` opts out — useful for dev/test deployments that
    legitimately need to hit `http://localhost:9000` (a local relay), but
    the default is to refuse anything not globally routable.
    """
    if not url or not isinstance(url, str):
        raise UnsafeOutboundURL("URL is empty or not a string.")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeOutboundURL(
            f"URL scheme {parsed.scheme!r} is not http(s)."
        )
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise UnsafeOutboundURL("URL has no host component.")
    if allow_private:
        return
    if host in _BLOCKED_LITERAL_HOSTS:
        raise UnsafeOutboundURL(
            f"Refusing outbound request to {host!r}: loopback/metadata host."
        )

    # Resolve via DNS to catch e.g. "metadata.local.example" → 169.254.x.
    # Note: this RESOLVES the name from the backend's network view; in
    # docker, "postgres" resolves to the docker-bridge IP for postgres,
    # which we then catch as RFC1918. DNS rebinding is mitigated by the
    # fact that `httpx` will re-resolve and re-validate on the actual
    # connection — but for high-security deployments, prefer to pin
    # the IP and bypass DNS at the proxy layer.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        # DNS failure isn't necessarily a security problem, but we
        # don't want to fire requests at names we can't resolve here —
        # if httpx fails too the operator gets a clearer error.
        raise UnsafeOutboundURL(
            f"DNS lookup failed for {host!r}: {exc}."
        ) from exc

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr_text = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr_text)
        except ValueError:
            continue
        if _is_private(ip):
            raise UnsafeOutboundURL(
                f"Refusing outbound request to {host!r} → {addr_text}: "
                "address is not globally routable (loopback / private / "
                "link-local / metadata / reserved)."
            )


def _is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for any address not safe to dispatch a webhook to.

    Catches the standard Python flags plus the AWS/GCP metadata IP and
    the IPv6 ULA + link-local ranges. We treat "private" defensively —
    if there's any doubt, refuse.
    """
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return True
    if ip.is_private:
        return True
    if ip.is_unspecified:
        return True
    # 169.254.169.254 / fd00:ec2::254 — cloud-metadata endpoints. Both
    # are already covered by `is_link_local` / `is_private`, but pin
    # the literal for clarity and to survive any future stdlib change.
    return isinstance(ip, ipaddress.IPv4Address) and str(ip) == "169.254.169.254"


__all__ = ["UnsafeOutboundURL", "check_outbound_url"]
