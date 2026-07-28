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
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

# Hosts the parser will refuse outright regardless of DNS resolution
# (some operators block DNS to RFC1918 ranges; this catches the literal
# IP / hostname forms too).
_BLOCKED_LITERAL_HOSTS = frozenset({"localhost", "metadata.google.internal"})

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeOutboundURL(ValueError):
    """Raised when a URL maps to a private / loopback / metadata target."""


async def check_outbound_url_async(url: str, *, allow_private: bool = False) -> None:
    """Async variant that resolves via the loop's thread-pool DNS so a
    slow / SERVFAIL upstream nameserver can't stall the whole event loop
    on every webhook dispatch.
    """
    _validate_url_shape(url, allow_private=allow_private)
    if allow_private:
        return
    host = (urlparse(url).hostname or "").strip().lower()
    infos = await _resolve_host(host)
    _refuse_private_addresses(host, infos)


async def _resolve_host(host: str) -> list:
    """One DNS resolution via the loop's thread-pool resolver. Raises
    `UnsafeOutboundURL` on failure so callers surface a clear message."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeOutboundURL(
            f"DNS lookup failed for {host!r}: {exc}."
        ) from exc


async def safe_post(
    url: str,
    *,
    content: bytes | str | None = None,
    json: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    allow_private: bool = False,
) -> httpx.Response:
    """POST to an admin-supplied URL with DNS-rebinding protection.

    `check_outbound_url_async` alone is TOCTOU-vulnerable: it resolves the
    hostname at validation time, then httpx resolves it AGAIN at connection
    time. An attacker controlling the authoritative DNS can answer with a
    safe IP for the first lookup and a private one for the second (classic
    DNS rebinding). This helper closes that window:

      1. resolve the hostname exactly once;
      2. validate every resolved address with the same private/loopback/
         metadata checks as the validators above;
      3. connect httpx to one of the vetted IPs by rewriting the URL host,
         so no second resolution ever happens.

    Virtual hosting and TLS keep working because the original hostname is
    preserved in the `Host` header and — for https — as the TLS SNI /
    certificate-verification name via httpx's `sni_hostname` request
    extension (httpcore passes it as `server_hostname` to the ssl module,
    which drives both SNI and hostname verification).

    Redirects are never followed: a 3xx pointing at an internal address
    would reopen the hole the pinning just closed.
    """
    _validate_url_shape(url, allow_private=allow_private)

    if allow_private:
        # Operator explicitly opted out (dev / isolated network) — plain
        # POST, no pinning, but still no redirect-following.
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            return await client.post(url, content=content, json=json, headers=headers)

    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    infos = await _resolve_host(host)
    _refuse_private_addresses(host, infos)

    pinned_ip = _first_resolved_ip(host, infos)

    # Rebuild the URL with the vetted IP as the host. IPv6 literals need
    # brackets in the authority component.
    ip_authority = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    if parsed.port is not None:
        ip_authority = f"{ip_authority}:{parsed.port}"
    pinned_url = urlunparse(parsed._replace(netloc=ip_authority))

    # httpx would otherwise derive `Host` from the (IP) URL — force the
    # original hostname so name-based virtual hosts route correctly.
    host_header = host if parsed.port is None else f"{host}:{parsed.port}"
    request_headers = dict(headers or {})
    request_headers["Host"] = host_header

    extensions: dict[str, Any] = {}
    if parsed.scheme.lower() == "https":
        extensions["sni_hostname"] = host

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        return await client.post(
            pinned_url,
            content=content,
            json=json,
            headers=request_headers,
            extensions=extensions,
        )


def _first_resolved_ip(host: str, infos: list) -> str:
    """Pick the first usable address out of a getaddrinfo result. All the
    entries already passed `_refuse_private_addresses`, so any of them is
    safe to pin."""
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
        if not sockaddr:
            continue
        addr_text = sockaddr[0]
        try:
            ipaddress.ip_address(addr_text)
        except ValueError:
            continue
        return addr_text
    raise UnsafeOutboundURL(f"DNS lookup for {host!r} returned no usable address.")


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


# RFC 6598 CGNAT space (carrier-grade NAT). Python's `is_private` flag
# does NOT include this range — `100.64.x.x` reports as neither
# `is_private` nor `is_reserved`. Common for VPN / ISP / internal
# service networks, so we MUST refuse explicitly. The Codex review on
# PR #90 caught this gap.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for any address not safe to dispatch a webhook to.

    Uses `is_global` as the inverse contract (anything that isn't a
    public, globally-routable address is treated as private). Pin the
    cloud-metadata literal and the CGNAT range explicitly because
    `is_global` covers most of those but the IPv4 `is_global` flag was
    flaky across stdlib versions for documentation-range edges.
    """
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return True
    if ip.is_private or ip.is_unspecified:
        return True
    # Not-global covers RFC 5737 documentation ranges, RFC 6890 special-use,
    # and various IPv6 reservations that the individual flags above miss.
    if not ip.is_global:
        return True
    # 169.254.169.254 / fd00:ec2::254 — cloud-metadata endpoints. Both
    # are already covered by `is_link_local` / `is_private`, but pin
    # the literal for clarity and to survive any future stdlib change.
    if isinstance(ip, ipaddress.IPv4Address) and str(ip) == "169.254.169.254":
        return True
    # CGNAT — see _CGNAT_NETWORK comment above.
    return isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK


__all__ = [
    "UnsafeOutboundURL",
    "check_outbound_url_async",
    "safe_post",
]
