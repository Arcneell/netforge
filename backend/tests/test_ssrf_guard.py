"""Tests for the SSRF guard on admin-supplied outbound URLs.

Covers the async validator (`check_outbound_url_async`) and the pinning
POST helper (`safe_post`). The dead sync variant was removed — every
caller runs inside the event loop.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import httpx
import pytest

import app.utils.ssrf as ssrf
from app.utils.ssrf import UnsafeOutboundURL, check_outbound_url_async, safe_post


def _fake_resolve(host: str, *_args, **_kwargs):
    """Map a small set of hostnames to fixed addresses for tests."""
    mapping = {
        # 8.8.8.8 is a real global IPv4 — RFC5737 documentation ranges
        # (203.0.113.*) are flagged is_reserved by Python so they'd be
        # refused, which would mask the "happy path" assertion.
        "public.example.com": "8.8.8.8",
        "internal.example.com": "10.1.2.3",
        "metadata.cloud.example": "169.254.169.254",
        "loopback.example": "127.0.0.1",
        "link-local.example": "169.254.10.5",
        "v6.example": "2606:4700::1111",
        "v6-loopback.example": "::1",
    }
    addr = mapping.get(host)
    if addr is None:
        # The guard catches socket.gaierror specifically — raising plain
        # OSError would let it leak past the except clause.
        raise socket.gaierror(f"no fixture for {host!r}")
    # Mirror socket.getaddrinfo's tuple shape: (family, type, proto, canon, sockaddr)
    return [(0, 0, 0, "", (addr, 0))]


@pytest.fixture
def fake_dns():
    # asyncio's default loop.getaddrinfo runs socket.getaddrinfo in the
    # thread-pool executor, so patching the socket module attribute covers
    # the async resolution path too.
    with patch("app.utils.ssrf.socket.getaddrinfo", side_effect=_fake_resolve):
        yield


# --- check_outbound_url_async ------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_empty_url() -> None:
    with pytest.raises(UnsafeOutboundURL):
        await check_outbound_url_async("")


@pytest.mark.asyncio
async def test_rejects_non_http_scheme() -> None:
    with pytest.raises(UnsafeOutboundURL, match="scheme"):
        await check_outbound_url_async("file:///etc/passwd")
    with pytest.raises(UnsafeOutboundURL, match="scheme"):
        await check_outbound_url_async("gopher://attacker.example/")


@pytest.mark.asyncio
async def test_rejects_literal_localhost(fake_dns) -> None:
    """`http://localhost/...` is a common SSRF vector even before DNS;
    pin the literal-host refusal so we don't depend on resolution."""
    with pytest.raises(UnsafeOutboundURL, match="loopback"):
        await check_outbound_url_async("http://localhost/foo")


@pytest.mark.asyncio
async def test_rejects_metadata_literal_host(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL, match=r"loopback|metadata"):
        await check_outbound_url_async("http://metadata.google.internal/x")


@pytest.mark.asyncio
async def test_rejects_rfc1918_target(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL, match="not globally routable"):
        await check_outbound_url_async("https://internal.example.com/hook")


