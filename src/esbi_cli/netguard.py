"""Refuse to fetch URLs that could reach internal services (SSRF): email links are untrusted."""

import ipaddress
import socket
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeURL(ValueError):
    pass


class CannotResolve(UnsafeURL):
    """The host does not resolve at all (a dead domain): unreachable, not "refused"."""


NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address) and ip in NAT64:  # judge the IPv4 address it wraps
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def check_public_url(url: str, resolver: Callable = socket.getaddrinfo) -> list[str]:
    """Raise UnsafeURL unless url is http(s) and its host resolves only to public addresses.
    Returns those addresses: connect to one of them, never to the name (see safe_get)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL(f"Only http(s) URLs are fetched, not {parsed.scheme or 'this'!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURL("The URL has no host")
    try:
        addresses = [str(ipaddress.ip_address(host))]  # an IP literal needs no DNS
    except ValueError:
        try:
            infos = resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise CannotResolve(f"Cannot resolve {host}: {exc}") from None
        addresses = list(dict.fromkeys(info[4][0] for info in infos))
    for address in addresses:
        if not _is_public(address):
            raise UnsafeURL(f"{host} resolves to a non-public address ({address})")
    return addresses


MAX_REDIRECTS = 5
MAX_BYTES = 20_000_000  # a page or PDF bigger than this is not a note
DEADLINE = 120  # seconds for one whole download: a server that trickles bytes cannot hold a run


def _read_capped(response: httpx.Response, url: str) -> httpx.Response:
    body, started = bytearray(), time.monotonic()
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > MAX_BYTES:
            raise UnsafeURL(f"The response is larger than {MAX_BYTES // 1_000_000} MB")
        if time.monotonic() - started > DEADLINE:
            raise UnsafeURL(f"The download took more than {DEADLINE} s")
    return httpx.Response(
        response.status_code,
        headers={k: v for k, v in response.headers.items() if k.lower() != "content-encoding"},
        content=bytes(body),
        request=httpx.Request("GET", url),  # the URL the caller asked for, not the pinned IP
    )


def _fetch_pinned(client: httpx.Client, url: str, addresses: list[str]) -> httpx.Response:
    target = httpx.URL(url)
    for i, address in enumerate(addresses):
        try:
            with client.stream(
                "GET",
                target.copy_with(host=address),
                headers={"Host": target.netloc.decode()},
                extensions={"sni_hostname": target.host},
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    return httpx.Response(response.status_code, headers=response.headers)
                return _read_capped(response, url)
        except httpx.ConnectError:
            if i == len(addresses) - 1:  # tried them all
                raise


def safe_get(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolver: Callable = socket.getaddrinfo,
    headers: dict | None = None,
    timeout: float = 30,
) -> httpx.Response:
    """GET a URL, following redirects manually so every hop passes check_public_url.

    The name is resolved once per hop, and the request goes to one of the addresses that passed
    the check (the URL carries the IP; Host and the TLS server name stay the original host, so
    certificates are still verified for it). A second lookup by the HTTP client, which a hostile
    DNS server could answer with a private address, never happens."""
    own_client = client is None
    client = client or httpx.Client(headers=headers, timeout=timeout)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            response = _fetch_pinned(client, url, check_public_url(url, resolver=resolver))
            if not response.is_redirect:
                return response
            url = urljoin(url, response.headers["location"])
        raise UnsafeURL(f"Too many redirects (more than {MAX_REDIRECTS})")
    finally:
        if own_client:
            client.close()
