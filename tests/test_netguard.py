import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from esbi_cli import netguard
from esbi_cli.netguard import UnsafeURL, check_public_url, safe_get

HOSTS = {
    "localhost": ["127.0.0.1"],
    "internal.test": ["10.0.0.7"],
    "ok.test": ["93.184.216.34"],
    "mixed.test": ["93.184.216.34", "10.0.0.7"],
    "v6.test": ["2606:2800:220:1:248:1893:25c8:1946"],
    "dual.test": ["2606:2800:220:1:248:1893:25c8:1946", "93.184.216.35"],
}


def resolver(host, port, *args, **kwargs):
    if host not in HOSTS:
        raise OSError(f"cannot resolve {host}")
    return [(2, 1, 6, "", (ip, port or 0)) for ip in HOSTS[host]]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/a",
        "http://127.0.0.1/",
        "http://10.0.0.5/x",
        "http://192.168.1.1/",
        "http://172.16.0.9/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://100.64.0.1/",  # carrier-grade NAT
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped loopback
        "http://internal.test/",  # a public-looking name that resolves to a private address
        "http://mixed.test/",  # any private answer is enough to refuse
        "http://nx.test/",  # does not resolve
        "ftp://ok.test/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http:///nohost",
    ],
)
def test_urls_that_could_reach_internal_services_are_refused(url):
    with pytest.raises(UnsafeURL):
        check_public_url(url, resolver=resolver)


@pytest.mark.parametrize(
    "url",
    [
        "https://ok.test/x?y=1",
        "http://93.184.216.34/",
        "https://v6.test/",
        "http://[2606:2800:220:1::1]/",
    ],
)
def test_public_http_and_https_urls_are_allowed(url):
    check_public_url(url, resolver=resolver)


def mock_client(handler, contacted):
    def recording(request):
        contacted.append(request.url.host)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(recording))


def test_a_redirect_into_an_internal_address_is_refused_before_it_is_requested():
    contacted: list[str] = []

    def handler(request):
        return httpx.Response(302, headers={"location": "http://internal.test/admin"})

    with pytest.raises(UnsafeURL, match="non-public"):
        safe_get("https://ok.test/start", client=mock_client(handler, contacted), resolver=resolver)

    assert contacted == ["93.184.216.34"]  # ok.test's checked address; internal.test never


def test_harmless_redirects_are_followed_and_the_final_url_is_reported():
    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, text="hola")

    response = safe_get("https://ok.test/a", client=mock_client(handler, []), resolver=resolver)

    assert (response.status_code, response.text, str(response.url)) == (
        200,
        "hola",
        "https://ok.test/b",
    )


def test_redirect_loops_are_cut_off():
    def handler(request):
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(UnsafeURL, match="Too many redirects"):
        safe_get("https://ok.test/", client=mock_client(handler, []), resolver=resolver)


def recording_client(handler, seen):
    """A client that keeps what the transport receives: where it connects, Host and SNI."""

    def record(request):
        seen.append(
            (
                request.url.host,
                request.headers["host"],
                request.extensions.get("sni_hostname"),
            )
        )
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record))


def test_the_connection_goes_to_the_address_that_was_checked():
    # DNS rebinding: a public answer for the check, a private one for whoever resolves next
    answers = iter([["93.184.216.34"], ["10.0.0.7"], ["10.0.0.7"]])
    calls: list[str] = []

    def rebinding(host, port, *args, **kwargs):
        calls.append(host)
        return [(2, 1, 6, "", (ip, port)) for ip in next(answers)]

    seen: list = []
    client = recording_client(lambda r: httpx.Response(200, text="hola"), seen)

    response = safe_get("https://rebind.test/page", client=client, resolver=rebinding)

    assert calls == ["rebind.test"]  # resolved once: nobody resolves the name again
    assert seen == [("93.184.216.34", "rebind.test", "rebind.test")]  # IP, original Host and SNI
    assert str(response.url) == "https://rebind.test/page"  # callers still see the real URL


