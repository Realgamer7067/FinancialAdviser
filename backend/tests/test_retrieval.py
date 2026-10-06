"""V3 Phase 06 retrieval module (docs/V3-IMPLEMENTATION-PLAN.md section 9.3).
Coordinator-written verification pass -- the original retrieval worker's own
test file was lost when its session hit a rate limit mid-task; this covers
what's cheaply and reliably testable without real network: the SSRF
pre-checks (which run and raise BEFORE any HTTP call is attempted, so they
need no network mocking at all) and the pure text-extraction functions.

The SSRF pre-checks (which run and raise BEFORE any HTTP call is attempted)
need no network mocking at all and ARE covered below.

UPDATE 2026-09-16: the "IP-pinning against a real network stack" gap named
above is now closed -- `test_build_pinned_client_makes_a_real_http_request_
against_a_local_server` runs `_build_pinned_client` for real against a local
`http.server` instance, not mocked. This is exactly what caught a real bug
that every mocked test here had missed: `httpx.AsyncHTTPTransport(
network_backend=...)` was never valid on this httpx/httpcore pairing
(0.27.2/1.0.9), so every real research request crashed at transport
construction. Fixed in `app/services/retrieval.py`'s `_build_pinned_client`
by building the `httpcore.AsyncConnectionPool` directly instead of passing
an unsupported kwarg.

Added by an independent V3 Phase 10 release-acceptance review (2026-09-15):
`test_fetch_document_aborts_streaming_when_oversized_response_exceeds_max_bytes`
and `test_fetch_document_succeeds_when_response_is_within_max_bytes` monkeypatch
just `_build_pinned_client` to swap in `httpx.MockTransport`, keeping
`fetch_document`'s real streaming/byte-counting/abort logic in the loop --
this closes the specific gap of `oversized_response_generator` being present
as a fixture but never actually fed through the real fetch path."""

import asyncio

import pytest

from app.services.retrieval import (
    FetchPolicy,
    RetrievalRejected,
    _extract_pdf_text,
    _resolve_and_pin,
    _VisibleTextHTMLParser,
    extract_passages,
    fetch_document,
)
from app.services.source_corpus_fixtures import (
    malformed_pdf_bytes,
    oversized_response_generator,
    prompt_injection_attempt_text,
    ssrf_attempt_urls,
)
from datetime import datetime, timezone
from app.services.retrieval import FetchedDocument


def _policy(**overrides):
    base = dict(allowed_hosts=None, max_bytes=1_000_000, max_pages=None, timeout_seconds=5.0, max_redirects=3)
    base.update(overrides)
    return FetchPolicy(**base)


def _fake_resolver(ips):
    def resolver(host, port):
        return ips
    return resolver


def test_private_ip_rejected_before_any_network_call():
    with pytest.raises(RetrievalRejected):
        _resolve_and_pin("internal.example", 443, _fake_resolver(["10.0.0.5"]))


def test_loopback_rejected():
    with pytest.raises(RetrievalRejected):
        _resolve_and_pin("localhost", 443, _fake_resolver(["127.0.0.1"]))


def test_link_local_cloud_metadata_address_rejected():
    with pytest.raises(RetrievalRejected):
        _resolve_and_pin("metadata.internal", 80, _fake_resolver(["169.254.169.254"]))


def test_public_ip_accepted_by_resolver_check():
    # 93.184.216.34 is example.com's long-standing public IP -- a real
    # public address, used here only to prove the validator does NOT reject
    # every address, only non-public ones.
    ip = _resolve_and_pin("example.com", 443, _fake_resolver(["93.184.216.34"]))
    assert ip == "93.184.216.34"


def test_dns_resolution_failure_is_rejected_not_crashed():
    def failing_resolver(host, port):
        raise RetrievalRejected(f"no DNS for {host}")
    with pytest.raises(RetrievalRejected):
        _resolve_and_pin("nowhere.invalid", 443, failing_resolver)


