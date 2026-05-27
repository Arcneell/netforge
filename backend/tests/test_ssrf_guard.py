"""Tests for the SSRF guard on admin-supplied outbound URLs."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.utils.ssrf import UnsafeOutboundURL, check_outbound_url


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
    with patch("app.utils.ssrf.socket.getaddrinfo", side_effect=_fake_resolve):
        yield


def test_rejects_empty_url() -> None:
    with pytest.raises(UnsafeOutboundURL):
        check_outbound_url("")


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(UnsafeOutboundURL, match="scheme"):
        check_outbound_url("file:///etc/passwd")
    with pytest.raises(UnsafeOutboundURL, match="scheme"):
        check_outbound_url("gopher://attacker.example/")


def test_rejects_literal_localhost(fake_dns) -> None:
    """`http://localhost/...` is a common SSRF vector even before DNS;
    pin the literal-host refusal so we don't depend on resolution."""
    with pytest.raises(UnsafeOutboundURL, match="loopback"):
        check_outbound_url("http://localhost/foo")


def test_rejects_metadata_literal_host(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL, match="loopback|metadata"):
        check_outbound_url("http://metadata.google.internal/x")


def test_rejects_rfc1918_target(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL, match="not globally routable"):
        check_outbound_url("https://internal.example.com/hook")


def test_rejects_aws_metadata(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        check_outbound_url("http://metadata.cloud.example/latest/meta-data/")


def test_rejects_link_local(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        check_outbound_url("http://link-local.example/")


def test_rejects_loopback_v4(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        check_outbound_url("http://loopback.example/")


def test_rejects_loopback_v6(fake_dns) -> None:
    with pytest.raises(UnsafeOutboundURL):
        check_outbound_url("http://v6-loopback.example/")


def test_allows_global_public_address(fake_dns) -> None:
    # Should not raise.
    check_outbound_url("https://public.example.com/webhook")


def test_allows_global_ipv6(fake_dns) -> None:
    check_outbound_url("https://v6.example/webhook")


def test_allow_private_opt_out_skips_check() -> None:
    """Operators on a dev or isolated network may legitimately need to
    hit `http://localhost:9000`. The opt-out flag short-circuits before
    DNS resolution, so the guard never fires (matches the behaviour
    `webhook_allow_private_targets=True` enables in production)."""
    # No fake_dns fixture — if check_outbound_url tried to resolve, we'd see
    # a real DNS error. The opt-out must short-circuit BEFORE that point.
    check_outbound_url("http://localhost:9000/relay", allow_private=True)
    check_outbound_url("http://127.0.0.1:5432/", allow_private=True)


def test_dns_failure_raises_unsafe(fake_dns) -> None:
    """Unresolvable names should refuse rather than fall through — httpx
    would also fail, but the guard surfaces a clearer error."""
    with pytest.raises(UnsafeOutboundURL, match="DNS"):
        check_outbound_url("https://does-not-exist.example/x")
