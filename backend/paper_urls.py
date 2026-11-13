"""Public paper links and bounded, DNS-pinned HTTPS downloads."""

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import urllib3


def public_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value) or "\\" in value:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (url.scheme != "https" or not host or url.username is not None or url.password is not None
                or url.port not in (None, 443) or "%" in host or "." not in host):
            return None
        if host.lower().rstrip(".").endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def normalize_doi(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I).lower()
    return value if re.fullmatch(r"10\.\d+/[^\s]+", value) else None


def download_pdf(url, max_bytes):
    """Validate every redirect and connect to the checked IP, preserving TLS hostname checks."""
    try:
        for _ in range(6):
            if not public_url(url):
                raise ValueError("PDF requires a public HTTPS URL.")
            parsed = urlsplit(url)
            host = parsed.hostname.encode("idna").decode("ascii")
            addresses = [row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise ValueError("PDF host does not resolve to public addresses.")
            # Do not resolve the hostname again at connection time (DNS rebinding).
            with urllib3.HTTPSConnectionPool(addresses[0], port=443, server_hostname=host,
                    assert_hostname=host, cert_reqs="CERT_REQUIRED",
                    timeout=urllib3.Timeout(connect=10, read=45)) as pool:
                response = pool.urlopen("GET", parsed.path or "/" if not parsed.query else
                    (parsed.path or "/") + "?" + parsed.query,
                    headers={"Host": host, "User-Agent": "LiteratureCrew/0.1", "Accept-Encoding": "identity"},
                    assert_same_host=False, redirect=False, retries=False, preload_content=False)
                try:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("PDF redirect has no destination.")
                        url = urljoin(url, location)
                        continue
                    if response.status != 200:
                        raise ValueError("PDF is not publicly downloadable.")
                    buffer = bytearray()
                    for chunk in response.stream(64 * 1024, decode_content=False):
                        buffer.extend(chunk)
                        if len(buffer) > max_bytes:
                            raise ValueError("PDF exceeds the 20 MB download limit.")
                    return bytes(buffer)
                finally:
                    response.close()
        raise ValueError("Too many PDF redirects.")
    except (OSError, urllib3.exceptions.HTTPError) as exc:
        raise ValueError("PDF download failed.") from None