def test_every_redirect_hop_is_checked_and_pinned_again():
    seen: list = []

    def handler(request):
        if request.headers["host"] == "ok.test":
            return httpx.Response(302, headers={"location": "https://v6.test:8443/b"})
        return httpx.Response(200, text="fin")

    safe_get("https://ok.test/a", client=recording_client(handler, seen), resolver=resolver)

    assert seen == [
        ("93.184.216.34", "ok.test", "ok.test"),
        ("2606:2800:220:1:248:1893:25c8:1946", "v6.test:8443", "v6.test"),
    ]


def test_another_checked_address_is_tried_when_the_first_does_not_connect():
    seen: list = []

    def handler(request):
        if ":" in request.url.host:
            raise httpx.ConnectError("no IPv6 route here")
        return httpx.Response(200, text="ok")

    response = safe_get(
        "https://dual.test/", client=recording_client(handler, seen), resolver=resolver
    )

    assert response.status_code == 200
    assert [s[0] for s in seen] == ["2606:2800:220:1:248:1893:25c8:1946", "93.184.216.35"]


def test_a_real_request_goes_to_the_pinned_address_with_the_original_host(monkeypatch):
    """No mock: a real httpx client must connect to the IP and never look the name up again."""
    hosts: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hosts.append(self.headers["Host"])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"pinned")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port
    monkeypatch.setattr(netguard, "_is_public", lambda address: True)  # loopback stands in
    try:
        response = safe_get(
            f"http://nowhere.invalid:{port}/x",  # does not resolve: only the pin can reach it
            resolver=lambda host, p, *a, **k: [(2, 1, 6, "", ("127.0.0.1", p))],
        )
    finally:
        server.shutdown()

    assert response.text == "pinned"
    assert hosts == [f"nowhere.invalid:{port}"]


class Recorder(BaseHTTPRequestHandler):
    """A tiny local server that answers 200 and says who it is; `Recorder.hits` lists what it got."""

    def do_GET(self):
        self.server.hits.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.server.name.encode())

    def log_message(self, *args):
        pass


def serve(name):
    server = HTTPServer(("127.0.0.1", 0), Recorder)
    server.name, server.hits = name, []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def proxied(monkeypatch):
    """A real `origin` and a real `proxy` on loopback, with the environment pointing at the proxy.
    The guard checks the address, so loopback is declared public for the test."""
    origin, proxy = serve("origin"), serve("proxy")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.server_port}")
    monkeypatch.setattr(netguard, "_is_public", lambda address: True)
    yield origin, proxy
    origin.shutdown()
    proxy.shutdown()


def fetch_from(origin):
    return safe_get(
        f"http://origin.test:{origin.server_port}/x",
        resolver=lambda host, p, *a, **k: [(2, 1, 6, "", ("127.0.0.1", p))],
    )


def test_an_environment_proxy_is_ignored_by_default_so_the_address_check_is_the_truth(proxied):
    origin, proxy = proxied

    response = fetch_from(origin)

    assert response.text == "origin" and proxy.hits == []  # went straight to the checked address


def test_the_user_can_opt_in_to_the_environment_proxy(proxied, monkeypatch):
    origin, proxy = proxied
    monkeypatch.setattr(netguard, "use_environment_proxy", True)

    response = fetch_from(origin)

    assert response.text == "proxy" and origin.hits == []  # the proxy resolves and connects


def test_no_proxy_is_not_consulted_unless_the_proxy_is_(proxied, monkeypatch):
    origin, proxy = proxied
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")  # would bypass the proxy for the pinned address

    assert fetch_from(origin).text == "origin"  # default: the whole environment is ignored
    monkeypatch.setattr(netguard, "use_environment_proxy", True)
    assert fetch_from(origin).text == "origin" and proxy.hits == []  # opted in: NO_PROXY applies
    monkeypatch.setenv("NO_PROXY", "other.test")
    assert fetch_from(origin).text == "proxy"
