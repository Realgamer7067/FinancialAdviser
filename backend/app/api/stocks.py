"""Stock-detail API (Section 56)."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.analysis import FinbertAnalysis, KronosPrediction, TechnicalFeatures
from app.models.fundamentals import FundamentalMetrics
from app.models.market import Instrument, MarketCandle
from app.models.news import NewsAnalysis, NewsItem
from app.models.recommendation import Recommendation
from app.schemas.recommendation import RecommendationCard
from app.schemas.stock import (
    FundamentalsOut,
    KronosOut,
    NewsArticleOut,
    NewsArticlesOut,
    NewsOut,
    PriceHistoryOut,
    PriceHistoryPoint,
    StockDetail,
    TechnicalsOut,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/{symbol}", response_model=StockDetail)
async def get_stock_detail(symbol: str, db: AsyncSession = Depends(get_db)):
    instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")

    latest_candle = (
        await db.execute(
            select(MarketCandle)
            .where(MarketCandle.instrument_id == instrument.id)
            .order_by(MarketCandle.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    fundamentals = (
        await db.execute(
            select(FundamentalMetrics)
            .where(FundamentalMetrics.instrument_id == instrument.id)
            .order_by(FundamentalMetrics.retrieved_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    technicals = (
        await db.execute(
            select(TechnicalFeatures)
            .where(TechnicalFeatures.instrument_id == instrument.id)
            .order_by(TechnicalFeatures.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    kronos = (
        await db.execute(
            select(KronosPrediction)
            .where(KronosPrediction.instrument_id == instrument.id)
            .order_by(KronosPrediction.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    news = (
        await db.execute(
            select(FinbertAnalysis)
            .where(FinbertAnalysis.instrument_id == instrument.id)
            .order_by(FinbertAnalysis.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    recommendation = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.instrument_id == instrument.id, Recommendation.user_id == SINGLE_USER_ID)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return StockDetail(
        symbol=instrument.symbol,
        name=instrument.name,
        sector=instrument.sector,
        latest_price=latest_candle.close if latest_candle else None,
        fundamentals=(
            FundamentalsOut(
                as_of_date=str(fundamentals.as_of_date),
                roe=fundamentals.roe,
                revenue_growth=fundamentals.revenue_growth,
                debt_to_equity=fundamentals.debt_to_equity,
                pe=fundamentals.pe,
                net_margin=fundamentals.net_margin,
                market_cap=fundamentals.market_cap,
                source=fundamentals.source,
            )
            if fundamentals
            else None
        ),
        technicals=(
            TechnicalsOut(
                rsi_14=technicals.rsi_14,
                trend=technicals.trend,
                volatility_30d=technicals.volatility_30d,
                drawdown_1y=technicals.drawdown_1y,
                macd_hist=technicals.macd_hist,
                beta=technicals.beta,
                computed_at=technicals.computed_at,
            )
            if technicals
            else None
        ),
        kronos=(
            KronosOut(
                forecast_horizon=kronos.forecast_horizon,
                direction=kronos.direction,
                predicted_return=kronos.predicted_return,
                confidence=kronos.confidence,
                generated_at=kronos.generated_at,
            )
            if kronos
            else None
        ),
        news=(
            NewsOut(
                sentiment_score=news.sentiment_score,
                confidence=news.confidence,
                article_count=news.article_count,
                window_start=news.window_start,
                window_end=news.window_end,
            )
            if news
            else None
        ),
        recommendation=(
            RecommendationCard(
                id=recommendation.id,
                symbol=instrument.symbol,
                name=instrument.name,
                recommendation=recommendation.recommendation,
                confidence=recommendation.confidence,
                score=recommendation.score,
                risk_level=recommendation.risk_level,
                risk_tier=recommendation.risk_tier,
                suggested_horizon=recommendation.suggested_horizon,
                strengths=recommendation.strengths,
                risks=recommendation.risks,
                rationale=recommendation.rationale,
                evidence=recommendation.evidence,
                fundamental_score=recommendation.fundamental_score,
                technical_score=recommendation.technical_score,
                kronos_score=recommendation.kronos_score,
                news_score=recommendation.news_score,
                portfolio_score=recommendation.portfolio_score,
                risk_score=recommendation.risk_score,
                model_agreement=recommendation.model_agreement,
                data_quality=recommendation.data_quality,
                generated_at=recommendation.generated_at,
            )
            if recommendation
            else None
        ),
    )


@router.get("/{symbol}/history", response_model=PriceHistoryOut)
async def get_stock_history(symbol: str, days: int = 180, db: AsyncSession = Depends(get_db)):
    days = max(1, min(days, 365))
    instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(MarketCandle)
            .where(
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.interval == "1d",
                MarketCandle.timestamp >= cutoff,
            )
            .order_by(MarketCandle.timestamp.asc())
        )
    ).scalars().all()

    return PriceHistoryOut(
        symbol=symbol,
        interval="1d",
        points=[PriceHistoryPoint(timestamp=r.timestamp, close=r.close) for r in rows],
    )


@router.get("/{symbol}/news", response_model=NewsArticlesOut)
async def get_stock_news(symbol: str, days: int = 30, db: AsyncSession = Depends(get_db)):
    """Raw ingested articles tagged to this symbol -- the aggregate sentiment
    on StockDetail.news is a summary of exactly these. Filtered in Python
    (`symbol in item.companies`), same as the pipeline's own
    _aggregate_news_sentiment -- NewsItem.companies is a JSON array, not
    portably queryable with SQL containment across the SQLite-in-tests /
    Postgres-in-prod split this repo relies on."""
    days = max(1, min(days, 365))
    instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(NewsAnalysis, NewsItem)
            .join(NewsItem, NewsAnalysis.news_id == NewsItem.id)
            .where(NewsItem.published_at >= cutoff)
            .order_by(NewsItem.published_at.desc())
        )
    ).all()
    matching = [(a, n) for a, n in rows if symbol in n.companies][:50]

    return NewsArticlesOut(
        symbol=symbol,
        articles=[
            NewsArticleOut(
                title=n.title,
                url=n.url,
                source=n.source,
                published_at=n.published_at,
                sentiment=a.sentiment,
                event_type=a.event_type,
                confidence=a.confidence,
            )
            for a, n in matching
        ],
    )
