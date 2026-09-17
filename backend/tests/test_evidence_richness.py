"""docs/V2-RETHINK.md P1: the council used to see only 6 fundamental fields
and 3 aggregate news numbers even though richer fundamentals and individual
articles were already fetched and stored. Verifies that already-available
data now actually reaches the evidence packet instead of being discarded."""

from datetime import datetime, timedelta, timezone

from app.models.market import Instrument
from app.models.news import NewsAnalysis, NewsItem
from app.pipelines.recommendation_pipeline import _aggregate_news_sentiment, _to_fundamental_evidence
from app.providers.base import FundamentalSnapshot


def test_fundamental_evidence_carries_previously_discarded_fields():
    snapshot = FundamentalSnapshot(
        symbol="TCS",
        as_of_date=datetime.now(timezone.utc).date(),
        roe=0.25,
        ebitda_margin=0.3,
        operating_cash_flow=1000.0,
        free_cash_flow=800.0,
        pb=8.0,
        ev_ebitda=20.0,
        dividend_yield=0.02,
        institutional_ownership=0.4,
        insider_holding_pct=0.15,
        source="test",
        retrieved_at=datetime.now(timezone.utc),
    )
    ev = _to_fundamental_evidence(snapshot)
    assert ev is not None
    assert ev.ebitda_margin == 0.3
    assert ev.operating_cash_flow == 1000.0
    assert ev.free_cash_flow == 800.0
    assert ev.pb == 8.0
    assert ev.ev_ebitda == 20.0
    assert ev.dividend_yield == 0.02
    assert ev.institutional_ownership == 0.4
    assert ev.insider_holding_pct == 0.15


async def test_news_aggregation_surfaces_inspectable_articles(db_session):
    now = datetime.now(timezone.utc)
    instrument = Instrument(symbol="TCS", exchange="NSE", name="TCS Ltd")
    db_session.add(instrument)
    await db_session.flush()
    news_item = NewsItem(
        source="economic_times_rss",
        title="TCS wins large multi-year deal",
        url="https://example.com/tcs-deal",
        published_at=now - timedelta(days=1),
        retrieved_at=now,
        companies=["TCS"],
        sectors=["IT"],
    )
    db_session.add(news_item)
    await db_session.flush()
    db_session.add(
        NewsAnalysis(
            news_id=news_item.id,
            event_type="guidance",
            sentiment=0.6,
            confidence=0.8,
            relevance=0.9,
            importance=0.9,
            model_name="FinBERT",
            model_version="test-v1",
            analyzed_at=now,
        )
    )
    await db_session.commit()

    result = await _aggregate_news_sentiment(db_session, "TCS", instrument.id)

    assert result is not None
    assert result["article_count"] == 1
    assert len(result["recent_articles"]) == 1
    article = result["recent_articles"][0]
    assert article["headline"] == "TCS wins large multi-year deal"
    assert article["url"] == "https://example.com/tcs-deal"
    assert article["event_type"] == "guidance"