def test_ssrf_attempt_urls_fixture_all_reference_non_public_targets():
    # Every URL the source-fixture worker catalogued as an SSRF attempt
    # pattern must have a host that, if resolved to its literal IP, this
    # module's own validator would reject -- cross-checks the two workers'
    # outputs actually agree.
    import ipaddress
    from urllib.parse import urlsplit

    for url in ssrf_attempt_urls():
        host = urlsplit(url).hostname
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            continue  # "localhost" isn't a literal IP -- skip, covered by test_loopback_rejected above
        assert ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def test_html_extraction_strips_script_and_style():
    html = "<html><body><p>Real content</p><script>alert(1)</script><style>.x{}</style></body></html>"
    parser = _VisibleTextHTMLParser()
    parser.feed(html)
    parser.close()
    text = parser.get_text()
    assert "Real content" in text
    assert "alert" not in text
    assert "{}" not in text


def test_extract_passages_bounds_length():
    doc = FetchedDocument(
        url="https://fixtures.internal.example/x", final_url="https://fixtures.internal.example/x",
        content_hash="deadbeef", content_type="text/plain", byte_count=10000,
        retrieved_at=datetime.now(timezone.utc), raw_text="word " * 3000,
    )
    passages = extract_passages(doc, max_passage_chars=500)
    assert len(passages) > 1
    assert all(len(p) <= 500 for p in passages)


def test_extract_passages_rejects_nonpositive_max_chars():
    doc = FetchedDocument(
        url="u", final_url="u", content_hash="h", content_type="text/plain", byte_count=1,
        retrieved_at=datetime.now(timezone.utc), raw_text="x",
    )
    with pytest.raises(ValueError):
        extract_passages(doc, max_passage_chars=0)


def test_prompt_injection_fixture_never_executed_as_instructions():
    # There is no LLM in this module at all -- prove the fixture's text
    # passes through extract_passages as inert data, unchanged in content.
    doc = FetchedDocument(
        url="u", final_url="u", content_hash="h", content_type="text/plain", byte_count=1,
        retrieved_at=datetime.now(timezone.utc), raw_text=prompt_injection_attempt_text(),
    )
    passages = extract_passages(doc, max_passage_chars=10000)
    assert "".join(passages).strip() != ""
    assert "IGNORE" in "".join(passages) or "INSTEAD" in "".join(passages)


def test_pdf_extraction_stubbed_with_clear_error_not_silent():
    with pytest.raises(RetrievalRejected):
        _extract_pdf_text(malformed_pdf_bytes(), _policy())


def test_malformed_pdf_fixture_is_not_valid_pdf():
    data = malformed_pdf_bytes()
    assert data.startswith(b"%PDF-")
    assert not data.rstrip().endswith(b"%%EOF")


def test_oversized_response_generator_matches_requested_size():
    data = oversized_response_generator(50_000)
    assert len(data) == 50_000


async def test_fetch_document_rejects_every_ssrf_attempt_url_end_to_end():
    # Runs each of source_corpus_fixtures.ssrf_attempt_urls() through the
    # REAL fetch_document() entry point (not just the lower-level
    # _resolve_and_pin helper above) -- confirms the hostile fixture is
    # actually rejected by the full public API a caller would use, with a
    # resolver that honestly reflects each URL's literal/hostname target.
    policy = _policy()
    import ipaddress
    from urllib.parse import urlsplit

    for url in ssrf_attempt_urls():
        host = urlsplit(url).hostname
        try:
            ip = ipaddress.ip_address(host)
            resolver = _fake_resolver([str(ip)])
        except ValueError:
            # "localhost" -- not a literal IP; a real resolver maps it to
            # loopback, so mimic that here rather than skipping the check.
            resolver = _fake_resolver(["127.0.0.1"])

        with pytest.raises(RetrievalRejected):
            await fetch_document(url, policy, resolver=resolver)


async def test_fetch_document_rejects_before_network_when_resolver_finds_private_ip():
    policy = _policy(max_bytes=1000)

    async def _run():
        return await fetch_document(
            "https://internal.example/doc", policy, resolver=_fake_resolver(["10.0.0.1"])
        )

    with pytest.raises(RetrievalRejected):
        await _run()


async def test_fetch_document_rejects_unsupported_scheme():
    policy = _policy()
    with pytest.raises(RetrievalRejected):
        await fetch_document("ftp://example.com/file", policy, resolver=_fake_resolver(["93.184.216.34"]))


