"""RSSNewsProvider (Section 7). Legitimate public syndicated feeds, not scraped
HTML. URLs below were verified against the publishers' own sites at build time;
re-verify periodically since publishers change feed layouts without notice.

Not included (unconfirmed exact feed URL at build time, don't invent -- Section
67): SEBI press releases, Moneycontrol. Add once verified.
"""

from datetime import datetime, timezone

import feedparser
import httpx

from app.providers.base import NewsProvider, RawNewsItem

FEEDS: dict[str, str] = {
    "economic_times_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "economic_times_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "rbi_press_releases": "https://www.rbi.org.in/pressreleases_rss.xml",
}


class RSSNewsProvider(NewsProvider):
    def __init__(self, feeds: dict[str, str] | None = None):
        self._feeds = feeds or FEEDS

    async def fetch_latest(self, since: datetime | None = None) -> list[RawNewsItem]:
        items: list[RawNewsItem] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for source_name, url in self._feeds.items():
                try:
                    resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    resp.raise_for_status()
                except httpx.HTTPError:
                    continue
                parsed = feedparser.parse(resp.content)
                retrieved_at = datetime.now(timezone.utc)
                for entry in parsed.entries:
                    published = _parse_published(entry)
                    if since and published and published < since:
                        continue
                    items.append(
                        RawNewsItem(
                            source=source_name,
                            title=entry.get("title", "").strip(),
                            url=entry.get("link", ""),
                            published_at=published or retrieved_at,
                            retrieved_at=retrieved_at,
                            summary=entry.get("summary"),
                        )
                    )
        return items


def _parse_published(entry) -> datetime | None:
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed_time:
        return None
    return datetime(*parsed_time[:6], tzinfo=timezone.utc)
