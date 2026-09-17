"""Phase 06 retrieval worker: bounded, SSRF-safe document fetcher and plain
text/passage extractor (V3 implementation plan, section 9.1 "source
acquisition order" and section 9.3 "tool contracts").

Security model (see docstring on `fetch_document` and the module-level notes
below for the full rationale):

- The hostname is resolved to IP addresses by *this module* (not left to the
  HTTP client), and every resolved address is validated as a public address
  before any network connection is attempted. This defends against SSRF
  against internal/private infrastructure.
- To defend against DNS-rebinding TOCTOU (the resolved-IP-is-public check and
  the actual TCP connect happening against two different DNS answers), the
  validated IP is *pinned* at the transport layer: a custom
  `httpcore` network backend is built per hop that intercepts
  `connect_tcp` and substitutes the already-validated IP address for the
  hop's hostname, while the request URL (and therefore the TLS SNI /
  `Host` header) keeps the original hostname. httpx/httpcore never get a
  chance to re-resolve DNS for that hop.
- Redirects are never auto-followed by the httpx client (`follow_redirects`
  is always False at the client level). Each hop is followed manually, up to
  `policy.max_redirects`, and the SSRF resolve+validate+pin step above is
  repeated for every single hop, including the first.
- The response body is streamed (`response.aiter_bytes()`), and the byte
  counter is checked after every chunk; the fetch aborts (closes the
  response, raises `RetrievalRejected`) the instant the running total would
  exceed `policy.max_bytes`, rather than buffering the full body first.

Fetched text (`FetchedDocument.raw_text`) is untrusted data. Nothing in this
module (or any caller) may treat it as instructions.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

# --------------------------------------------------------------------------
# Public contract
# --------------------------------------------------------------------------


class RetrievalRejected(Exception):
    """Raised for any policy violation: disallowed host, private/loopback/
    link-local target, oversized response, too many redirects, disallowed
    content type, timeout. Callers must treat this as "cannot retrieve,"
    never silently return partial/corrupted content."""


@dataclass(frozen=True)
class FetchPolicy:
    allowed_hosts: frozenset[str] | None  # None means "allow any PUBLIC host" (still SSRF-checked); a real allowlist is stricter
    max_bytes: int
    max_pages: int | None  # for PDFs specifically -- None if not applicable to the content type
    timeout_seconds: float
    max_redirects: int


@dataclass(frozen=True)
class FetchedDocument:
    url: str  # the ORIGINAL requested URL
    final_url: str  # after any redirects
    content_hash: str  # sha256 hex digest of the raw bytes
    content_type: str
    byte_count: int
    retrieved_at: datetime
    raw_text: str  # extracted plain text -- untrusted, never instructions


# Content types this module knows how to extract text from.
_SUPPORTED_CONTENT_TYPES = {"text/html", "text/plain", "application/pdf"}

# Redirect status codes we follow manually.
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# Resolver hook: (host, port) -> list of IP address strings. Overridable for
# tests so no real DNS/network is needed to exercise the SSRF logic.
Resolver = Callable[[str, int], list[str]]


def _default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise RetrievalRejected(f"DNS resolution failed for host {host!r}: {exc}") from exc
    ips = sorted({info[4][0] for info in infos})
    return ips


def _validate_public_ip(ip_str: str, host: str) -> None:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError as exc:
        raise RetrievalRejected(f"resolved address {ip_str!r} for host {host!r} is not a valid IP") from exc
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise RetrievalRejected(
            f"host {host!r} resolves to non-public address {ip_str} -- rejected (SSRF defense)"
        )


def _resolve_and_pin(host: str, port: int, resolver: Resolver) -> str:
    """Resolves `host` and validates every resolved IP is public. Returns the
    IP to pin the connection to (the first resolved address). Raising here
    means the caller must not attempt any network request for this hop."""
    ips = resolver(host, port)
    if not ips:
        raise RetrievalRejected(f"DNS resolution for host {host!r} returned no addresses")
    for ip_str in ips:
        _validate_public_ip(ip_str, host)
    return ips[0]


def _check_allowed_host(host: str, policy: FetchPolicy) -> None:
    if policy.allowed_hosts is not None and host.lower() not in {h.lower() for h in policy.allowed_hosts}:
        raise RetrievalRejected(f"host {host!r} is not in the configured allowlist")


class _PinnedBackend(AutoBackend):
    """Wraps the default httpcore async backend so that TCP connections for
    a specific (already-validated) hostname are redirected to a pinned IP
    address, instead of letting httpcore/anyio re-resolve DNS themselves.

    This is what closes the DNS-rebinding TOCTOU gap: the IP we validated as
    public is the IP we actually connect to, not merely an IP we glanced at
    before a second, independent resolution happens at connect time.
    """

    def __init__(self, pinned_host: str, pinned_ip: str) -> None:
        super().__init__()
        self._pinned_host = pinned_host
        self._pinned_ip = pinned_ip

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        target_host = self._pinned_ip if host == self._pinned_host else host
        return await super().connect_tcp(
            target_host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


def _build_pinned_client(host: str, pinned_ip: str, policy: FetchPolicy) -> httpx.AsyncClient:
    # BUG FOUND 2026-09-16 (first real network call through this path ever
    # made -- Phase 06 only unit-tested this transport with mocks, never a
    # live httpx.AsyncClient, exactly the disclosed gap in
    # docs/v3-execution/phase-06.md): `httpx.AsyncHTTPTransport.__init__`
    # has never accepted a `network_backend` kwarg in this httpx/httpcore
    # pairing (0.27.2/1.0.9) -- every real request crashed at construction
    # time with `TypeError: AsyncHTTPTransport.__init__() got an unexpected
    # keyword argument 'network_backend'`. httpx builds its own
    # httpcore.AsyncConnectionPool internally with no passthrough for this.
    # The real, supported way to inject a custom backend is to build that
    # pool directly and swap it onto the transport's `_pool` attribute --
    # `_pool` is httpx's own internal-but-stable extension point for
    # exactly this (custom transports/backends), not a hack around a
    # private detail that could vanish; httpx's own test suite does the
    # same swap.
    transport = httpx.AsyncHTTPTransport()
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(),
        network_backend=_PinnedBackend(host, pinned_ip),
    )
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,  # redirects are always followed manually, re-validated per hop
        timeout=policy.timeout_seconds,
        # httpx's default User-Agent ("python-httpx/0.27.2") gets a flat 403
        # from Wikipedia and plenty of other real sources (found 2026-09-16,
        # first real request through this path) -- identify honestly as what
        # this actually is, not a spoofed browser string.
        headers={"User-Agent": "IndianEquityResearchBot/0.1 (research pipeline evidence retrieval)"},
    )


def _default_port_for_scheme(scheme: str) -> int:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    raise RetrievalRejected(f"unsupported URL scheme {scheme!r}")


def _content_type_key(header_value: str | None) -> str:
    if not header_value:
        return ""
    return header_value.split(";")[0].strip().lower()


async def fetch_document(
    url: str,
    policy: FetchPolicy,
    *,
    resolver: Resolver = _default_resolver,
) -> FetchedDocument:
    """Fetches `url` under `policy`. See module docstring for the SSRF /
    redirect / streaming-abort behavior. Raises `RetrievalRejected` for every
    policy violation -- callers must never receive a partial document."""

    original_url = url
    current_url = url
    redirect_count = 0

    while True:
        parts = urlsplit(current_url)
        if parts.scheme not in ("http", "https"):
            raise RetrievalRejected(f"unsupported URL scheme {parts.scheme!r} in {current_url!r}")
        host = parts.hostname
        if not host:
            raise RetrievalRejected(f"could not determine hostname from URL {current_url!r}")
        port = parts.port or _default_port_for_scheme(parts.scheme)

        _check_allowed_host(host, policy)
        pinned_ip = _resolve_and_pin(host, port, resolver)

        client = _build_pinned_client(host, pinned_ip, policy)
        got_redirect = False
        try:
            async with client:
                try:
                    async with client.stream("GET", current_url) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if not location:
                                raise RetrievalRejected(
                                    f"redirect status {response.status_code} without Location header"
                                )
                            redirect_count += 1
                            if redirect_count > policy.max_redirects:
                                raise RetrievalRejected(
                                    f"exceeded max_redirects ({policy.max_redirects})"
                                )
                            current_url = urljoin(current_url, location)
                            got_redirect = True
                        else:
                            if response.status_code != 200:
                                raise RetrievalRejected(
                                    f"unexpected HTTP status {response.status_code} for {current_url!r}"
                                )

                            content_type = _content_type_key(response.headers.get("content-type"))
                            if content_type not in _SUPPORTED_CONTENT_TYPES:
                                raise RetrievalRejected(
                                    f"unsupported content type {content_type!r} for {current_url!r}"
                                )

                            raw = bytearray()
                            async for chunk in response.aiter_bytes():
                                raw.extend(chunk)
                                if len(raw) > policy.max_bytes:
                                    raise RetrievalRejected(
                                        f"response exceeded max_bytes ({policy.max_bytes}) while streaming {current_url!r}"
                                    )

                            raw_bytes = bytes(raw)
                            final_url = str(response.url)
                            content_type_full = response.headers.get("content-type", content_type)
                except httpx.TimeoutException as exc:
                    raise RetrievalRejected(f"timed out fetching {current_url!r}: {exc}") from exc
                except httpx.HTTPError as exc:
                    raise RetrievalRejected(f"transport error fetching {current_url!r}: {exc}") from exc
        except RetrievalRejected:
            raise

        if got_redirect:
            continue

        # Successfully got a terminal (non-redirect) 200 response -- extract text.
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        raw_text = _extract_text(content_type, raw_bytes, policy)

        return FetchedDocument(
            url=original_url,
            final_url=final_url,
            content_hash=content_hash,
            content_type=content_type_full,
            byte_count=len(raw_bytes),
            retrieved_at=datetime.now(timezone.utc),
            raw_text=raw_text,
        )


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------


class _VisibleTextHTMLParser(HTMLParser):
    """Dependency-free HTML-to-plain-text extractor. Strips tags and the
    contents of <script>/<style> (and a few other non-visible elements),
    collecting only visible text. Deliberately simple -- no NLP, just a
    bounded, safe tag stripper built on the stdlib parser."""

    _SKIP_CONTENT_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP_CONTENT_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_CONTENT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def get_text(self) -> str:
        return "\n\n".join(self._chunks)


def _decode_bytes(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _extract_text(content_type: str, raw_bytes: bytes, policy: FetchPolicy) -> str:
    if content_type == "text/plain":
        return _decode_bytes(raw_bytes)
    if content_type == "text/html":
        parser = _VisibleTextHTMLParser()
        parser.feed(_decode_bytes(raw_bytes))
        parser.close()
        return parser.get_text()
    if content_type == "application/pdf":
        return _extract_pdf_text(raw_bytes, policy)
    # _SUPPORTED_CONTENT_TYPES should make this unreachable, but never
    # silently return something that looks like real extracted text.
    raise RetrievalRejected(f"no text extractor available for content type {content_type!r}")


def _extract_pdf_text(raw_bytes: bytes, policy: FetchPolicy) -> str:
    """PDF extraction is STUBBED, not real. No PDF-parsing library
    (`pypdf`/`PyPDF2`/`pdfminer`/`pdfplumber`/`fitz`) is installed in this
    venv, and this venv's pip is broken (`python -m pip` -> "No module named
    pip"), so nothing can be installed here. Rather than silently skip or
    fabricate extracted text, this always raises a clear, specific
    rejection. See the task report for what dependency would be needed
    (`pypdf` is the natural, lightweight choice) -- it must be added to
    requirements.txt and approved/installed by the coordinator, not added
    here."""
    raise RetrievalRejected(
        "pdf extraction unavailable: no PDF-parsing library (e.g. pypdf) is installed in this environment"
    )


def extract_passages(document: FetchedDocument, *, max_passage_chars: int = 2000) -> list[str]:
    """Splits `document.raw_text` into passages, each <= max_passage_chars.
    Paragraph-boundary aware: splits on blank lines first (paragraphs / HTML
    text blocks), then further hard-splits any paragraph that is still too
    long. This is a simple whitespace/paragraph chunker, not an NLP
    splitter -- that's an acceptable baseline per the task contract."""
    if max_passage_chars <= 0:
        raise ValueError("max_passage_chars must be positive")

    text = document.raw_text
    raw_paragraphs = [p.strip() for p in text.split("\n\n")]
    paragraphs = [p for p in raw_paragraphs if p]

    passages: list[str] = []
    current = ""
    for para in paragraphs:
        # Hard-split any single paragraph longer than the limit on its own.
        para_pieces = [para[i : i + max_passage_chars] for i in range(0, len(para), max_passage_chars)] or [""]

        for piece in para_pieces:
            if not current:
                current = piece
                continue
            candidate = current + "\n\n" + piece
            if len(candidate) <= max_passage_chars:
                current = candidate
            else:
                passages.append(current)
                current = piece

    if current:
        passages.append(current)

    return passages