def _mock_transport_client_factory(content: bytes, content_type: str = "text/plain", status_code: int = 200):
    """Builds a `_build_pinned_client`-shaped replacement backed by
    `httpx.MockTransport` instead of the real IP-pinned network backend --
    closes the gap this file's own module docstring flags ("the actual
    successful-fetch/.../streaming-abort behavior against a real or mocked
    HTTP transport ... neither was set up in this pass"). This does not
    exercise IP-pinning itself (that's still untested, as disclosed), but it
    does exercise fetch_document's real streaming byte-counting/abort logic
    end-to-end against a real httpx response stream, not just the fixture's
    own byte count."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, headers={"content-type": content_type}, content=content)

    def factory(host, pinned_ip, policy):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False, timeout=policy.timeout_seconds)

    return factory


async def test_fetch_document_aborts_streaming_when_oversized_response_exceeds_max_bytes(monkeypatch):
    # Real adversarial fixture from source_corpus_fixtures, fed through the
    # actual fetch_document streaming-abort path (not just checked for its
    # own byte count in isolation).
    oversized = oversized_response_generator(50_000)
    policy = _policy(max_bytes=1000)

    monkeypatch.setattr(
        "app.services.retrieval._build_pinned_client",
        _mock_transport_client_factory(oversized),
    )

    with pytest.raises(RetrievalRejected, match="max_bytes"):
        await fetch_document(
            "https://fixtures.internal.example/oversized", policy, resolver=_fake_resolver(["93.184.216.34"])
        )


async def test_fetch_document_succeeds_when_response_is_within_max_bytes(monkeypatch):
    small = oversized_response_generator(500)
    policy = _policy(max_bytes=1000)

    monkeypatch.setattr(
        "app.services.retrieval._build_pinned_client",
        _mock_transport_client_factory(small),
    )

    doc = await fetch_document(
        "https://fixtures.internal.example/small", policy, resolver=_fake_resolver(["93.184.216.34"])
    )
    assert doc.byte_count == 500
    assert doc.raw_text  # text/plain extraction ran for real


async def test_build_pinned_client_makes_a_real_http_request_against_a_local_server():
    """Closes the gap this file's own docstring names: every other test here
    monkeypatches `_build_pinned_client` itself, so `_PinnedBackend`'s real
    `connect_tcp` override and the transport construction it depends on were
    never actually exercised. They weren't: `httpx.AsyncHTTPTransport(
    network_backend=...)` doesn't exist as a constructor kwarg on this
    httpx/httpcore pairing (0.27.2/1.0.9) -- every real call crashed with
    `TypeError: AsyncHTTPTransport.__init__() got an unexpected keyword
    argument 'network_backend'` (found 2026-09-16, first genuine research
    session run against a real URL). Fixed by building the httpcore pool
    directly and swapping it onto `transport._pool`. This test proves both
    the construction no longer raises AND the IP-pin actually works: the
    server binds to 127.0.0.1, and `_build_pinned_client` is called with a
    host that does NOT resolve to that address, pinned to 127.0.0.1 anyway
    -- if pinning silently didn't work, this would attempt to connect to
    the (non-existent, on this network) real DNS target for that host name
    and fail or hang, not reach the local server."""
    import http.server
    import threading

    from app.services.retrieval import _build_pinned_client

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"real response from the local test server"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # keep test output quiet

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # A hostname that does NOT resolve to 127.0.0.1 on any real network --
        # if _PinnedBackend's connect_tcp override didn't actually redirect
        # to the pinned IP, this request would try to reach the real
        # fixtures.internal.example host defined in source_corpus_fixtures.py
        # (or fail DNS resolution) instead of ever hitting our local server.
        host = "fixtures.internal.example"
        client = _build_pinned_client(host, "127.0.0.1", _policy())
        try:
            response = await client.get(f"http://{host}:{port}/")
        finally:
            await client.aclose()
        assert response.status_code == 200
        assert response.content == b"real response from the local test server"
    finally:
        server.shutdown()
        thread.join(timeout=2)
