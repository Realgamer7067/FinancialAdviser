"""app/services/web_search.py -- Gemini search-grounding source discovery,
added 2026-09-16. Everything here mocks httpx; no real network call."""

import httpx
import pytest

from app.services.web_search import discover_branch_urls, discover_urls


async def test_discover_urls_returns_empty_with_no_api_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert await discover_urls("some query") == []


async def test_discover_urls_parses_grounding_chunks(monkeypatch):
    response_body = {
        "candidates": [
            {
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://example.com/a", "title": "A"}},
                        {"web": {"uri": "https://example.com/b", "title": "B"}},
                        {"web": {"uri": "https://example.com/a", "title": "A dup"}},  # duplicate, must be deduped
                    ]
                }
            }
        ]
    }

    async def _fake_post(self, url, headers=None, json=None):
        return httpx.Response(200, json=response_body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    urls = await discover_urls("some query", api_key="fake-key")
    assert urls == ["https://example.com/a", "https://example.com/b"]


async def test_discover_urls_degrades_to_empty_on_http_error(monkeypatch):
    async def _fake_post(self, url, headers=None, json=None):
        request = httpx.Request("POST", url)
        return httpx.Response(429, json={"error": {"message": "quota"}}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    # Matches the real, confirmed behavior of this project's Gemini keys --
    # search grounding sits behind a stricter quota than plain generation.
    assert await discover_urls("some query", api_key="fake-key") == []


async def test_discover_urls_degrades_to_empty_on_malformed_response(monkeypatch):
    async def _fake_post(self, url, headers=None, json=None):
        return httpx.Response(200, json={"candidates": [{"no_grounding_metadata_here": True}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    assert await discover_urls("some query", api_key="fake-key") == []


async def test_discover_branch_urls_augments_query_per_branch(monkeypatch):
    seen_bodies = []

    async def _fake_post(self, url, headers=None, json=None):
        seen_bodies.append(json)
        return httpx.Response(200, json={"candidates": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await discover_branch_urls("How is Example Bank doing?", "financials_valuation", api_key="fake-key")
    await discover_branch_urls("How is Example Bank doing?", "peers_downside", api_key="fake-key")

    q1 = seen_bodies[0]["contents"][0]["parts"][0]["text"]
    q2 = seen_bodies[1]["contents"][0]["parts"][0]["text"]
    assert q1 != q2  # each branch gets a topically distinct query, not the same string
    assert "valuation" in q1
    assert "peers" in q2 or "competitors" in q2


def test_subject_is_what_is_left_after_the_question_boilerplate():
    from app.services.web_search import subject_of

    assert subject_of("How is Reliance Industries performing?") == "Reliance Industries"
    assert subject_of("What about HDFC Bank's recent performance") == "HDFC Bank's"
    assert subject_of("???") == "???"


def test_news_feed_urls_are_scoped_per_branch_and_encoded():
    from app.services.web_search import news_feed_url

    fin = news_feed_url("Reliance Industries", "financials_valuation")
    ev = news_feed_url("Reliance Industries", "events_governance")
    assert fin.startswith("https://news.google.com/rss/search?q=") and "Reliance+Industries" in fin and "results" in fin and "ceid=IN%3Aen" in fin.replace("ceid=IN:en", "ceid=IN%3Aen")
    assert fin != ev and "SEBI" in ev
    assert news_feed_url("", "events_governance") is None and news_feed_url("X", "unknown") is None


async def test_branch_discovery_uses_known_sources_only_when_gemini_finds_nothing(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "web_search_fallback", True)

    async def _post_empty(self, url, headers=None, json=None):
        return httpx.Response(429, json={"error": {"message": "quota"}}, request=httpx.Request("POST", url))

    async def _get(self, url, params=None):
        return httpx.Response(200, json=["Reliance", ["Reliance Industries"], [""], ["https://en.wikipedia.org/wiki/Reliance_Industries"]], request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _post_empty)
    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    fin = await discover_branch_urls("How is Reliance Industries performing?", "financials_valuation", api_key="k")
    assert fin[0].startswith("https://news.google.com/rss/search") and fin[1] == "https://en.wikipedia.org/wiki/Reliance_Industries"
    ev = await discover_branch_urls("How is Reliance Industries performing?", "events_governance", api_key="k")
    assert len(ev) == 1 and ev[0].startswith("https://news.google.com/rss/search")        # Wikipedia only on the financials branch

    # a Wikipedia title that does not match the subject is never used
    async def _get_other(self, url, params=None):
        return httpx.Response(200, json=["x", ["Totally Different Company"], [""], ["https://en.wikipedia.org/wiki/Other"]], request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _get_other)
    assert len(await discover_branch_urls("How is Reliance Industries performing?", "financials_valuation", api_key="k")) == 1

    # Gemini answering means nothing else is consulted
    async def _post_ok(self, url, headers=None, json=None):
        return httpx.Response(200, json={"candidates": [{"groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://g.example/x"}}]}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _post_ok)
    assert await discover_branch_urls("q", "peers_downside", api_key="k") == ["https://g.example/x"]


def test_feed_text_is_extracted_without_an_xml_parser():
    from app.services.retrieval import RetrievalRejected, _extract_feed_text

    xml = """<rss><channel><title>feed</title>
    <item><title>Reliance Q2 profit rises 5% &amp; beats estimates</title><pubDate>Wed, 01 Oct 2026 08:00:00 GMT</pubDate><source url="https://x">Economic Times</source>
    <description>&lt;a href="x"&gt;ignored&lt;/a&gt;</description></item>
    <item><title><![CDATA[SEBI notice to <b>Reliance</b> unit]]></title><source>Mint</source></item></channel></rss>"""
    text = _extract_feed_text(xml)
    assert "Reliance Q2 profit rises 5% & beats estimates (Economic Times, Wed, 01 Oct 2026 08:00:00 GMT)" in text and "SEBI notice to Reliance unit (Mint)" in text
    assert "ignored" not in text and "<" not in text
    try:
        _extract_feed_text("<rss></rss>")
    except RetrievalRejected:
        pass
    else:
        raise AssertionError("an empty feed must be a rejection, not empty text")
