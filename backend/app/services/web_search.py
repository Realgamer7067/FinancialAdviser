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


async def discover_branch_urls(question: str, branch_type: str, *, api_key: str | None = None) -> list[str]:
    """Branch-scoped search query -- each of the 3 standard research
    branches asks a topically distinct question rather than sharing one
    generic search, so financials/events/peers don't all compete for the
    same handful of generic result URLs."""
    suffix = _BRANCH_QUERY_SUFFIX.get(branch_type, "")
    query = f"{question} {suffix}".strip()
    return await discover_urls(query, api_key=api_key)
