import socket
from unittest.mock import MagicMock

import pytest

import paper_urls as urls


@pytest.mark.parametrize("value", [
    "http://example.org/a", "https://127.0.0.1/a", "https://10.0.0.5/a", "https://[::1]/a",
    "https://localhost/a", "https://printer.local/a", "https://svc.internal/a", "https://user:pw@example.org/a",
    "https://example.org:8443/a", "https://example/a", "https://exa mple.org/a", "https://example.org\\a",
    "https://example.org/" + "a" * 5000, None, 5,
])
def test_non_public_or_malformed_urls_are_rejected(value):
    assert urls.public_url(value) is None


def test_public_https_urls_pass():
    assert urls.public_url("https://example.org/paper.pdf?x=1") == "https://example.org/paper.pdf?x=1"
    assert urls.public_url("https://8.8.8.8/a") == "https://8.8.8.8/a"


def test_doi_normalisation():
    assert urls.normalize_doi("https://doi.org/10.1234/AbC") == "10.1234/abc"
    assert urls.normalize_doi("doi: 10.1234/abc") == "10.1234/abc"
    assert urls.normalize_doi("not-a-doi") is None and urls.normalize_doi(None) is None


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=(b"%PDF-1.7",)):
        self.status, self.headers, self._chunks = status, headers or {}, chunks
        self.closed = False

    def stream(self, size, decode_content=False):
        yield from self._chunks

    def close(self):
        self.closed = True


class FakePool:
    responses = []
    seen = []

    def __init__(self, host, **kwargs):
        FakePool.seen.append((host, kwargs))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def urlopen(self, method, path, **kwargs):
        FakePool.seen.append((method, path, kwargs))
        return FakePool.responses.pop(0)


@pytest.fixture
def network(monkeypatch):
    FakePool.responses, FakePool.seen = [], []
    resolved = {"example.org": ["93.184.216.34"], "cdn.example.org": ["93.184.216.35"],
                "evil.example": ["10.0.0.5"], "mixed.example": ["93.184.216.34", "127.0.0.1"]}
    monkeypatch.setattr(urls.socket, "getaddrinfo", lambda host, port, type=None: [
        (socket.AF_INET, type, 0, "", (ip, port)) for ip in resolved[host]])
    monkeypatch.setattr(urls.urllib3, "HTTPSConnectionPool", FakePool)
    return FakePool


def test_download_pins_checked_ip_and_keeps_hostname_verification(network):
    network.responses = [FakeResponse(chunks=(b"%PDF", b"-1.7"))]
    assert urls.download_pdf("https://example.org/a.pdf?x=1", 1000) == b"%PDF-1.7"
    host, kwargs = network.seen[0]
    assert host == "93.184.216.34" and kwargs["server_hostname"] == "example.org"
    assert kwargs["assert_hostname"] == "example.org" and kwargs["cert_reqs"] == "CERT_REQUIRED"
    method, path, request = network.seen[1]
    assert (method, path) == ("GET", "/a.pdf?x=1") and request["redirect"] is False
    assert request["headers"]["Host"] == "example.org"


def test_redirects_are_followed_and_revalidated(network):
    network.responses = [FakeResponse(302, {"Location": "https://cdn.example.org/real.pdf"}), FakeResponse()]
    assert urls.download_pdf("https://example.org/a", 1000) == b"%PDF-1.7"
    assert network.seen[2][0] == "93.184.216.35"


@pytest.mark.parametrize("location", ["http://example.org/a", "https://127.0.0.1/a", "https://evil.example/a"])
def test_redirect_to_unsafe_destination_is_refused(network, location):
    network.responses = [FakeResponse(302, {"Location": location})]
    with pytest.raises(ValueError):
        urls.download_pdf("https://example.org/a", 1000)


@pytest.mark.parametrize("url", ["https://evil.example/a.pdf", "https://mixed.example/a.pdf"])
def test_hosts_resolving_to_private_addresses_are_refused(network, url):
    with pytest.raises(ValueError, match="public addresses"):
        urls.download_pdf(url, 1000)
    assert network.seen == []


def test_size_limit_status_and_redirect_loops(network):
    network.responses = [FakeResponse(chunks=(b"x" * 600, b"x" * 600))]
    with pytest.raises(ValueError, match="20 MB"):
        urls.download_pdf("https://example.org/a", 1000)
    network.responses = [FakeResponse(403)]
    with pytest.raises(ValueError, match="not publicly downloadable"):
        urls.download_pdf("https://example.org/a", 1000)
    network.responses = [FakeResponse(302)]
    with pytest.raises(ValueError, match="no destination"):
        urls.download_pdf("https://example.org/a", 1000)
    network.responses = [FakeResponse(302, {"Location": "/again"}) for _ in range(6)]
    with pytest.raises(ValueError, match="Too many"):
        urls.download_pdf("https://example.org/a", 1000)


def test_connection_errors_are_generic(network, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("secret detail")

    monkeypatch.setattr(urls.urllib3, "HTTPSConnectionPool", broken)
    with pytest.raises(ValueError, match="PDF download failed") as caught:
        urls.download_pdf("https://example.org/a", 1000)
    assert "secret" not in str(caught.value)