@pytest.mark.asyncio
async def test_rejects_aws_metadata(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        await check_outbound_url_async("http://metadata.cloud.example/latest/meta-data/")


@pytest.mark.asyncio
async def test_rejects_link_local(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        await check_outbound_url_async("http://link-local.example/")


@pytest.mark.asyncio
async def test_rejects_loopback_v4(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        await check_outbound_url_async("http://loopback.example/")


@pytest.mark.asyncio
async def test_rejects_loopback_v6(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        await check_outbound_url_async("http://v6-loopback.example/")


@pytest.mark.asyncio
async def test_allows_global_public_address(fake_dns) -> None:
    # Should not raise.
    await check_outbound_url_async("https://public.example.com/webhook")


@pytest.mark.asyncio
async def test_allows_global_ipv6(fake_dns) -> None:
    await check_outbound_url_async("https://v6.example/webhook")


@pytest.mark.asyncio
async def test_allow_private_opt_out_skips_check() -> None:
    """Operators on a dev or isolated network may legitimately need to
    hit `http://localhost:9000`. The opt-out flag short-circuits before
    DNS resolution, so the guard never fires (matches the behaviour
    `webhook_allow_private_targets=True` enables in production)."""
    # No fake_dns fixture — if the validator tried to resolve, we'd see
    # a real DNS error. The opt-out must short-circuit BEFORE that point.
    await check_outbound_url_async("http://localhost:9000/relay", allow_private=True)
    await check_outbound_url_async("http://127.0.0.1:5432/", allow_private=True)


@pytest.mark.asyncio
async def test_dns_failure_raises_unsafe(fake_dns) -> None:
    """Unresolvable names should refuse rather than fall through — httpx
    would also fail, but the guard surfaces a clearer error."""
    with pytest.raises(UnsafeOutboundURL, match="DNS"):
        await check_outbound_url_async("https://does-not-exist.example/x")


# --- safe_post (DNS-rebinding pinning) ---------------------------------------


# Bound at import time — the fixtures below monkeypatch httpx.AsyncClient,
# so the factory must hold the real class to avoid recursing into itself.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _CapturingClientFactory:
    """Stand-in for httpx.AsyncClient that routes through a MockTransport
    and records the constructor kwargs + the request the handler saw."""

    def __init__(self, handler) -> None:
        self._handler = handler
        self.client_kwargs: dict | None = None
        self.request: httpx.Request | None = None

    def __call__(self, **kwargs) -> httpx.AsyncClient:
        self.client_kwargs = kwargs

        def _record(request: httpx.Request) -> httpx.Response:
            self.request = request
            return self._handler(request)

        kwargs.setdefault("transport", httpx.MockTransport(_record))
        return _REAL_ASYNC_CLIENT(**kwargs)


@pytest.fixture
def capture_client(monkeypatch: pytest.MonkeyPatch):
    factory = _CapturingClientFactory(lambda _req: httpx.Response(200, content=b"ok"))
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", factory)
    return factory


@pytest.mark.asyncio
async def test_safe_post_pins_connection_to_resolved_ip(fake_dns, capture_client) -> None:
    """The wire request must target the vetted IP (no second resolution),
    while the Host header keeps the original name for virtual hosting."""
    resp = await safe_post("http://public.example.com:8080/hook?x=1", content=b"{}")
    assert resp.status_code == 200
    req = capture_client.request
    assert req is not None
    assert req.url.host == "8.8.8.8"
    assert req.url.port == 8080
    assert req.url.raw_path == b"/hook?x=1"
    assert req.headers["host"] == "public.example.com:8080"


@pytest.mark.asyncio
async def test_safe_post_sets_sni_hostname_for_https(fake_dns, capture_client) -> None:
    """For https the original hostname must drive SNI + certificate
    verification even though the URL now carries the pinned IP."""
    await safe_post("https://public.example.com/hook", content=b"{}")
    req = capture_client.request
    assert req is not None
    assert req.url.host == "8.8.8.8"
    assert req.extensions.get("sni_hostname") == "public.example.com"
    assert req.headers["host"] == "public.example.com"


@pytest.mark.asyncio
async def test_safe_post_brackets_ipv6_pinned_host(fake_dns, capture_client) -> None:
    await safe_post("https://v6.example/webhook", content=b"{}")
    req = capture_client.request
    assert req is not None
    assert req.url.host == "2606:4700::1111"
    assert req.extensions.get("sni_hostname") == "v6.example"


@pytest.mark.asyncio
async def test_safe_post_refuses_private_target(fake_dns, capture_client) -> None:
    with pytest.raises(UnsafeOutboundURL, match="not globally routable"):
        await safe_post("https://internal.example.com/hook", content=b"{}")
    # No HTTP request must have been attempted.
    assert capture_client.request is None


@pytest.mark.asyncio
async def test_safe_post_never_follows_redirects(fake_dns, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 302 to an internal address would reopen the SSRF hole — the
    response must come back unfollowed for the caller to treat as-is."""
    factory = _CapturingClientFactory(
        lambda _req: httpx.Response(302, headers={"Location": "http://127.0.0.1:5432/"})
    )
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", factory)
    resp = await safe_post("http://public.example.com/hook", content=b"{}")
    assert resp.status_code == 302
    assert factory.client_kwargs is not None
    assert factory.client_kwargs.get("follow_redirects") is False


@pytest.mark.asyncio
async def test_safe_post_allow_private_skips_pinning(capture_client) -> None:
    """Opt-out mode posts to the URL as-is (no DNS, no pinning) — needed
    for dev relays on localhost. Still no redirect following."""
    resp = await safe_post("http://127.0.0.1:9000/relay", content=b"{}", allow_private=True)
    assert resp.status_code == 200
    req = capture_client.request
    assert req is not None
    assert req.url.host == "127.0.0.1"
    assert capture_client.client_kwargs.get("follow_redirects") is False
