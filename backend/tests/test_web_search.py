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
