"""Web search source discovery for the research pipeline (added 2026-09-16).

Before this, every research branch needed the user to manually paste URLs --
there was no search capability anywhere in this codebase (V3 9.3's actual
search/entity-resolution tools were explicitly never built, per
research_orchestrator.py's own prior docstring). This module closes that gap
using Gemini's built-in Google Search grounding tool on the native
`generateContent` REST endpoint (the same endpoint `GeminiAdapter` in
app/models_iface/model_adapter.py already targets) -- NOT a hand-rolled
scraper, and NOT a substitute for this codebase's real verification: search
only DISCOVERS candidate URLs. Every discovered URL still goes through the
exact same `fetch_document` -> `extract_passages` -> `create_fact` ->
`verify_fact` pipeline as a manually-pasted URL, so a source the model
"found" gets exactly as much scrutiny as one a human pasted in. Search never
gets to assert a fact directly.

KNOWN LIMITATION (confirmed 2026-09-16, not guessed): Gemini's search-
grounding tool appears to sit behind a separate, much stricter quota than
plain generateContent calls on this project's free-tier keys -- all 7
configured keys returned 429 RESOURCE_EXHAUSTED for a `google_search`-tool
request while the identical keys succeeded immediately on a plain
(non-tool) request. `discover_urls` degrades to an empty list on any
failure rather than crashing or blocking the research session -- the
caller falls back to whatever manually-supplied URLs exist, exactly the
pre-search-tool behavior, never worse than before this module existed.
"""

import logging
import re
from urllib.parse import quote_plus, quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT_SECONDS = 15.0
_MAX_URLS_PER_QUERY = 5


async def discover_urls(query: str, *, api_key: str | None = None) -> list[str]:
    """Asks Gemini to search the web for `query` and returns the source
    URLs it actually grounded its answer on (deduplicated, capped). Never
    raises -- any failure (quota, network, malformed response, no
    candidates) degrades to an empty list, which callers must treat as
    "search found nothing usable," not "search succeeded with zero
    results" (those are the same observable outcome here on purpose --
    Section 50: a failed specialist is a missing signal, not a crash)."""
    key = api_key or settings.gemini_api_key
    if not key:
        return []

    url = f"{settings.gemini_base_url}/models/{settings.gemini_flash_lite_model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }
    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers={"x-goog-api-key": key}, json=body)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Gemini search grounding failed for %r: HTTP %s", query, exc.response.status_code)
        return []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Gemini search grounding failed for %r: %s", query, exc)
        return []

    try:
        candidates = data.get("candidates") or []
        if not candidates:
            return []
        chunks = candidates[0].get("groundingMetadata", {}).get("groundingChunks", []) or []
        urls: list[str] = []
        for chunk in chunks:
            web_uri = chunk.get("web", {}).get("uri")
            if web_uri and web_uri not in urls:
                urls.append(web_uri)
        return urls[:_MAX_URLS_PER_QUERY]
    except (AttributeError, TypeError, KeyError) as exc:
        logger.warning("Gemini search grounding response for %r had an unexpected shape: %s", query, exc)
        return []


_BRANCH_QUERY_SUFFIX = {
    "financials_valuation": "financial results, revenue, valuation, balance sheet",
    "events_governance": "recent news, management changes, regulatory events, governance",
    "peers_downside": "competitors, sector peers, risks, downside scenarios",
}


_QUESTION_FILLER = {"how", "is", "are", "was", "were", "what", "whats", "why", "does", "do", "did", "the", "a", "an", "about", "of", "on", "performing", "performance",
                    "doing", "going", "looking", "tell", "me", "please", "should", "i", "buy", "company", "stock", "share", "shares", "its", "it", "recently", "lately", "now", "recent"}
_NEWS_QUERY = {
    "financials_valuation": '"{s}" (results OR revenue OR profit OR earnings OR valuation) when:90d',
    "events_governance": '"{s}" (management OR board OR SEBI OR regulator OR acquisition OR announcement) when:30d',
    "peers_downside": '"{s}" (competition OR competitors OR risk OR outlook OR downgrade) when:90d',
}
_WIKI_API = "https://en.wikipedia.org/w/api.php"


def subject_of(question: str) -> str:
    """The company name left after the question boilerplate is removed ("How is Reliance Industries performing?" -> "Reliance Industries")."""
    words = [w for w in re.findall(r"[A-Za-z0-9&.'-]+", question) if w.lower() not in _QUESTION_FILLER]
    return " ".join(words[:6]) or question[:60]


def news_feed_url(subject: str, branch_type: str) -> str | None:
    template = _NEWS_QUERY.get(branch_type)
    if not template or not subject.strip():
        return None
    return f"https://news.google.com/rss/search?q={quote_plus(template.format(s=subject))}&hl=en-IN&gl=IN&ceid=IN:en"


async def wikipedia_url(subject: str) -> str | None:
    """The company's Wikipedia article, only when its title plainly matches the subject (never a near miss for a different company)."""
    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT_SECONDS) as client:
            r = await client.get(_WIKI_API, params={"action": "opensearch", "search": subject, "limit": 1, "format": "json"})
            r.raise_for_status()
            _q, titles, _d, urls = r.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    if not titles or not urls:
        return None
    first = subject.split()[0].lower()
    return urls[0] if first in titles[0].lower() else None


async def discover_known_sources(question: str, branch_type: str) -> list[str]:
    """Fixed, keyless sources for when search grounding returns nothing (its free-tier quota normally is exhausted): a Google News RSS search
    for the company, scoped to what the branch asks, and, for the financials branch, the company's Wikipedia article. Like any discovered
    address these only DISCOVER material; each still goes through fetch, extraction and verification. Search engines were tried first and
    block this machine's VPN address."""
    subject = subject_of(question)
    urls = []
    feed = news_feed_url(subject, branch_type)
    if feed:
        urls.append(feed)
    if branch_type == "financials_valuation":
        wiki = await wikipedia_url(subject)
        if wiki:
            urls.append(wiki)
    return urls


async def discover_branch_urls(question: str, branch_type: str, *, api_key: str | None = None) -> list[str]:
    """Branch-scoped search query -- each of the 3 standard research
    branches asks a topically distinct question rather than sharing one
    generic search, so financials/events/peers don't all compete for the
    same handful of generic result URLs."""
    suffix = _BRANCH_QUERY_SUFFIX.get(branch_type, "")
    query = f"{question} {suffix}".strip()
    urls = await discover_urls(query, api_key=api_key)
    if not urls and settings.web_search_fallback:
        urls = await discover_known_sources(question, branch_type)
    return urls
