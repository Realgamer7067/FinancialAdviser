"""Coverage for GET /api/stocks/{symbol}/news -- raw ingested articles
filtered to those tagged with the requested symbol, within a day window."""

from datetime import datetime, timedelta, timezone

from app.models.market import Instrument
from app.models.news import NewsAnalysis, NewsItem


async def _seed_article(
    db_session,
    *,
    url: str,
    title: str,
    companies: list[str],
    published_at: datetime,
    sentiment: float = 0.3,
):
    item = NewsItem(
        source="test_fixture",
        title=title,
        url=url,
        published_at=published_at,
        retrieved_at=published_at,
        companies=companies,
        sectors=[],
    )
    db_session.add(item)
    await db_session.flush()

    db_session.add(
        NewsAnalysis(
            news_id=item.id,
            event_type="earnings",
            sentiment=sentiment,
            confidence=0.8,
            relevance=0.9,
            importance=0.5,
            model_name="FinBERT",
            model_version="test",
            analyzed_at=published_at,
        )
    )
    await db_session.commit()


async def test_news_returns_only_articles_tagged_to_symbol(client, db_session):
    db_session.add(Instrument(symbol="TESTCO", exchange="NSE", name="Test Co"))
    await db_session.commit()

    now = datetime.now(timezone.utc)
    await _seed_article(db_session, url="https://x/1", title="TESTCO beats estimates", companies=["TESTCO"], published_at=now)
    await _seed_article(db_session, url="https://x/2", title="OTHER news", companies=["OTHER"], published_at=now)

    res = await client.get("/api/stocks/TESTCO/news")
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "TESTCO"
    assert len(body["articles"]) == 1
    assert body["articles"][0]["title"] == "TESTCO beats estimates"


async def test_news_ordered_newest_first(client, db_session):
    db_session.add(Instrument(symbol="TESTCO", exchange="NSE", name="Test Co"))
    await db_session.commit()

    now = datetime.now(timezone.utc)
    await _seed_article(db_session, url="https://x/older", title="older", companies=["TESTCO"], published_at=now - timedelta(days=2))
    await _seed_article(db_session, url="https://x/newer", title="newer", companies=["TESTCO"], published_at=now)

    res = await client.get("/api/stocks/TESTCO/news")
    assert res.status_code == 200
    titles = [a["title"] for a in res.json()["articles"]]
    assert titles == ["newer", "older"]


async def test_news_respects_days_window(client, db_session):
    db_session.add(Instrument(symbol="TESTCO", exchange="NSE", name="Test Co"))
    await db_session.commit()

    now = datetime.now(timezone.utc)
    await _seed_article(db_session, url="https://x/old", title="old", companies=["TESTCO"], published_at=now - timedelta(days=60))

    res = await client.get("/api/stocks/TESTCO/news", params={"days": 30})
    assert res.status_code == 200
    assert res.json()["articles"] == []


async def test_news_unknown_symbol_404s(client):
    res = await client.get("/api/stocks/NOPE/news")
    assert res.status_code == 404
