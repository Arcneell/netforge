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

import asyncio
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
    """Synchronous wrapper — kept for callers that don't have an event
    loop handy. Prefer `check_outbound_url_async` from any coroutine,
    because the underlying `socket.getaddrinfo` blocks for the duration
    of DNS resolution and would otherwise stall the whole loop.
    """
    _validate_url_shape(url, allow_private=allow_private)
    if allow_private:
        return
    host = (urlparse(url).hostname or "").strip().lower()
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeOutboundURL(
            f"DNS lookup failed for {host!r}: {exc}."
        ) from exc
    _refuse_private_addresses(host, infos)


async def check_outbound_url_async(url: str, *, allow_private: bool = False) -> None:
    """Async variant that resolves via the loop's thread-pool DNS so a
    slow / SERVFAIL upstream nameserver can't stall the whole event loop
    on every webhook dispatch.
    """
    _validate_url_shape(url, allow_private=allow_private)
    if allow_private:
        return
    host = (urlparse(url).hostname or "").strip().lower()
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeOutboundURL(
            f"DNS lookup failed for {host!r}: {exc}."
        ) from exc
    _refuse_private_addresses(host, infos)


def _validate_url_shape(url: str, *, allow_private: bool) -> None:
    """Shape-only checks (scheme, host present, literal-host blocklist).
    Caller is responsible for the DNS-side check, which differs between
    the sync and async variants above."""
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


def _refuse_private_addresses(host: str, infos: list) -> None:
    """Raise `UnsafeOutboundURL` if any resolved address is private /
    loopback / metadata / link-local / multicast / reserved.

    Note on DNS rebinding: this resolves once at validation time but
    httpx will resolve again at connection time, so an attacker who
    controls the authoritative DNS for `host` can return a safe IP
    here and a private one to httpx. The mitigation is to pre-resolve
    via this helper AND connect to a pinned IP — see the
    `safe_post` helper that wraps httpx for outbound webhooks.
    """
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
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


__all__ = [
    "UnsafeOutboundURL",
    "check_outbound_url",
    "check_outbound_url_async",
]
